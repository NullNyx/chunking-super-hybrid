"""
B1 - OCR Fallback / Trích xuất text từ PDF qua OCR

Input:
- PDF file (đặc biệt các file có font garbled như UTM trong sách Toán)

Output:
- Markdown text với đầy đủ dấu tiếng Việt

Workflow:
1. Gửi PDF lên olmOCR server (render as images)
2. OCR với model tối ưu cho tiếng Việt
3. Trả về markdown: LaTeX, HTML tables, image references

Usage:
    from src.b1_extract.olmocr_extract import extract_pdf_via_olmocr

    markdown = extract_pdf_via_olmocr("input/toan/Toan_9_Tap_1.pdf")
"""
from __future__ import annotations

import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Union

import requests

# Default olmOCR server URL
OLMOCR_API_URL = "https://olmocr.aibuddy.vn/ocr"

# Request settings
REQUEST_TIMEOUT = 600  # 10 minutes per request
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries (fixed delay)


def _safe_print(s: str) -> None:
    """Print with fallback for Windows console encoding issues."""
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass


MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB - under Cloudflare limit
CHUNK_SIZE_PAGES = 20  # Pages per chunk


def _extract_large_pdf_in_chunks(
    pdf_path: Path,
    *,
    api_url: str,
    timeout: int,
    max_retries: int,
    retry_delay: int,
) -> Optional[str]:
    """
    Extract large PDF by splitting into page chunks and OCRing each.

    Args:
        pdf_path: Path to the large PDF file
        api_url: olmOCR server URL
        timeout: Request timeout in seconds
        max_retries: Number of retry attempts per chunk
        retry_delay: Seconds between retries

    Returns:
        Combined markdown text from all chunks, or None if any chunk failed
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    total_pages = doc.page_count
    doc.close()

    _safe_print(f"[olmOCR] Total pages: {total_pages}, chunk size: {CHUNK_SIZE_PAGES}")

    all_markdown: list[str] = []
    num_chunks = (total_pages + CHUNK_SIZE_PAGES - 1) // CHUNK_SIZE_PAGES

    for chunk_idx in range(num_chunks):
        start = chunk_idx * CHUNK_SIZE_PAGES
        end = min(start + CHUNK_SIZE_PAGES, total_pages) - 1

        _safe_print(f"[olmOCR] Processing chunk {chunk_idx + 1}/{num_chunks}: pages {start + 1}-{end + 1}...")

        result = extract_pages_via_olmocr(
            pdf_path, start, end,
            api_url=api_url, timeout=timeout,
            return_error=False,
        )

        if result is None:
            _safe_print(f"[olmOCR] Chunk {chunk_idx + 1} failed, aborting full extraction")
            return None

        all_markdown.append(result)

    combined = "\n\n".join(all_markdown)
    _safe_print(f"[olmOCR] Combined {len(all_markdown)} chunks: {len(combined)} total chars")
    return combined


def extract_pdf_via_olmocr(
    pdf_path: Union[str, Path],
    *,
    api_url: str = OLMOCR_API_URL,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    retry_delay: int = RETRY_DELAY,
) -> Optional[str]:
    """
    Send a PDF file to olmOCR server and return the markdown text.

    For large PDFs (>50MB), automatically splits into chunks to avoid
    Cloudflare 413 Payload Too Large errors.

    Args:
        pdf_path: Path to the PDF file
        api_url: olmOCR server URL
        timeout: Request timeout in seconds
        max_retries: Number of retry attempts
        retry_delay: Seconds between retries

    Returns:
        Markdown text from OCR, or None if failed
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        _safe_print(f"[olmOCR] File not found: {pdf_path}")
        return None

    file_size = pdf_path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        _safe_print(f"[olmOCR] File {pdf_path.name} ({file_size / 1024 / 1024:.1f}MB) > {MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB - splitting into chunks...")
        return _extract_large_pdf_in_chunks(pdf_path, api_url=api_url, timeout=timeout, max_retries=max_retries, retry_delay=retry_delay)

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            with open(pdf_path, "rb") as f:
                files = {
                    "file": (pdf_path.name, f, "application/pdf")
                }
                response = requests.post(api_url, files=files, timeout=timeout)

            if response.status_code == 200:
                data = response.json()
                markdown_text = data.get("markdown", "")
                return markdown_text
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                _safe_print(f"[olmOCR] Attempt {attempt}/{max_retries} failed: {last_error}")

        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
            _safe_print(f"[olmOCR] Attempt {attempt}/{max_retries}: {last_error}")
        except requests.exceptions.Timeout:
            last_error = f"Timeout after {timeout}s"
            _safe_print(f"[olmOCR] Attempt {attempt}/{max_retries}: {last_error}")
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            _safe_print(f"[olmOCR] Attempt {attempt}/{max_retries}: {last_error}")

        if attempt < max_retries:
            time.sleep(retry_delay)

    _safe_print(f"[olmOCR] All {max_retries} attempts failed for {pdf_path.name}: {last_error}")
    return None


def extract_pages_via_olmocr(
    pdf_path: Union[str, Path],
    start: int,
    end: int,
    *,
    api_url: str = OLMOCR_API_URL,
    timeout: int = REQUEST_TIMEOUT,
    return_error: bool = False,
) -> Union[Optional[str], tuple]:
    """
    Extract specific pages from a PDF via olmOCR.

    Creates a temporary PDF with only the specified pages, sends it to
    the olmOCR server, and returns the markdown text.

    Args:
        pdf_path: Path to the source PDF
        start: Start page (0-indexed, inclusive)
        end: End page (0-indexed, inclusive)
        api_url: olmOCR server URL
        timeout: Request timeout in seconds
        return_error: If True, returns (markdown_or_None, error_msg_or_None)

    Returns:
        If return_error=False: Markdown text from OCR, or None if failed
        If return_error=True: (markdown_or_None, error_msg_or_None)
    """
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))

    # Create temp PDF with selected pages
    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=start, to_page=end)

    # Save to bytes buffer
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    doc.close()

    # Send bytes to API
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            files = {
                "file": (f"{pdf_path.stem}_p{start+1}-{end+1}.pdf",
                         BytesIO(pdf_bytes), "application/pdf")
            }
            response = requests.post(api_url, files=files, timeout=timeout)

            if response.status_code == 200:
                data = response.json()
                result = data.get("markdown", "")
                return (result, None) if return_error else result
            else:
                last_error = f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            last_error = f"Timeout after {timeout}s"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    _safe_print(f"[olmOCR] Failed pages {start+1}-{end+1} of {pdf_path.name}: {last_error}")
    return (None, last_error) if return_error else None


def split_pdf_to_lesson_pdfs_and_ocr(
    pdf_path: Union[str, Path],
    toc: list,
    *,
    offset: int = 0,
    api_url: str = OLMOCR_API_URL,
    verbose: bool = True,
    max_workers: int = 5,
) -> dict:
    """
    Split PDF into per-lesson page ranges and OCR each via olmOCR.
    Uses ThreadPoolExecutor for parallel requests (I/O-bound).

    Args:
        pdf_path: Path to the full PDF
        toc: List of TOC entries with (lesson_num, title, start_page)
        offset: Page offset
        api_url: olmOCR server URL
        verbose: Print progress
        max_workers: Number of concurrent olmOCR requests (default 5)

    Returns:
        {lesson_num: (title, markdown_text)}
    """
    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    total_pages = doc.page_count
    doc.close()

    # Build tasks list
    tasks = []
    for i, entry in enumerate(toc):
        lesson_num = entry["lesson_num"]
        title = entry["title"]
        start = entry["start_page"] + offset - 1  # convert to 0-indexed

        if i + 1 < len(toc):
            end = toc[i + 1]["start_page"] + offset - 2  # page before next lesson
        else:
            end = total_pages - 1

        if start < 0 or start >= total_pages:
            continue
        end = min(end, total_pages - 1)
        tasks.append((lesson_num, title, start, end))

    if verbose:
        _safe_print(f"[olmOCR] {len(tasks)} lessons, parallel={max_workers}")

    results = {}

    def _ocr_lesson(lesson_num, title, start, end):
        if verbose:
            _safe_print(f"[olmOCR] Lesson {lesson_num}: '{title}' (pages {start+1}-{end+1})...")
        markdown = extract_pages_via_olmocr(pdf_path, start, end, api_url=api_url)
        return lesson_num, title, markdown

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_lesson, ln, t, s, e): ln
            for ln, t, s, e in tasks
        }

        for future in as_completed(futures):
            try:
                lesson_num, title, markdown = future.result()
            except Exception as exc:
                lesson_num = futures[future]
                if verbose:
                    _safe_print(f"  ❌ Lesson {lesson_num} exception: {exc}")
                continue

            if markdown:
                results[lesson_num] = (title, markdown)
                if verbose:
                    _safe_print(f"  ✅ Lesson {lesson_num}: {len(markdown)} chars")
            else:
                if verbose:
                    _safe_print(f"  ❌ Lesson {lesson_num} failed")

    return results


def extract_pdf_via_olmocr_to_files(
    pdf_path: Union[str, Path],
    *,
    out_dir: Union[str, Path],
    path_labels_heading: Union[str, Path],
    api_url: str = OLMOCR_API_URL,
    timeout: int = REQUEST_TIMEOUT,
) -> Optional[dict]:
    """
    OCR a whole PDF and materialize B1-like raw text artifacts.

    This writes:
    - raw_markdown.txt: markdown returned by olmOCR
    - raw_text.txt: normalized plain text used by downstream pipeline steps
    """
    from src.b1_extract.extract_text_and_heading import inject_headings
    from src.b5_export.page_split import _markdown_to_plain_text

    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    markdown = extract_pdf_via_olmocr(pdf_path, api_url=api_url, timeout=timeout)
    if not markdown:
        return None

    raw_text = _markdown_to_plain_text(markdown).strip() + "\n"
    empty_labels_path = out_dir / "labels.tsv"
    empty_labels_path.write_text("", encoding="utf-8")
    text_with_headings, inserted, dropped = inject_headings(
        label_tsv_path=empty_labels_path,
        text_with_images=markdown,
        path_labels_heading=path_labels_heading,
        drop_unlabeled_images=True,
    )

    (out_dir / "raw_markdown.txt").write_text(markdown, encoding="utf-8")
    (out_dir / "raw_text.txt").write_text(raw_text, encoding="utf-8")
    (out_dir / "raw_with_headings.txt").write_text(text_with_headings, encoding="utf-8")

    return {
        "pdf": str(pdf_path),
        "out_dir": str(out_dir),
        "raw_markdown_path": str(out_dir / "raw_markdown.txt"),
        "raw_text_path": str(out_dir / "raw_text.txt"),
        "raw_with_headings_path": str(out_dir / "raw_with_headings.txt"),
        "num_headings_inserted": inserted,
        "num_images_dropped": dropped,
    }
