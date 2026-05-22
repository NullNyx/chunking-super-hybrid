"""
Page-based lesson splitting using TOC + pypdfium2.

Strategy:
1. Parse TOC from Docling-extracted text → {lesson_num: (title, start_page)}
2. Extract text per page using pypdfium2 (fast, no layout model needed)
3. Group pages by lesson range → each lesson gets its exact page content
4. Output: dict mapping lesson_num → (title, content)

This replaces the fuzzy title-matching approach with precise page boundaries.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass


def _safe_print(s: str) -> None:
    """Print with fallback for Windows console encoding issues."""
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pypdfium2 as pdfium

# Known section headers/footers that appear as layout artifacts in PDF pages
_KNOWN_SECTION_HEADERS = {
    "khám phá",
    "luyện tập",
    "chủ đề",
    "hoạt động hoạt động",
    "luyện tập luyện tập",
    "khởi động",
    "ghi nhớ",
    "vận dụng",
    "thực hành",
}

# Compiled regex for "Số" pattern lines (e.g. "Số", "Số 5", "Số12")
_SO_PATTERN = re.compile(r"^Số\s?\d*$")


def clean_lesson_text(content: str, title: str, lesson_num: int = 0) -> str:
    """
    Clean layout artifacts from extracted PDF page text.

    Removes:
    - Standalone page numbers (lines matching ^\\d+$)
    - Known section headers/footers (case-insensitive exact match)
    - "Số" pattern lines (matching ^Số\\s?\\d*$)
    - Duplicate lesson title in body (exact "Bài {N}" and title variants)
    - Chapter headers (all-uppercase lines in first 10 non-empty lines)
    - Sidebar labels (e.g. "1 ôn tập và bổ sung Chủ đề")
    - Excessive blank lines (3+ consecutive newlines collapsed to 2)

    Preserves all other content unchanged.
    """
    lines = content.splitlines()
    filtered: list[str] = []
    title_lower = title.strip().lower()
    title_upper = title.strip().upper()
    title_removed = False
    bai_removed = False

    # Build title variants for duplicate detection
    title_variants_lower = {title_lower, title_upper.lower(), title.strip().lower()}

    for line in lines:
        stripped = line.strip()

        # Remove standalone page numbers (lines with only digits)
        if stripped and re.match(r"^\d+$", stripped):
            continue

        # Remove known section headers (case-insensitive exact match)
        if stripped and stripped.lower() in _KNOWN_SECTION_HEADERS:
            continue

        # Remove "Số" pattern lines
        if stripped and _SO_PATTERN.match(stripped):
            continue

        # Rule 1a: Remove duplicate "Bài {N}" standalone line
        if not bai_removed and lesson_num > 0:
            if re.match(rf"^Bài\s+{lesson_num}\s*$", stripped, re.IGNORECASE):
                bai_removed = True
                continue

        # Rule 1b: Remove duplicate title (case-insensitive exact match)
        if not title_removed and stripped and stripped.lower() in title_variants_lower:
            title_removed = True
            continue

        # Rule 3: Remove sidebar labels like "1 ôn tập và bổ sung Chủ đề"
        if re.match(r"^\d+\s+.+\s+Chủ đề\s*$", stripped):
            continue

        filtered.append(line)

    # Rule 2: Remove chapter headers (all-uppercase lines in first ~10 non-empty lines)
    # These are chapter titles like "MỘT SỐ ĐƠN VỊ ĐO ĐỘ DÀI, KHỐI LƯỢNG..."
    cleaned: list[str] = []
    non_empty_count = 0
    for line in filtered:
        stripped = line.strip()
        if stripped:
            non_empty_count += 1

        # Only check first 10 non-empty lines
        if non_empty_count <= 10 and stripped:
            # Chapter header: all uppercase, > 5 chars, no math symbols
            if (stripped.isupper()
                and len(stripped) > 5
                and "=" not in stripped
                and "?" not in stripped
                and "×" not in stripped
                and ":" not in stripped
                and not re.match(r"^\d", stripped)):
                continue

        cleaned.append(line)

    # Rejoin lines and collapse 3+ consecutive newlines to exactly 2
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result


@dataclass
class TocEntry:
    lesson_num: int
    title: str
    start_page: int  # 1-indexed (as printed in book)


def parse_toc_from_text(text: str) -> List[TocEntry]:
    """
    Parse table of contents from Docling-extracted text.

    Supports two formats:
    1. Table format (lớp 3-5): |  | Bài 1. Ôn tập các số đến 1 000  |  6 |
    2. Plain text format (lớp 6+): "Bài 1. Tập hợp" followed by page number on next line
    """
    # Try table format first
    # Format A (lớp 3-5): |  | Bài 1. Ôn tập các số đến 1 000  |  6 |
    # Format B (lớp 7-9): | Bài 1. Tập hợp các số hữu tỉ  |  5 |
    TOC_TABLE_RE = re.compile(
        r"\|\s*Bài\s+(\d+)\.\s*(.+?)\s*\|\s*(\d+)\s*\|"
    )
    entries: List[TocEntry] = []
    for line in text.splitlines():
        m = TOC_TABLE_RE.search(line)
        if m:
            entries.append(TocEntry(
                lesson_num=int(m.group(1)),
                title=m.group(2).strip(),
                start_page=int(m.group(3)),
            ))

    if entries:
        return entries

    # Fallback: plain text format (lớp 6+)
    # Pattern: "Bài X. Title" on one line, page number on next line(s)
    lines = text.splitlines()
    TOC_PLAIN_RE = re.compile(r"^\s*Bài\s+(\d+)\.\s*(.+?)\s*$")
    # Variant: title ends with page number on same line (e.g. "Bài 19. Hình chữ nhật. Hình thoi. 83")
    TOC_PLAIN_INLINE_RE = re.compile(r"^\s*Bài\s+(\d+)\.\s*(.+?)\s+(\d+)\s*$")

    for i, line in enumerate(lines):
        m = TOC_PLAIN_RE.match(line)
        if m:
            lesson_num = int(m.group(1))
            title = m.group(2).strip()

            # Look for page number on next line(s), searching further for multi-line titles
            page_num = 0
            for j in range(i + 1, min(i + 6, len(lines))):
                next_line = lines[j].strip()
                if next_line and re.match(r"^\d+$", next_line):
                    page_num = int(next_line)
                    break

            # If no standalone page number found, check if title ends with a number
            # (e.g. "Bài 19. Hình chữ nhật. Hình thoi. 83")
            if page_num == 0:
                m_inline = TOC_PLAIN_INLINE_RE.match(line)
                if m_inline:
                    page_num = int(m_inline.group(3))
                    title = m_inline.group(2).strip()

            # Only add if we found a page number (confirms this is TOC, not body text)
            if page_num > 0:
                entries.append(TocEntry(
                    lesson_num=lesson_num,
                    title=title,
                    start_page=page_num,
                ))

    return entries


def extract_pages_text(pdf_path: Union[str, Path], *, use_olmocr: bool = False) -> Dict[int, str]:
    """
    Extract text from each page using pypdfium2.
    If use_olmocr=True, delegates to olmOCR server instead.

    Args:
        pdf_path: Path to the PDF file
        use_olmocr: Use olmOCR server for extraction (for PDFs with garbled fonts)

    Returns: {page_num (1-indexed): text}
    """
    pdf_path = Path(pdf_path)

    if use_olmocr:
        _safe_print(f"[olmOCR] Using olmOCR server for {pdf_path.name}...")
        return _extract_pages_via_olmocr(pdf_path)

    # Normal extraction via pypdfium2
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages: Dict[int, str] = {}
    for i in range(len(pdf)):
        page = pdf[i]
        textpage = page.get_textpage()
        text = textpage.get_text_bounded()
        pages[i + 1] = text  # 1-indexed
        textpage.close()
        page.close()
    pdf.close()
    return pages


def _extract_pages_via_olmocr(pdf_path: Path) -> Dict[int, str]:
    """
    Extract all pages via olmOCR server.
    Returns: {page_num (1-indexed): text}
    """
    from src.olmocr_extract import extract_pdf_via_olmocr

    markdown = extract_pdf_via_olmocr(pdf_path)
    if not markdown:
        _safe_print(f"[olmOCR] Failed to extract {pdf_path.name}, falling back to pypdfium2")
        pdf = pdfium.PdfDocument(str(pdf_path))
        pages: Dict[int, str] = {}
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            pages[i + 1] = textpage.get_text_bounded()
            textpage.close()
            page.close()
        pdf.close()
        return pages

    # olmOCR returns continuous markdown — store as single entry
    pdf = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(pdf)
    pdf.close()

    pages = {1: markdown}
    for i in range(2, total_pages + 1):
        pages[i] = ""
    return pages


def split_by_toc_pages(
    pdf_path: Union[str, Path],
    toc_text: str,
    *,
    offset: int = 0,
) -> Dict[int, Tuple[str, str]]:
    """
    Split PDF content into lessons using TOC page numbers.

    Args:
        pdf_path: path to PDF file
        toc_text: text containing the TOC (from Docling extract)
        offset: page offset if PDF page numbers differ from printed numbers
                (e.g. if cover is page 1 in PDF but page 0 in book)

    Returns:
        {lesson_num: (title, content)}
    """
    toc = parse_toc_from_text(toc_text)
    if not toc:
        return {}

    pages = extract_pages_text(pdf_path)
    total_pages = max(pages.keys()) if pages else 0

    # Determine page offset by checking if first TOC entry's page exists
    # TOC says "Bài 1 → page 6" — check if page 6 has relevant content
    if offset == 0 and toc:
        first_page = toc[0].start_page
        # Heuristic: if PDF has fewer pages than TOC expects, there's likely
        # a cover offset. Most Vietnamese textbooks: PDF page 1 = book page 1.
        # But some have cover pages not counted.
        # We'll auto-detect by checking if the first lesson's title appears
        # near the expected page.
        pass  # Default offset=0 works for most cases

    # Sort TOC entries by start_page to ensure correct page ranges
    # (TOC text may list lessons out of page order, e.g. grouped by chapter)
    toc = sorted(toc, key=lambda e: e.start_page)

    # Build page ranges for each lesson
    # lesson_ranges: [(lesson_num, title, start_page, end_page)]
    lesson_ranges: List[Tuple[int, str, int, int]] = []
    for i, entry in enumerate(toc):
        start = entry.start_page + offset
        if i + 1 < len(toc):
            end = toc[i + 1].start_page + offset - 1
        else:
            end = total_pages
        lesson_ranges.append((entry.lesson_num, entry.title, start, end))

    # Collect content for each lesson
    result: Dict[int, Tuple[str, str]] = {}
    for lesson_num, title, start, end in lesson_ranges:
        content_parts: List[str] = []
        for page_num in range(start, end + 1):
            if page_num in pages:
                page_text = pages[page_num].strip()
                if page_text:
                    content_parts.append(page_text)

        content = "\n\n".join(content_parts)
        if content.strip():
            result[lesson_num] = (title, content)

    return result


def split_pdf_to_lessons(
    pdf_path: Union[str, Path],
    toc_text: str,
    output_dir: Union[str, Path],
    *,
    offset: int = 0,
    verbose: bool = True,
    use_olmocr: bool = False,
    olmocr_max_workers: int = 5,
    pipeline_logger=None,
) -> Dict[int, Path]:
    """
    Split PDF into per-lesson .txt files using TOC page boundaries.

    When use_olmocr=True, sends per-lesson page ranges to the olmOCR server
    for high-quality Vietnamese OCR extraction (for PDFs with garbled fonts).

    Args:
        olmocr_max_workers: Number of parallel olmOCR requests (default 4).
        pipeline_logger: Optional PipelineLogger instance for structured logging.

    Returns: {lesson_num: output_path}
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if use_olmocr:
        return _split_pdf_to_lessons_olmocr(pdf_path, toc_text, output_dir,
                                            offset=offset, verbose=verbose,
                                            max_workers=olmocr_max_workers,
                                            pipeline_logger=pipeline_logger)

    # Normal path: pypdfium2 extraction
    lessons = split_by_toc_pages(pdf_path, toc_text, offset=offset)

    output_paths: Dict[int, Path] = {}
    for lesson_num, (title, content) in sorted(lessons.items()):
        # Clean layout artifacts before formatting output
        content = clean_lesson_text(content, title, lesson_num=lesson_num)
        # Format: CMS-compatible with ##Title header
        out_text = f"##Title: Bài {lesson_num}. {title}\n\n{content}\n"
        out_path = output_dir / f"lesson{lesson_num}.txt"
        # Write with CRLF line endings (Windows/CMS standard)
        out_path.write_bytes(out_text.replace("\n", "\r\n").encode("utf-8"))
        output_paths[lesson_num] = out_path

        if verbose:
            _safe_print(f"  lesson{lesson_num}.txt: '{title}' ({len(content)} chars)")
        if pipeline_logger:
            pipeline_logger.lesson_ok(pdf_path.name, lesson_num, title)

    if verbose:
        _safe_print(f"\n  Total: {len(output_paths)} lessons written to {output_dir}")

    return output_paths


def _split_pdf_to_lessons_olmocr(
    pdf_path: Path,
    toc_text: str,
    output_dir: Path,
    *,
    offset: int = 0,
    verbose: bool = True,
    max_workers: int = 5,
    pipeline_logger=None,
) -> Dict[int, Path]:
    """
    Split PDF into per-lesson .txt files using olmOCR for text extraction.
    Sends each lesson's page range to the olmOCR server in PARALLEL
    using ThreadPoolExecutor (I/O-bound → threads are ideal).

    Args:
        max_workers: Number of concurrent olmOCR requests (default 5).
                     Increase if server can handle more; decrease if rate-limited.
        pipeline_logger: Optional PipelineLogger for structured logging.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.olmocr_extract import extract_pages_via_olmocr

    _safe_print(f"[olmOCR] Using olmOCR server for {pdf_path.name} (parallel={max_workers})...")
    if pipeline_logger:
        pipeline_logger.info(f"[olmOCR] {pdf_path.name}: parallel={max_workers}")

    toc = parse_toc_from_text(toc_text)
    if not toc:
        _safe_print("[olmOCR] No TOC entries found, cannot split.")
        if pipeline_logger:
            pipeline_logger.warning(f"[olmOCR] {pdf_path.name}: No TOC entries found")
        return {}

    toc = sorted(toc, key=lambda e: e.start_page)

    pdf = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(pdf)
    pdf.close()

    # Build list of (lesson_num, title, start_page_0idx, end_page_0idx)
    tasks: List[Tuple[int, str, int, int]] = []
    for i, entry in enumerate(toc):
        lesson_num = entry.lesson_num
        title = entry.title
        start = entry.start_page + offset - 1  # 0-indexed

        if i + 1 < len(toc):
            end = toc[i + 1].start_page + offset - 2
        else:
            end = total_pages - 1

        if start < 0 or start >= total_pages:
            continue
        end = min(end, total_pages - 1)
        tasks.append((lesson_num, title, start, end))

    if verbose:
        _safe_print(f"  {len(tasks)} lessons to OCR, dispatching {max_workers} parallel requests...")
    if pipeline_logger:
        pipeline_logger.info(f"  {pdf_path.name}: {len(tasks)} lessons to OCR")

    output_paths: Dict[int, Path] = {}
    failed_lessons: List[Tuple[int, str]] = []

    def _ocr_one_lesson(lesson_num: int, title: str, start: int, end: int):
        """Worker: OCR one lesson's page range."""
        if verbose:
            _safe_print(f"  [olmOCR] Lesson {lesson_num}: '{title}' (pages {start+1}-{end+1})...")
        markdown, err = extract_pages_via_olmocr(pdf_path, start, end, return_error=True)
        return lesson_num, title, start, end, markdown, err

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one_lesson, ln, t, s, e): (ln, t)
            for ln, t, s, e in tasks
        }

        for future in as_completed(futures):
            ln_key, title_key = futures[future]
            try:
                lesson_num, title, start, end, markdown, err = future.result()
            except Exception as exc:
                _safe_print(f"  ❌ Lesson {ln_key} exception: {exc}")
                failed_lessons.append((ln_key, title_key))
                if pipeline_logger:
                    pipeline_logger.lesson_failed(
                        pdf_path.name, ln_key, str(exc), title=title_key
                    )
                continue

            if not markdown:
                error_detail = err or "olmOCR returned empty response"
                _safe_print(f"  ❌ Lesson {lesson_num} failed: {error_detail}")
                failed_lessons.append((lesson_num, title))
                if pipeline_logger:
                    pipeline_logger.lesson_failed(
                        pdf_path.name, lesson_num,
                        f"pages {start+1}-{end+1}: {error_detail}",
                        title=title,
                    )
                continue

            # Convert markdown to plain text for CMS compatibility
            content = _markdown_to_plain_text(markdown)

            # Format output
            out_text = f"##Title: Bài {lesson_num}. {title}\n\n{content}\n"
            out_path = output_dir / f"lesson{lesson_num}.txt"
            out_path.write_bytes(out_text.replace("\n", "\r\n").encode("utf-8"))
            output_paths[lesson_num] = out_path

            if verbose:
                _safe_print(f"  ✅ lesson{lesson_num}.txt ({len(content)} chars)")
            if pipeline_logger:
                pipeline_logger.lesson_ok(pdf_path.name, lesson_num, title)

    if verbose:
        _safe_print(f"\n  Total: {len(output_paths)} lessons OK, {len(failed_lessons)} failed")
        if failed_lessons:
            _safe_print(f"  Failed lessons: {sorted([ln for ln, _ in failed_lessons])}")
    if pipeline_logger:
        pipeline_logger.info(
            f"  {pdf_path.name}: {len(output_paths)} OK, {len(failed_lessons)} failed"
        )

    return output_paths


def _markdown_to_plain_text(md_text: str) -> str:
    """
    Convert olmOCR markdown output to plain text suitable for CMS.
    Keeps text content, converts tables to pipe format, removes images.
    """
    import re

    lines = md_text.split('\n')
    result = []

    for line in lines:
        # Remove image references
        if line.strip().startswith('!['):
            continue
        # Remove markdown heading markers but keep text
        if line.startswith('#'):
            line = re.sub(r'^#+\s*', '', line)
        # Keep LaTeX formulas as-is (they'll be in \(...\) or \[...\] format)
        # Remove HTML table tags but this is complex; keep as-is for now
        result.append(line)

    text = '\n'.join(result)

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


if __name__ == "__main__":
    # Quick test
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else r"input\toan\Toan_3_Tap_1-6.3.25.pdf"
    toc_source = sys.argv[2] if len(sys.argv) > 2 else r"outputs\toan\_work_tmp\toan\Toan_3_Tap_1-6.3.25\raw_text.txt"

    toc_text = Path(toc_source).read_text(encoding="utf-8")
    split_pdf_to_lessons(pdf, toc_text, r"outputs\_test_page_split")
