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
    Expects lines like: |  | Bài 1. Ôn tập các số đến 1 000  |  6 |
    """
    TOC_RE = re.compile(
        r"\|\s*\|\s*Bài\s+(\d+)\.\s*(.+?)\s*\|\s*(\d+)\s*\|"
    )
    entries: List[TocEntry] = []
    for line in text.splitlines():
        m = TOC_RE.search(line)
        if m:
            entries.append(TocEntry(
                lesson_num=int(m.group(1)),
                title=m.group(2).strip(),
                start_page=int(m.group(3)),
            ))
    return entries


def extract_pages_text(pdf_path: Union[str, Path]) -> Dict[int, str]:
    """
    Extract text from each page using pypdfium2.
    Returns: {page_num (1-indexed): text}
    """
    pdf_path = Path(pdf_path)
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
) -> Dict[int, Path]:
    """
    Split PDF into per-lesson .txt files using TOC page boundaries.

    Returns: {lesson_num: output_path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lessons = split_by_toc_pages(pdf_path, toc_text, offset=offset)

    output_paths: Dict[int, Path] = {}
    for lesson_num, (title, content) in sorted(lessons.items()):
        # Clean layout artifacts before formatting output
        content = clean_lesson_text(content, title, lesson_num=lesson_num)
        # Format: plain text, no markdown markers
        # Start with "Bài X\nTITLE\n\n" then content
        out_text = f"Bài {lesson_num}\n{title.upper()}\n\n{content}\n"
        out_path = output_dir / f"lesson{lesson_num}.txt"
        # Write with CRLF line endings (Windows/CMS standard)
        out_path.write_bytes(out_text.replace("\n", "\r\n").encode("utf-8"))
        output_paths[lesson_num] = out_path

        if verbose:
            _safe_print(f"  lesson{lesson_num}.txt: '{title}' ({len(content)} chars)")

    if verbose:
        _safe_print(f"\n  Total: {len(output_paths)} lessons written to {output_dir}")

    return output_paths


if __name__ == "__main__":
    # Quick test
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else r"input\toan\Toan_3_Tap_1-6.3.25.pdf"
    toc_source = sys.argv[2] if len(sys.argv) > 2 else r"outputs\toan\_work_tmp\toan\Toan_3_Tap_1-6.3.25\raw_text.txt"

    toc_text = Path(toc_source).read_text(encoding="utf-8")
    split_pdf_to_lessons(pdf, toc_text, r"outputs\_test_page_split")
