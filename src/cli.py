"""
End-to-end pipeline entry point.

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


# -------------------------
# SSL: make urllib trust certifi's CA bundle (Windows often lacks system CAs).
# Must run BEFORE any code that downloads.
# Re-applied inside each worker process (Windows uses spawn).
# -------------------------
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

from src.extract_text_and_heading import run_one_pdf
from src.convert_text_raw_to_json import convert_folder
from src.merge_and_split_json import process_json_folder
from src.post_process_json import merge_all_lessons_to_one_json


# -------------------------
# Logging control
# -------------------------
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


# ==========================================================
# Worker for parallel PDF processing
# ==========================================================
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


# -------------------------
# Step 1: PDFs -> mirrored TXT (FAST)
# -------------------------
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
            elif status == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                failures.append({"pdf": pdf, "error": err or "unknown"})
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
                elif status == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                    failures.append({"pdf": pdf, "error": err or "unknown"})
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


# -------------------------
# Full E2E: PDFs -> Chunked JSON (+ optional merged)
# -------------------------
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
) -> Dict[str, str]:
    out_root = Path(out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    txt_root = out_root / "01_extract_txt_raw"
    json_raw_root = out_root / "02_convert_json_raw"
    json_chunked_root = out_root / "03_chunked_raw"
    merged_root = out_root / "04_merged_all"

    # 1) PDFs -> mirrored TXT
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
    )

    # 2) TXT -> JSON raw
    convert_folder(
        input_root=str(txt_root),
        output_root=str(json_raw_root),
        chunk_version=chunk_version,
    )

    # 3) JSON raw -> JSON chunked *MAIN CHUNKING
    process_json_folder(
        input_root=str(json_raw_root),
        output_root=str(json_chunked_root),
        min_tokens=min_tokens,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        overlap_units=overlap_units,
        chunk_version=chunk_version,
    )

    # 4) Merge all lessons
    merged_path = ""
    if merge_all:
        merged_root.mkdir(parents=True, exist_ok=True)
        merge_all_lessons_to_one_json(
            input_root=str(json_chunked_root),
            output_root=str(merged_root),
            out_version=merged_out_version,
        )
        merged_path = str(merged_root)

    return {
        "txt_root": str(txt_root),
        "json_raw_root": str(json_raw_root),
        "json_chunked_root": str(json_chunked_root),
        "merged_root": merged_path,
    }


def main() -> None:
    """Console entry point used by `uv run chunk-pipeline`."""
    import sys

    # Input root: default ./input, or pass as first argument
    input_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r".\input")

    # Auto-detect subject from input subfolder(s)
    # e.g. input/toan/ → subject = "toan", out_root = outputs/toan/
    subdirs = [d for d in input_root.iterdir() if d.is_dir()]
    if len(subdirs) == 1:
        subject = subdirs[0].name
    else:
        subject = input_root.name

    out_root = Path(r".\outputs") / subject

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
    )
    print("DONE. Outputs:")
    print(json.dumps(paths, ensure_ascii=False, indent=2))

    # 5) Export to ZIP (for "Import Lessons từ ZIP")
    from src.export_zip import export_to_zip, export_to_folder

    json_source = paths["json_chunked_root"]
    export_root = str(out_root / "05_export")

    print("\n" + "=" * 60)
    print("B5: Export to ZIP format")
    print("=" * 60)

    export_to_folder(json_source, str(Path(export_root) / "txt"))
    export_to_zip(json_source, str(Path(export_root) / f"{subject}.zip"))


if __name__ == "__main__":
    main()
