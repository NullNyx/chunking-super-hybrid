"""
CLI - End-to-end Pipeline Entry Point / Điều phối pipeline chính

Input:
- PDF files in input/

Output:
- Chunked JSON in outputs/

Workflow:
1. B1: PDF → TXT (Docling + CLIP heading detection)
2. B2: TXT → JSON raw (convert_folder)
3. B3: JSON chunking (semantic ~400 tokens)
4. B4: Merge lessons to per-book JSON
5. B5: Export ZIP for CMS

Run via:
    uv run chunk-pipeline
    python -m src.cli
    python main.py            (root-level shim)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple


# === SSL CONFIG ===
def _ensure_ssl_ca_bundle() -> None:
    try:
        import certifi
    except ImportError:
        return
    ca = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    os.environ.setdefault("CURL_CA_BUNDLE", ca)


_ensure_ssl_ca_bundle()

# HuggingFace Hub: suppress symlink warning on Windows, increase download timeout.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")


from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from src.b1_extract.extract_text_and_heading import run_one_pdf
from src.b2_convert.convert_text_raw_to_json import convert_folder
from src.b3_chunk.merge_and_split_json import process_json_folder
from src.b4_merge.post_process_json import merge_all_lessons_to_one_json
from src.pipeline_logger import PipelineLogger


# -------------------------
# === LOGGING CONTROL ===
def suppress_third_party_logs() -> None:
    for name in [
        "docling",
        "docling_core",
        "docling_defaults",
        "rapidocr",
        "RapidOCR",
        "onnxruntime",
        "transformers",
        "PIL",
    ]:
        logging.getLogger(name).setLevel(logging.ERROR)

    logging.getLogger().setLevel(logging.WARNING)
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# === WORKER ===

# === STEP 1: PDFs -> TXT ===
def _process_one_pdf_to_txt(
    pdf_path: str,
    input_root: str,
    output_txt_root: str,
    work_root: str,
    prototypes_path: str,
    labels_heading_json: str,
    n_pages: Optional[int],
    test_fast: bool,
    clip_score_threshold: float,
    clip_device: Optional[str],
    drop_unlabeled_images: bool,
    label_mode: str,
    overwrite: bool,
    cleanup_work: bool,
) -> Tuple[str, str, Optional[str], float]:
    """
    Returns: (status, pdf_path, error, seconds)
      status in {"ok", "skipped", "failed"}
    """
    _ensure_ssl_ca_bundle()
    suppress_third_party_logs()

    pdf_path_p = Path(pdf_path)
    input_root_p = Path(input_root)
    output_txt_root_p = Path(output_txt_root)
    work_root_p = Path(work_root)

    t0 = time.time()

    rel_pdf = pdf_path_p.relative_to(input_root_p)
    out_txt_path = (output_txt_root_p / rel_pdf).with_suffix(".txt")
    out_txt_path.parent.mkdir(parents=True, exist_ok=True)

    if out_txt_path.exists() and not overwrite:
        return ("skipped", str(pdf_path_p), None, time.time() - t0)

    per_pdf_work_dir = work_root_p / rel_pdf.with_suffix("")
    per_pdf_work_dir.mkdir(parents=True, exist_ok=True)

    if not Path(prototypes_path).exists():
        raise FileNotFoundError(f"prototypes_path not found: {prototypes_path}")
    if not Path(labels_heading_json).exists():
        raise FileNotFoundError(f"labels_heading_json not found: {labels_heading_json}")

    # Retry logic for transient errors (network, timeout, SSL)
    MAX_RETRIES = 3
    RETRY_ERRORS = (OSError, ConnectionError, TimeoutError)

    try:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                run_one_pdf(
                    pdf_path=pdf_path_p,
                    out_dir=per_pdf_work_dir,
                    prototypes_path=prototypes_path,
                    n_pages=n_pages,
                    test_fast=test_fast,
                    keep_docling_dir=True,
                    clip_score_threshold=clip_score_threshold,
                    path_labels_heading=labels_heading_json,
                    clip_device=clip_device,
                    drop_unlabeled_images=drop_unlabeled_images,
                    label_mode=label_mode,
                )

                produced_txt = per_pdf_work_dir / "raw_with_headings.txt"
                if not produced_txt.exists():
                    raise FileNotFoundError(f"Pipeline did not produce: {produced_txt}")

                out_txt_path.write_text(
                    produced_txt.read_text(encoding="utf-8", errors="ignore"),
                    encoding="utf-8",
                )

                return ("ok", str(pdf_path_p), None, time.time() - t0)

            except RETRY_ERRORS as e:
                if attempt < MAX_RETRIES:
                    wait = attempt * 10  # 10s, 20s, 30s
                    print(f"  [RETRY {attempt}/{MAX_RETRIES}] {pdf_path_p.name}: {type(e).__name__}: {e} — waiting {wait}s...", flush=True)
                    time.sleep(wait)
                    continue
                return ("failed", str(pdf_path_p), traceback.format_exc(), time.time() - t0)

            except Exception:
                return ("failed", str(pdf_path_p), traceback.format_exc(), time.time() - t0)

    finally:
        if cleanup_work:
            shutil.rmtree(per_pdf_work_dir, ignore_errors=True)


# === STEP 1: PDFs -> TXT ===
def pdfs_to_mirrored_txt(
    input_root: Union[str, Path],
    *,
    output_txt_root: Union[str, Path],
    prototypes_path: Union[str, Path],
    labels_heading_json: Union[str, Path],
    n_pages: Optional[int] = None,
    test_fast: bool = True,
    clip_score_threshold: float = 0.9,
    clip_device: Optional[str] = None,
    drop_unlabeled_images: bool = True,
    label_mode: str = "artifacts",
    recursive: bool = True,
    overwrite: bool = False,
    cleanup_work: bool = True,
    work_root: Optional[Union[str, Path]] = None,
    max_workers: int = 2,
    pipeline_logger: Optional[PipelineLogger] = None,
) -> Dict[str, int]:
    """
    Speed-ups:
    - Parallel PDF processing with ProcessPoolExecutor
    - Per-PDF timing logs
    """
    suppress_third_party_logs()

    input_root = Path(input_root).resolve()
    output_txt_root = Path(output_txt_root).resolve()
    output_txt_root.mkdir(parents=True, exist_ok=True)

    # convert relative -> absolute ONCE (important when using ProcessPool on Windows)
    prototypes_path = str(Path(prototypes_path).resolve())
    labels_heading_json = str(Path(labels_heading_json).resolve())

    if not Path(prototypes_path).exists():
        raise FileNotFoundError(f"prototypes_path not found: {prototypes_path}")
    if not Path(labels_heading_json).exists():
        raise FileNotFoundError(f"labels_heading_json not found: {labels_heading_json}")

    if not input_root.exists():
        raise FileNotFoundError(f"input_root not found: {input_root}")

    if work_root is None:
        work_root = output_txt_root / "_work_tmp"
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)

    def _is_real_pdf(p: Path) -> bool:
        name = p.name
        if not p.is_file():
            return False
        if p.suffix.lower() != ".pdf":
            return False
        if name.startswith("~$"):
            return False
        try:
            if p.stat().st_size < 1024:  # < 1KB
                return False
        except OSError:
            return False
        return True

    pdf_paths = (list(input_root.rglob("*.pdf")) if recursive else list(input_root.glob("*.pdf")))
    pdf_paths = [p for p in pdf_paths if _is_real_pdf(p)]
    pdf_paths.sort(key=lambda p: str(p).lower())

    stats = {"total": len(pdf_paths), "ok": 0, "skipped": 0, "failed": 0}
    failures: List[Dict[str, str]] = []
    timings: List[Dict[str, Union[str, float]]] = []

    if not pdf_paths:
        (output_txt_root / "_failures.json").write_text("[]", encoding="utf-8")
        (output_txt_root / "_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return stats

    # Avoid GPU contention when CLIP runs on CUDA.
    if clip_device and str(clip_device).lower().startswith("cuda"):
        max_workers = 1
    else:
        max_workers = max(1, int(max_workers))

    pbar = tqdm(total=len(pdf_paths), desc="1/4 PDFs -> TXT", unit="pdf")

    # When max_workers == 1, run in-process to avoid Windows spawn deadlocks
    # (PyTorch + multiprocessing on Windows is fragile).
    if max_workers <= 1:
        for pdf_path in pdf_paths:
            status, pdf, err, secs = _process_one_pdf_to_txt(
                str(pdf_path),
                str(input_root),
                str(output_txt_root),
                str(work_root),
                prototypes_path,
                labels_heading_json,
                n_pages,
                test_fast,
                clip_score_threshold,
                clip_device,
                drop_unlabeled_images,
                label_mode,
                overwrite,
                cleanup_work,
            )
            timings.append({"pdf": pdf, "seconds": float(secs), "status": status})
            if status == "ok":
                stats["ok"] += 1
                if pipeline_logger:
                    pipeline_logger.pdf_ok(Path(pdf).name, elapsed=secs)
            elif status == "skipped":
                stats["skipped"] += 1
                if pipeline_logger:
                    pipeline_logger.pdf_skipped(Path(pdf).name)
            else:
                stats["failed"] += 1
                failures.append({"pdf": pdf, "error": err or "unknown"})
                if pipeline_logger:
                    pipeline_logger.pdf_failed(Path(pdf).name, err or "unknown", elapsed=secs)
                print("\n" + "=" * 120)
                print(f"[FAILED] {pdf}")
                print(err or "unknown")
                print("=" * 120 + "\n")
            pbar.update(1)
            pbar.set_postfix(
                {"ok": stats["ok"], "skip": stats["skipped"], "fail": stats["failed"]}
            )
    else:
        futures = []
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            for pdf_path in pdf_paths:
                fut = ex.submit(
                    _process_one_pdf_to_txt,
                    str(pdf_path),
                    str(input_root),
                    str(output_txt_root),
                    str(work_root),
                    prototypes_path,
                    labels_heading_json,
                    n_pages,
                    test_fast,
                    clip_score_threshold,
                    clip_device,
                    drop_unlabeled_images,
                    label_mode,
                    overwrite,
                    cleanup_work,
                )
                futures.append(fut)

            for fut in as_completed(futures):
                try:
                    status, pdf, err, secs = fut.result()
                except Exception:
                    status, pdf, err, secs = ("failed", "unknown", traceback.format_exc(), 0.0)
                timings.append({"pdf": pdf, "seconds": float(secs), "status": status})

                if status == "ok":
                    stats["ok"] += 1
                    if pipeline_logger:
                        pipeline_logger.pdf_ok(Path(pdf).name, elapsed=secs)
                elif status == "skipped":
                    stats["skipped"] += 1
                    if pipeline_logger:
                        pipeline_logger.pdf_skipped(Path(pdf).name)
                else:
                    stats["failed"] += 1
                    failures.append({"pdf": pdf, "error": err or "unknown"})
                    if pipeline_logger:
                        pipeline_logger.pdf_failed(Path(pdf).name, err or "unknown", elapsed=secs)
                    if status == "failed":
                        print("\n" + "=" * 120)
                        print(f"[FAILED] {pdf}")
                        print(err or "unknown")
                        print("=" * 120 + "\n")
                pbar.update(1)
                pbar.set_postfix(
                    {"ok": stats["ok"], "skip": stats["skipped"], "fail": stats["failed"]}
                )

    pbar.close()

    if cleanup_work:
        shutil.rmtree(work_root, ignore_errors=True)

    (output_txt_root / "_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_txt_root / "_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_txt_root / "_timings.json").write_text(
        json.dumps(
            sorted(timings, key=lambda x: x["seconds"], reverse=True),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return stats


# === FULL E2E PIPELINE ===
def run_e2e_pdf_folder_to_chunked_json(
    input_pdfs_root: Union[str, Path],
    *,
    out_root: Union[str, Path],
    prototypes_path: Union[str, Path],
    labels_heading_json: Union[str, Path],
    n_pages: Optional[int] = None,
    test_fast: bool = True,
    clip_score_threshold: float = 0.9,
    clip_device: Optional[str] = None,
    drop_unlabeled_images: bool = True,
    label_mode: str = "artifacts",
    recursive: bool = True,
    overwrite_txt: bool = False,
    cleanup_work: bool = True,
    pdf_max_workers: int = 2,
    min_tokens: int = 200,
    target_tokens: int = 350,
    max_tokens: int = 650,
    overlap_units: int = 2,
    chunk_version: str = "v1",
    merge_all: bool = True,
    merged_out_version: str = "v2",
    pipeline_logger: Optional[PipelineLogger] = None,
) -> Dict[str, str]:
    out_root = Path(out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    txt_root = out_root / "01_extract_txt_raw"
    json_raw_root = out_root / "02_convert_json_raw"
    json_chunked_root = out_root / "03_chunked_raw"
    merged_root = out_root / "04_merged_all"

    # 1) PDFs -> mirrored TXT
    if pipeline_logger:
        pipeline_logger.step_start("B1", "PDFs -> TXT (Docling + CLIP heading)")
    pdfs_to_mirrored_txt(
        input_pdfs_root,
        output_txt_root=txt_root,
        prototypes_path=prototypes_path,
        labels_heading_json=labels_heading_json,
        n_pages=n_pages,
        test_fast=test_fast,
        clip_score_threshold=clip_score_threshold,
        clip_device=clip_device,
        drop_unlabeled_images=drop_unlabeled_images,
        label_mode=label_mode,
        recursive=recursive,
        overwrite=overwrite_txt,
        cleanup_work=cleanup_work,
        work_root=out_root / "_work_tmp",
        max_workers=pdf_max_workers,
        pipeline_logger=pipeline_logger,
    )
    if pipeline_logger:
        pipeline_logger.step_end("B1")

    # 2) TXT -> JSON raw
    if pipeline_logger:
        pipeline_logger.step_start("B2", "TXT -> JSON raw (convert_folder)")
    convert_folder(
        input_root=str(txt_root),
        output_root=str(json_raw_root),
        chunk_version=chunk_version,
    )
    if pipeline_logger:
        pipeline_logger.step_end("B2")

    # 3) JSON raw -> JSON chunked *MAIN CHUNKING
    if pipeline_logger:
        pipeline_logger.step_start("B3", "JSON chunking + overlap")
    process_json_folder(
        input_root=str(json_raw_root),
        output_root=str(json_chunked_root),
        min_tokens=min_tokens,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        overlap_units=overlap_units,
        chunk_version=chunk_version,
    )
    if pipeline_logger:
        pipeline_logger.step_end("B3")

    # 4) Merge all lessons
    merged_path = ""
    if merge_all:
        if pipeline_logger:
            pipeline_logger.step_start("B4", "Merge all lessons")
        merged_root.mkdir(parents=True, exist_ok=True)
        merge_all_lessons_to_one_json(
            input_root=str(json_chunked_root),
            output_root=str(merged_root),
            out_version=merged_out_version,
        )
        merged_path = str(merged_root)
        if pipeline_logger:
            pipeline_logger.step_end("B4")

    return {
        "txt_root": str(txt_root),
        "json_raw_root": str(json_raw_root),
        "json_chunked_root": str(json_chunked_root),
        "merged_root": merged_path,
    }


def _detect_subject_and_out_root(input_root: Path) -> Tuple[str, Path]:
    """Auto-detect subject from input subfolder(s) and return (subject, out_root)."""
    subdirs = [d for d in input_root.iterdir() if d.is_dir()]
    if len(subdirs) == 1:
        subject = subdirs[0].name
    else:
        subject = input_root.name
    out_root = Path(r".\outputs") / subject
    return subject, out_root


def _run_export_step(
    input_root: Path,
    out_root: Path,
    subject: str,
    *,
    use_olmocr: bool = False,
    pipeline_logger: Optional[PipelineLogger] = None,
) -> None:
    """
    B5: Page-based lesson splitting + ZIP export.

    Args:
        use_olmocr: If True, use olmOCR server for text extraction
                    (for PDFs with garbled fonts like Toán 9).
        pipeline_logger: Optional logger for structured run logging.
    """
    from src.b5_export.page_split import split_pdf_to_lessons
    from src.b5_export.export_zip import export_to_zip
    import re as _re

    print("\n" + "=" * 60)
    print(f"B5: Page-based lesson splitting + ZIP export"
          f"{' [olmOCR]' if use_olmocr else ''}")
    print("=" * 60)

    if pipeline_logger:
        pipeline_logger.step_start("B5", f"Page-based lesson splitting{' [olmOCR]' if use_olmocr else ''}")

    export_txt_root = out_root / "05_export" / "txt"
    pdf_files = list(Path(input_root).rglob("*.pdf"))

    for pdf_path in sorted(pdf_files):
        # Determine grade + volume from filename
        # Pattern 1: TiengViet1_T1 → grade=1, volume=1
        # Pattern 2: Toan_3_Tap_1 → grade=3, volume=1
        # Pattern 3: Toan_3 → grade=3, volume=None
        stem = pdf_path.stem

        # Find all numbers in filename
        numbers = _re.findall(r"\d+", stem)

        if len(numbers) >= 2:
            # Two numbers: first is grade, second is volume
            grade = int(numbers[0])
            volume = int(numbers[1])
        elif len(numbers) == 1:
            # One number: grade only
            grade = int(numbers[0])
            volume = None
        else:
            grade = 0
            volume = None

        lop_folder = f"Lop{grade}_{volume}" if volume else f"Lop{grade}"

        # Find raw_text for TOC (from work_tmp)
        rel = pdf_path.relative_to(Path(input_root))
        work_dir = out_root / "_work_tmp" / rel.with_suffix("")
        raw_text_path = work_dir / "raw_text.txt"

        if not raw_text_path.exists():
            print(f"  [SKIP] No raw_text for {pdf_path.name}")
            if pipeline_logger:
                pipeline_logger.lesson_skipped(pdf_path.name, "No raw_text.txt (TOC not available)")
            continue

        toc_text = raw_text_path.read_text(encoding="utf-8", errors="ignore")

        # Output: subject/Lop{grade}_{volume}/LT/lesson{N}.txt
        lesson_dir = export_txt_root / subject / lop_folder / "LT"

        print(f"\n  {pdf_path.name} -> {lesson_dir}")

        try:
            result = split_pdf_to_lessons(pdf_path, toc_text, lesson_dir,
                                          use_olmocr=use_olmocr,
                                          pipeline_logger=pipeline_logger)
            if pipeline_logger and not result:
                pipeline_logger.lesson_skipped(pdf_path.name, "No lessons extracted from TOC")
        except Exception as e:
            err_msg = traceback.format_exc()
            print(f"  [ERROR] {pdf_path.name}: {e}")
            if pipeline_logger:
                pipeline_logger.pdf_failed(pdf_path.name, err_msg)

    # Create ZIP from the export folder
    zip_path = str(out_root / "05_export" / f"{subject}.zip")
    print(f"\n  Creating ZIP: {zip_path}")
    try:
        export_to_zip(str(export_txt_root), zip_path)
    except Exception as e:
        if pipeline_logger:
            pipeline_logger.error(f"ZIP creation failed: {e}")

    if pipeline_logger:
        pipeline_logger.step_end("B5")


def main() -> None:
    """
    Console entry point: `uv run chunk-pipeline`

    Full pipeline (B1→B5): Docling extract + CLIP heading + chunking + page split.
    Uses pypdfium2 for text extraction (works for PDFs with normal fonts).
    """
    import sys

    # Input root: default ./input, or pass as first argument
    input_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r".\input")
    subject, out_root = _detect_subject_and_out_root(input_root)

    # Initialize pipeline logger
    plog = PipelineLogger(subject=subject)
    plog.info(f"Input: {input_root}")
    plog.info(f"Output: {out_root}")

    paths = run_e2e_pdf_folder_to_chunked_json(
        input_pdfs_root=str(input_root),
        out_root=str(out_root),
        prototypes_path=r".\assets\prototypes_heading.pt",
        labels_heading_json=r".\assets\labels_heading.json",
        n_pages=None,  # full PDF; đặt số nhỏ (5, 10) để test nhanh
        test_fast=True,
        clip_score_threshold=0.91,
        clip_device="cuda",  # RTX 3050 — nhanh gấp 5-10x so với CPU
        drop_unlabeled_images=True,
        label_mode="referenced",  # chỉ CLIP ảnh referenced trong markdown (nhanh hơn artifacts)
        recursive=True,
        overwrite_txt=False,
        cleanup_work=False,
        pdf_max_workers=1,  # single-process: tránh deadlock PyTorch + Windows spawn
        min_tokens=250,
        target_tokens=400,
        max_tokens=650,
        overlap_units=2,
        chunk_version="v1",
        merge_all=True,
        merged_out_version="v1",
        pipeline_logger=plog,
    )
    print("DONE (B1-B4). Outputs:")
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    plog.info("B1-B4 completed.")

    # B5: Export using pypdfium2 (normal fonts)
    _run_export_step(input_root, out_root, subject, use_olmocr=False, pipeline_logger=plog)

    # Finalize log
    plog.finish()


def main_ocr() -> None:
    """
    Console entry point: `uv run chunk-pipeline-ocr`

    olmOCR pipeline (B5 only): Skips Docling extraction (B1-B4) and uses
    olmOCR server for text extraction. Applies to ALL PDFs in the input folder
    (not just garbled-font ones).

    Requires:
    - B1 already run (raw_text.txt exists for TOC parsing)
    - olmOCR server running at https://olmocr.aibuddy.vn/ocr

    Usage:
        uv run chunk-pipeline-ocr [input_root]
    """
    import sys

    input_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r".\input")
    subject, out_root = _detect_subject_and_out_root(input_root)

    # Verify raw_text exists (B1 must have been run before)
    work_tmp = out_root / "_work_tmp"
    if not work_tmp.exists():
        print(f"ERROR: {work_tmp} not found.")
        print("You must run `chunk-pipeline` first (at least B1) to generate raw_text.txt for TOC parsing.")
        print("Then re-run this command to use olmOCR for text extraction.")
        sys.exit(1)

    # Initialize pipeline logger
    plog = PipelineLogger(subject=f"{subject}_ocr")
    plog.info(f"Input: {input_root}")
    plog.info(f"Output: {out_root}")

    print("=" * 60)
    print(f"olmOCR Pipeline — Subject: {subject}")
    print(f"Input: {input_root}")
    print(f"Output: {out_root}")
    print("=" * 60)
    print("\nSkipping B1-B4 (using existing raw_text for TOC).")
    print("Using olmOCR server for ALL PDFs.\n")

    # B5: Export ALL PDFs using olmOCR
    _run_export_step(input_root, out_root, subject, use_olmocr=True, pipeline_logger=plog)

    # Finalize log
    plog.finish()


def main_retry() -> None:
    """
    Console entry point: `uv run chunk-pipeline-retry`

    Retry failed lessons from a previous pipeline run.
    Reads the summary.json log file to find failed lessons and re-runs them.

    Usage:
        uv run chunk-pipeline-retry [input_root] [--max-retries N]
    """
    import sys
    import json
    from pathlib import Path

    # Enable UTF-8 output for Vietnamese characters
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    # Handle --help flag
    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
Retry failed lessons from a previous pipeline run.

Usage:
    uv run chunk-pipeline-retry [input_root] [--max-retries N]

Options:
    input_root      Path to input folder (default: ./input)
    --max-retries N  Maximum retry attempts (default: 3)

Example:
    uv run chunk-pipeline-retry
    uv run chunk-pipeline-retry ./input --max-retries 5
        """)
        sys.exit(0)

    max_retries = 3
    # Handle --max-retries before finding input_root
    if "--max-retries" in sys.argv:
        idx = sys.argv.index("--max-retries")
        if idx + 1 < len(sys.argv):
            max_retries = int(sys.argv[idx + 1])
            # Remove these args to find input_root
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]

    input_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r".\input")

    subject, out_root = _detect_subject_and_out_root(input_root)

    # Find the latest log file (try both normal and _ocr runs)
    log_dir = Path("logs")
    summary_files = (
        sorted(log_dir.glob(f"run_{subject}_*_summary.json"), reverse=True) +
        sorted(log_dir.glob(f"run_{subject}_ocr_*_summary.json"), reverse=True)
    )

    if not summary_files:
        print(f"ERROR: No summary.json found for subject '{subject}' in logs/")
        print("Run the pipeline first to generate logs.")
        sys.exit(1)

    summary_path = summary_files[0]
    print(f"Loading failures from: {summary_path.name}")

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    failures = summary.get("failures", [])
    if not failures:
        print("No failures found in the summary file.")
        sys.exit(0)

    print(f"Found {len(failures)} failed lessons to retry (max {max_retries} retries each)")

    # Group failures by PDF
    failures_by_pdf: dict[str, list[dict]] = {}
    for failure in failures:
        pdf = failure["pdf"]
        if pdf not in failures_by_pdf:
            failures_by_pdf[pdf] = []
        failures_by_pdf[pdf].append(failure)

    # Initialize logger for retry run
    plog = PipelineLogger(subject=f"{subject}_retry")
    plog.info(f"Retry run for {len(failures)} failed lessons")
    plog.info(f"Source log: {summary_path.name}")

    # Process each PDF with failures
    export_txt_root = out_root / "05_export" / "txt"

    for pdf_name, pdf_failures in failures_by_pdf.items():
        # Find the PDF file
        pdf_files = list(Path(input_root).rglob(pdf_name))
        if not pdf_files:
            print(f"[SKIP] PDF not found: {pdf_name}")
            plog.warning(f"PDF not found: {pdf_name}")
            continue
        pdf_path = pdf_files[0]

        # Determine grade/volume
        import re as _re
        grade_match = _re.search(r"[_\s](\d{1,2})[_\s]", pdf_path.stem)
        grade = int(grade_match.group(1)) if grade_match else 0
        volume_match = _re.search(r"[Tt](?:ap|ập)[_\s]*(\d+)", pdf_path.stem)
        volume = int(volume_match.group(1)) if volume_match else None
        lop_folder = f"Lop{grade}_{volume}" if volume else f"Lop{grade}"

        # Find raw_text for TOC
        rel = pdf_path.relative_to(Path(input_root))
        work_dir = out_root / "_work_tmp" / rel.with_suffix("")
        raw_text_path = work_dir / "raw_text.txt"

        if not raw_text_path.exists():
            print(f"[SKIP] No raw_text for {pdf_name}")
            continue

        toc_text = raw_text_path.read_text(encoding="utf-8", errors="ignore")

        # Output directory
        lesson_dir = export_txt_root / subject / lop_folder / "LT"
        lesson_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n  Retrying {len(pdf_failures)} lessons from {pdf_name}")

        # Retry each failed lesson
        from src.b5_export.page_split import split_pdf_to_lessons
        from src.b5_export.page_split import parse_toc_from_text, _split_pdf_to_lessons_olmocr
        from src.b1_extract.olmocr_extract import extract_pages_via_olmocr

        toc = parse_toc_from_text(toc_text)
        toc_by_num = {entry.lesson_num: entry for entry in toc}

        # Track retry results
        retry_ok = 0
        retry_failed = 0

        for failure in pdf_failures:
            lesson_num = failure["lesson_num"]
            title = failure.get("title", f"Bài {lesson_num}")
            error = failure.get("error", "Unknown")

            print(f"\n    Retry lesson {lesson_num}: {title[:30]}...")
            print(f"      Previous error: {error[:80]}")

            if lesson_num not in toc_by_num:
                print(f"      [SKIP] Lesson {lesson_num} not found in TOC")
                continue

            entry = toc_by_num[lesson_num]
            start = entry.start_page - 1  # 0-indexed
            end = start + 20  # Assume up to 20 pages per lesson

            # Retry loop
            for attempt in range(1, max_retries + 1):
                print(f"      Attempt {attempt}/{max_retries}...", end=" ")
                markdown, err = extract_pages_via_olmocr(
                    pdf_path, start, end, return_error=True
                )

                if markdown:
                    # Success - write the file
                    from src.b5_export.page_split import _markdown_to_plain_text
                    content = _markdown_to_plain_text(markdown)
                    out_text = f"##Title: Bài {lesson_num}. {title}\n\n{content}\n"
                    out_path = lesson_dir / f"lesson{lesson_num}.txt"
                    out_path.write_bytes(out_text.replace("\n", "\r\n").encode("utf-8"))
                    print(f"OK ({len(content)} chars)")
                    plog.lesson_ok(pdf_name, lesson_num, title)
                    retry_ok += 1
                    break
                else:
                    error_detail = err or "Empty response"
                    print(f"FAILED: {error_detail[:50]}")
                    if attempt < max_retries:
                        import time
                        time.sleep(2)  # Wait before retry
            else:
                print(f"      ❌ All {max_retries} retries failed")
                plog.lesson_failed(pdf_name, lesson_num, error, title=title)
                retry_failed += 1

        print(f"\n  Retry complete: {retry_ok} OK, {retry_failed} failed")

    plog.finish()
    print("\nRetry run complete!")


if __name__ == "__main__":
    main()
