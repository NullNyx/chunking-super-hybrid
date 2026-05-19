"""
olmOCR integration for PDF text extraction.

Uses the olmOCR server (hosted by Thành) to extract text from PDF files
that have garbled font encoding (e.g., UTM fonts in Toán 9).

The server renders PDF pages as images and performs OCR with a model
optimized for Vietnamese text, returning markdown output with:
- Full Vietnamese diacriticals
- LaTeX formulas
- HTML tables
- Image references

Usage:
    from src.olmocr_extract import extract_pdf_via_olmocr, extract_pages_via_olmocr

    # Extract entire PDF
    markdown = extract_pdf_via_olmocr("input/toan/Toan_9_Tap_1.pdf")

    # Extract specific page range
    markdown = extract_pages_via_olmocr("input/toan/Toan_9_Tap_1.pdf", start=4, end=6)
"""
from __future__ import annotations

import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Union

import requests

# Default olmOCR server URL (Thành's server)
OLMOCR_API_URL = "https://olmocr.aibuddy.vn/ocr"

# Request settings
REQUEST_TIMEOUT = 600  # 10 minutes per request
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries


def _safe_print(s: str) -> None:
    """Print with fallback for Windows console encoding issues."""
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass


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
) -> Optional[str]:
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

    Returns:
        Markdown text from OCR, or None if failed
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
                return data.get("markdown", "")
            else:
                last_error = f"HTTP {response.status_code}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    _safe_print(f"[olmOCR] Failed pages {start+1}-{end+1} of {pdf_path.name}: {last_error}")
    return None


def split_pdf_to_lesson_pdfs_and_ocr(
    pdf_path: Union[str, Path],
    toc: list,
    *,
    offset: int = 0,
    api_url: str = OLMOCR_API_URL,
    verbose: bool = True,
) -> dict:
    """
    Split PDF into per-lesson page ranges and OCR each via olmOCR.

    Args:
        pdf_path: Path to the full PDF
        toc: List of TOC entries with (lesson_num, title, start_page)
        offset: Page offset
        api_url: olmOCR server URL
        verbose: Print progress

    Returns:
        {lesson_num: (title, markdown_text)}
    """
    import fitz

    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    total_pages = doc.page_count
    doc.close()

    # Build page ranges
    results = {}
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

        if verbose:
            _safe_print(f"[olmOCR] Lesson {lesson_num}: '{title}' (pages {start+1}-{end+1})...")

        markdown = extract_pages_via_olmocr(pdf_path, start, end, api_url=api_url)

        if markdown:
            results[lesson_num] = (title, markdown)
            if verbose:
                _safe_print(f"  ✅ {len(markdown)} chars")
        else:
            if verbose:
                _safe_print(f"  ❌ Failed")

    return results
