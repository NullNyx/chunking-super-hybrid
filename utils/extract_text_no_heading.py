from __future__ import annotations

import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import json

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode


# =========================================================
# 0) Regex / constants
# =========================================================

IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

ARTIFACT_IMG_RE = re.compile(
    r'(?P<path>(?:[A-Za-z]:)?[^ \t\r\n"\'()]*?_artifacts[\\/][^ \t\r\n"\'()]+?\.(?:png|jpg|jpeg|webp))',
    flags=re.IGNORECASE,
)

DOCLING_IMG_COMMENT_RE = re.compile(r"<!--\s*Image\s*-->\s*", flags=re.IGNORECASE)
DOCLING_IMG_MISSING_RE = re.compile(
    r"<!--\s*🖼️❌\s*Image not available\..*?-->",
    flags=re.DOTALL,
)

PAGE_MARKERS = [
    re.compile(r"^\s*---\s*Page\s+(\d+)\s*---\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*<!--\s*Page\s+(\d+)\s*-->\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*#\s*Page\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE),
]

WINDOWS_PATH_LINE_RE = re.compile(r"^\s*\(?\s*[A-Za-z]:\\.*$", flags=re.IGNORECASE)
ONLY_OPEN_PAREN_RE = re.compile(r"^\s*\(\s*$")
ONLY_CLOSE_PAREN_RE = re.compile(r"^\s*\)\s*$")

_UNI_HEX_RE = re.compile(r"/uni([0-9a-fA-F]{4,6})")


# =========================================================
# 1) Text normalization / cleaning helpers
# =========================================================

def fix_uni_glyphs(text: str) -> str:
    def repl(m: re.Match) -> str:
        cp = int(m.group(1), 16)
        try:
            return chr(cp)
        except ValueError:
            return m.group(0)
    return _UNI_HEX_RE.sub(repl, text)


def normalize_weird_case(text: str) -> str:
    def fix_tok(tok: str) -> str:
        if not tok or tok.isspace():
            return tok
        if tok.isupper() and len(tok) <= 5:
            return tok
        letters = [c for c in tok if c.isalpha()]
        if not letters:
            return tok
        has_upper = any(c.isupper() for c in letters)
        has_lower = any(c.islower() for c in letters)
        if has_upper and has_lower:
            low = tok.lower()
            return low[:1].upper() + low[1:] if len(low) > 1 else low
        return tok

    parts = re.split(r"(\s+)", text)
    return "".join(fix_tok(p) if not p.isspace() else p for p in parts)


def fix_weird_vietnamese_glyph_noise(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("𞼜", "ực").replace("𞻺", "ữa").replace("𞼚", "ựa").replace("𞫼", "ắc")
    text = text.replace("", "*").replace("𞼌", "ực")
    text = text.replace("\u0301", "")
    return text


def strip_docling_comments(md: str) -> str:
    md = DOCLING_IMG_MISSING_RE.sub("", md)
    md = DOCLING_IMG_COMMENT_RE.sub("", md)
    return md


def compact_newlines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join([ln.rstrip() for ln in text.split("\n")])
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def cleanup_visual_noise_around_images(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if ONLY_OPEN_PAREN_RE.match(s) or ONLY_CLOSE_PAREN_RE.match(s):
            continue
        if WINDOWS_PATH_LINE_RE.match(ln.strip()):
            continue
        out.append(ln)
    cleaned = "\n".join(out)
    return compact_newlines(cleaned)


def safe_stem_for_windows(p: Path) -> str:
    s = p.stem.rstrip(" .")
    return s if s else "file"


def resolve_md_image_path(md_dir: Path, rel_path: str) -> Path:
    p = rel_path.strip().strip('"').strip("'").replace("\\", os.sep).replace("/", os.sep)
    p = os.path.normpath(p)
    return (md_dir / p).resolve()


# =========================================================
# 2) Slice markdown by pages (optional)
# =========================================================

def slice_markdown_first_n_pages(md_text: str, n_pages: int) -> Tuple[str, bool]:
    matches: List[Tuple[int, int]] = []
    for pat in PAGE_MARKERS:
        for m in pat.finditer(md_text):
            matches.append((m.start(), int(m.group(1))))
    if not matches:
        return md_text, False

    matches.sort(key=lambda x: x[0])
    start_pos = matches[0][0]

    end_pos = None
    for idx, (pos, page) in enumerate(matches):
        if page == n_pages:
            end_pos = matches[idx + 1][0] if idx + 1 < len(matches) else len(md_text)
            break
    if end_pos is None:
        end_pos = len(md_text)

    return md_text[start_pos:end_pos], True


def fallback_slice_by_chars(md_text: str, n_pages: Optional[int]) -> str:
    if not n_pages or n_pages <= 0:
        return md_text
    return md_text[: n_pages * 6000]


# =========================================================
# 3) Docling extraction (no OCR) -> markdown
# =========================================================

@dataclass
class ExtractResult:
    md_path: str
    docling_dir: str
    artifacts_dir: str
    md_slice: str
    used_page_markers: bool


def extract_pdf_to_markdown_no_ocr(
    pdf_path: Union[str, Path],
    *,
    n_pages: Optional[int],
    out_dir: Union[str, Path],
    test_fast: bool = True,
    keep_docling_dir: bool = True,
) -> ExtractResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    docling_dir = (out_dir / "_docling").resolve()
    docling_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = safe_stem_for_windows(pdf_path)
    md_path = (docling_dir / f"{safe_stem}.md").resolve()
    artifacts_dir = (docling_dir / f"{safe_stem}_artifacts").resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 1.2 if test_fast else 2.0
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    res = converter.convert(pdf_path)
    doc = res.document

    doc.save_as_markdown(
        md_path,
        artifacts_dir=artifacts_dir,
        image_mode=ImageRefMode.REFERENCED,
    )

    md_full = md_path.read_text(encoding="utf-8", errors="ignore")

    if not n_pages or n_pages <= 0:
        md_slice = md_full
        used_markers = False
    else:
        md_slice, used_markers = slice_markdown_first_n_pages(md_full, n_pages=n_pages)
        if not used_markers:
            md_slice = fallback_slice_by_chars(md_full, n_pages=n_pages)

    if not keep_docling_dir:
        shutil.rmtree(docling_dir, ignore_errors=True)

    return ExtractResult(
        md_path=str(md_path),
        docling_dir=str(docling_dir),
        artifacts_dir=str(artifacts_dir),
        md_slice=md_slice,
        used_page_markers=used_markers,
    )


# =========================================================
# 4) Replace images -> [Hình Ảnh k]
# =========================================================

def replace_images_with_placeholders(
    md_text: str,
    *,
    md_dir: Path,
    prefix: str = "Hình Ảnh",
) -> Tuple[str, List[Dict[str, Any]]]:
    md_text = strip_docling_comments(md_text)

    images: List[Dict[str, Any]] = []
    counter = 0

    def clean_tail_punct(s: str) -> str:
        return s.rstrip(")]}>.,;")

    def repl(m: re.Match) -> str:
        nonlocal counter, images
        raw_path = clean_tail_punct(m.group("path"))

        counter += 1
        placeholder = f"[{prefix} {counter}]"

        p_norm = raw_path.replace("/", os.sep).replace("\\", os.sep)
        if Path(p_norm).is_absolute():
            abs_p = Path(p_norm)
        else:
            abs_p = (md_dir / p_norm).resolve()

        images.append({
            "index": counter,
            "placeholder": placeholder,
            "image_path_rel_in_text": raw_path,
            "image_path_abs": str(abs_p),
            "exists": abs_p.exists(),
        })

        return f"\n{placeholder}\n"

    out = ARTIFACT_IMG_RE.sub(repl, md_text)
    out = re.sub(r"!\[[^\]]*\]", "", out)  # remove broken "![...]" pieces

    out = fix_uni_glyphs(out)
    out = fix_weird_vietnamese_glyph_noise(out)
    out = normalize_weird_case(out)

    out = compact_newlines(out)
    out = cleanup_visual_noise_around_images(out)
    return out, images


# =========================================================
# 5) Output helpers + 2 running options
# =========================================================

def make_output_txt_name(pdf_path: Path) -> str:
    return f"{safe_stem_for_windows(pdf_path)}.txt"


def get_out_dir_for_pdf(
    pdf_path: Path,
    *,
    output_mode: str,
    central_out_dir: Optional[Union[str, Path]],
) -> Path:
    """
    output_mode:
      - "sidecar": output next to pdf
      - "central": output into one folder (central_out_dir required)
    """
    mode = (output_mode or "").strip().lower()
    if mode == "sidecar":
        return pdf_path.parent.resolve()
    if mode == "central":
        if central_out_dir is None:
            raise ValueError("central_out_dir is required when output_mode='central'")
        p = Path(central_out_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    raise ValueError("output_mode must be 'sidecar' or 'central'")


def run_one_pdf(
    pdf_path: Union[str, Path],
    *,
    output_mode: str = "central",
    out_dir: Optional[Union[str, Path]] = None,   # used when output_mode="central"
    n_pages: Optional[int] = None,
    test_fast: bool = True,
    keep_docling_dir: bool = True,
    placeholder_prefix: str = "Hình Ảnh",
) -> Dict[str, Any]:
    """
    OPTION A: Run one PDF, write <pdf_name>.txt
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    final_out_dir = get_out_dir_for_pdf(pdf_path, output_mode=output_mode, central_out_dir=out_dir)

    # We still need a working dir for docling outputs. Use final_out_dir so paths resolve.
    ex = extract_pdf_to_markdown_no_ocr(
        pdf_path,
        n_pages=n_pages,
        out_dir=final_out_dir,
        test_fast=test_fast,
        keep_docling_dir=keep_docling_dir,
    )

    md_dir = Path(ex.md_path).parent
    text_out, images = replace_images_with_placeholders(ex.md_slice, md_dir=md_dir, prefix=placeholder_prefix)

    txt_name = make_output_txt_name(pdf_path)
    out_path = final_out_dir / txt_name
    out_path.write_text(text_out, encoding="utf-8")

    return {
        "pdf": str(pdf_path),
        "output_txt": str(out_path),
        "output_mode": output_mode,
        "out_dir": str(final_out_dir),
        "n_pages_requested": n_pages,
        "page_slicing_used_markers": ex.used_page_markers,
        "num_images": len(images),
    }


def run_folder(
    input_dir: Union[str, Path],
    *,
    output_mode: str = "central",
    out_dir: Optional[Union[str, Path]] = None,   # used when output_mode="central"
    recursive: bool = False,
    n_pages: Optional[int] = None,
    test_fast: bool = True,
    keep_docling_dir: bool = True,
    placeholder_prefix: str = "Hình Ảnh",
) -> List[Dict[str, Any]]:
    """
    OPTION B: Run all PDFs in a folder.
    Each PDF -> <pdf_name>.txt (same basename)
    """
    input_dir = Path(input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise NotADirectoryError(f"Input folder not found: {input_dir}")

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_files = sorted(input_dir.glob(pattern))

    results: List[Dict[str, Any]] = []
    for pdf in pdf_files:
        try:
            results.append(run_one_pdf(
                pdf,
                output_mode=output_mode,
                out_dir=out_dir,
                n_pages=n_pages,
                test_fast=test_fast,
                keep_docling_dir=keep_docling_dir,
                placeholder_prefix=placeholder_prefix,
            ))
        except Exception as e:
            results.append({"pdf": str(pdf), "error": repr(e)})
    return results


# =========================================================
# 6) Example usage
# =========================================================
if __name__ == "__main__":
    # # ===== OPTION A: single file =====
    # meta_one = run_one_pdf(
    #     pdf_path=r"E:\QuangNV\Matching_book_logic\GDCD\CDHT GDKTPL 12 CTST (Ruot ITB 17.02.25).pdf",
    #     output_mode="central",  # "central" or "sidecar"
    #     out_dir=r"E:\QuangNV\Matching_book_logic\GDCD_export_txt",  # required if central
    #     n_pages=None,
    #     test_fast=True,
    #     keep_docling_dir=True,
    #     placeholder_prefix="Hình Ảnh",
    # )
    # print(json.dumps(meta_one, ensure_ascii=False, indent=2))

    # ===== OPTION B: folder =====
    
    metas = run_folder(
        input_dir=r"E:\QuangNV\Matching_book_logic\GDCD",
        output_mode="central",  # "central" or "sidecar"
        out_dir=r"E:\QuangNV\Matching_book_logic\GDCD_export_txt",  # required if central
        recursive=False,
        n_pages=None,
        test_fast=True,
        keep_docling_dir=True,
        placeholder_prefix="Hình Ảnh",
    )
    print(json.dumps(metas, ensure_ascii=False, indent=2))