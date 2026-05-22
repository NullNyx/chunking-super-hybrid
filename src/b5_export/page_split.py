"""
B5 - Page Split / Tách lesson theo trang PDF

Input:
- PDF file + JSON chunks từ B4

Output:
- Text per lesson, dựa trên page boundaries từ TOC

Workflow:
1. Parse TOC từ Docling text → {lesson_num: (title, start_page)}
2. Extract text per page using pypdfium2
3. Group pages by lesson range
4. Clean layout artifacts (page numbers, headers)
5. Output: dict mapping lesson_num → (title, content)

Thay thế fuzzy title-matching bằng precise page boundaries.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pypdfium2 as pdfium


# === CONSTANTS ===

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

# Pattern for standalone "Số" lines (e.g., "Số", "Số 5", "Số12")
_SO_PATTERN = re.compile(r"^Số\s?\d*$")


# === HELPER FUNCTIONS ===

def _safe_print(s: str) -> None:
    """Print with fallback for Windows console encoding issues.

    Args:
        s: String to print.
    """
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass


# === TEXT CLEANING ===

def clean_lesson_text(content: str, title: str, lesson_num: int = 0) -> str:
    """Clean layout artifacts from extracted PDF page text.

    Removes:
    - Standalone page numbers (lines matching ^\\d+$)
    - Known section headers/footers (case-insensitive exact match)
    - "Số" pattern lines (matching ^Số\\s?\\d*$)
    - Duplicate lesson title in body (exact "Bài {N}" and title variants)
    - Chapter headers (all-uppercase lines in first 10 non-empty lines)
    - Sidebar labels (e.g. "1 ôn tập và bổ sung Chủ đề")
    - Excessive blank lines (3+ consecutive newlines collapsed to 2)

    Preserves all other content unchanged.

    Args:
        content: Raw text extracted from PDF pages.
        title: Lesson title for duplicate detection.
        lesson_num: Lesson number for "Bài N" duplicate detection.

    Returns:
        Cleaned text with artifacts removed.
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


# === TOC PARSING ===

@dataclass
class TocEntry:
    """Table of contents entry."""
    lesson_num: int
    title: str
    start_page: int  # 1-indexed (as printed in book)


def parse_toc_from_text(text: str) -> List[TocEntry]:
    """Parse table of contents from Docling-extracted text.

    Supports multiple formats:
    1. Table format (lớp 3-5): | BÀI 1 | Content | 14 |
    2. Table with empty first col (lớp 1): | | BÀI 1 | A a | 14 |
    3. Plain text format (lớp 6+): "Bài 1. Title" + page on next line
    4. Multi-line format (lớp 2+): Bài X followed by multi-line content

    Args:
        text: Raw text containing TOC.

    Returns:
        List of TocEntry objects sorted by lesson number.
    """
    entries: List[TocEntry] = []

    # Format 1 & 2: Table format with pipes
    TOC_TABLE_RE = re.compile(
        r"(?i)\|\s*(?:\|?)\s*Bài\s+(\d+)\.?\s*\|(.+?)\|\s*(\d+)\s*\|"
    )
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

    # Format 3 & 4: Plain text "Bài X" pattern with page numbers
    lines = text.splitlines()
    BAI_LINE_RE = re.compile(r"(?i)^\s*Bài\s+(\d+)\.?\s*(.*)$")
    PAGE_NUM_RE = re.compile(r"^\s*(\d+)\s*$")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = BAI_LINE_RE.match(line)

        if m:
            lesson_num = int(m.group(1))
            title_or_content = m.group(2).strip()

            # Look for page number: inline or on subsequent lines
            page_num = 0
            title = title_or_content

            # Check if page number is inline (e.g., "Bài 1 Title 10")
            inline_match = re.match(r"(.+?)\s+(\d+)\s*$", title_or_content)
            if inline_match and len(inline_match.group(2)) <= 3:
                potential_page = int(inline_match.group(2))
                if potential_page < 500:  # Page numbers typically < 500
                    page_num = potential_page
                    title = inline_match.group(1).strip()

            # If no inline page, look on subsequent lines
            if page_num == 0:
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j].strip()
                    pm = PAGE_NUM_RE.match(next_line)
                    if pm:
                        potential_page = int(pm.group(1))
                        if potential_page < 500:
                            page_num = potential_page
                            break

            if page_num > 0:
                entries.append(TocEntry(
                    lesson_num=lesson_num,
                    title=title,
                    start_page=page_num,
                ))

        i += 1

    return entries


# === PDF EXTRACTION ===

def _extract_page_text(pdf_doc, page_idx: int) -> str:
    """Extract text from a single PDF page.

    Args:
        pdf_doc: pypdfium2 document object.
        page_idx: Zero-based page index.

    Returns:
        Extracted text content.
    """
    page = pdf_doc[page_idx]
    text_page = page.get_textpage()
    text = text_page.get_text_bounded()
    return text


def _get_page_range_for_lesson(
    entries: List[TocEntry],
    lesson_num: int,
) -> Tuple[int, int]:
    """Get page range (start, end) for a specific lesson.

    Args:
        entries: TOC entries sorted by start_page.
        lesson_num: Target lesson number.

    Returns:
        Tuple of (start_page, end_page), both 1-indexed.
    """
    entries_by_num = {e.lesson_num: e for e in entries}
    if lesson_num not in entries_by_num:
        return (0, 0)

    entry = entries_by_num[lesson_num]
    start = entry.start_page

    # Find end page: next lesson's start - 1
    end = start
    for e in entries:
        if e.start_page > start:
            end = e.start_page - 1
            break
    else:
        # Last lesson: use a large number as placeholder
        end = start + 50  # will be truncated by actual page count

    return (start, end)


# === MAIN SPLITTING ===

def split_pdf_to_lessons(
    pdf_path: Union[str, Path],
    toc_text: str,
    output_dir: Union[str, Path],
    *,
    verbose: bool = True,
    pipeline_logger=None,
) -> Dict[int, Path]:
    """Split PDF into individual lesson .txt files using TOC.

    Args:
        pdf_path: Path to input PDF file.
        toc_text: Text containing TOC (from Docling extraction).
        output_dir: Directory for output lesson .txt files.
        verbose: If True, print progress.
        pipeline_logger: Optional PipelineLogger instance for logging.

    Returns:
        Dict mapping lesson_num → output file path.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse TOC
    entries = parse_toc_from_text(toc_text)
    if not entries:
        _safe_print(f"[WARN] No TOC entries found in: {pdf_path.name}")
        return {}

    # Sort by start page
    entries = sorted(entries, key=lambda e: e.start_page)

    if verbose:
        _safe_print(f"  Found {len(entries)} lessons in TOC")

    # Open PDF
    pdf_doc = pdfium.PdfDocument(pdf_path)
    n_pages = len(pdf_doc)

    if verbose:
        _safe_print(f"  PDF has {n_pages} pages")

    output_paths: Dict[int, Path] = {}

    for entry in entries:
        lesson_num = entry.lesson_num
        title = entry.title

        start, end = _get_page_range_for_lesson(entries, lesson_num)

        # Adjust to 0-based indices
        start_idx = max(0, start - 1)
        end_idx = min(n_pages, end)

        if start_idx >= n_pages or end_idx <= start_idx:
            _safe_print(f"  [SKIP] lesson{lesson_num}: invalid page range {start}-{end}")
            continue

        # Extract and concatenate pages
        parts: List[str] = []
        for pi in range(start_idx, end_idx):
            page_text = _extract_page_text(pdf_doc, pi)
            if page_text:
                parts.append(page_text)

        content = "\n".join(parts)

        # Clean artifacts
        content = clean_lesson_text(content, title, lesson_num)

        # Format output
        out_text = f"##Title: Bài {lesson_num}. {title}\n\n{content}\n"
        out_path = output_dir / f"lesson{lesson_num}.txt"
        out_path.write_bytes(out_text.replace("\n", "\r\n").encode("utf-8"))
        output_paths[lesson_num] = out_path

        if verbose:
            _safe_print(f"  ✅ lesson{lesson_num}.txt ({len(content)} chars)")

    if verbose:
        _safe_print(f"\n  Total: {len(output_paths)} lessons written")

    return output_paths


def _split_pdf_to_lessons_olmocr(
    pdf_path: Union[str, Path],
    toc_text: str,
    output_dir: Union[str, Path],
    *,
    offset: int = 0,
    verbose: bool = True,
) -> Dict[int, Path]:
    """Split PDF using olmOCR for PDFs with garbled fonts.

    Uses olmOCR server to extract text when standard pypdfium2 fails.
    Requires olmOCR server running.

    Args:
        pdf_path: Path to input PDF file.
        toc_text: Text containing TOC.
        output_dir: Directory for output lesson .txt files.
        offset: Page offset to add to TOC pages.
        verbose: If True, print progress.

    Returns:
        Dict mapping lesson_num → output file path.
    """
    from src.b1_extract.olmocr_extract import extract_pages_via_olmocr

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _safe_print(f"[olmOCR] Using olmOCR server for {pdf_path.name}...")

    toc = parse_toc_from_text(toc_text)
    if not toc:
        _safe_print("[olmOCR] No TOC entries found, cannot split.")
        return {}

    toc = sorted(toc, key=lambda e: e.start_page)

    pdf = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(pdf)
    pdf.close()

    output_paths: Dict[int, Path] = {}

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

        if verbose:
            _safe_print(f"  [olmOCR] Lesson {lesson_num}: '{title}' (pages {start+1}-{end+1})...")

        markdown = extract_pages_via_olmocr(pdf_path, start, end)

        if not markdown:
            _safe_print(f"  ❌ Lesson {lesson_num} failed, skipping")
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

    if verbose:
        _safe_print(f"\n  Total: {len(output_paths)} lessons written to {output_dir}")

    return output_paths


def _markdown_to_plain_text(md_text: str) -> str:
    """Convert olmOCR markdown output to plain text for CMS.

    Keeps text content, removes images, converts markdown headings to plain text.

    Args:
        md_text: Markdown text from olmOCR.

    Returns:
        Plain text suitable for CMS.
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