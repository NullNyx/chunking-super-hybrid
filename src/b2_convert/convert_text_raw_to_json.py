"""
B2 - Convert to JSON / Chuyển đổi text có heading thành JSON chunks

Input:
- Text file với heading markers (## Heading:) từ B1

Output:
- JSON chunks với metadata (subject, grade, lesson, chunk_id)

Workflow:
1. Split text bằng ## Heading: markers
2. Generate chunk IDs (SHA1)
3. Add metadata từ folder structure
4. Output: mirrored .json files

Input structure:
    <root>/<subject>/<kb_folder>/<types>/<file>.txt
Example:
    outputs/01_extract_txt_raw/htlt/Lop1/general/lesson4.txt
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# === REGEX PATTERNS ===

# Match ## Heading: ... markers injected by B1
HEADING_RE = re.compile(r"^\s*##\s*Heading:\s*(.+?)\s*$", re.IGNORECASE)

# Normalize whitespace (preserve line breaks)
WHITESPACE_RE = re.compile(r"\s+")

# Count word-like tokens (fallback when tiktoken unavailable)
WORD_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Match lesson number in heading (e.g., "Bài 5. Bảng nhân 3")
_LESSON_IN_HEADING_RE = re.compile(r"\bBài\s+(\d+)\b", re.IGNORECASE)


# === HELPER FUNCTIONS ===

def safe_token_count(text: str) -> int:
    """Count tokens in text.

    Uses tiktoken (cl100k_base) for accurate LLM token estimate.
    Falls back to word counting if tiktoken unavailable.

    Args:
        text: Input text to count tokens for.

    Returns:
        Approximate token count.
    """
    text = text.strip()
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(WORD_TOKEN_RE.findall(text))


def normalize_text(text: str) -> str:
    """Normalize text while preserving line breaks.

    - Strips leading/trailing whitespace from each line
    - Removes empty lines at start/end
    - Collapses multiple spaces within lines to single space

    Args:
        text: Input text.

    Returns:
        Normalized text.
    """
    lines = [WHITESPACE_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def compute_chunk_id(
    subject: str,
    kb_folder: str,
    types: str,
    rel_file: str,
    heading: str,
    content: str,
) -> str:
    """Generate deterministic chunk ID using SHA1 hash.

    Args:
        subject: Subject name (e.g., 'htlt').
        kb_folder: Grade folder (e.g., 'Lop1').
        types: Content type (e.g., 'general', 'LT').
        rel_file: Relative file path.
        heading: Section heading.
        content: Section content.

    Returns:
        40-character hex string (SHA1 hash).
    """
    raw = f"{subject}|{kb_folder}|{types}|{rel_file}|{heading}|{content}".encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha1(raw).hexdigest()


def parse_kb_id(kb_folder: str) -> Optional[int]:
    """Extract grade number from folder name.

    Args:
        kb_folder: Folder name like 'Lop6' or 'Lop12'.

    Returns:
        Grade number (6, 12, etc.) or None if not found.
    """
    m = re.search(r"(\d+)", kb_folder)
    return int(m.group(1)) if m else None


def parse_lesson(filename_stem: str) -> Optional[int]:
    """Extract lesson number from filename.

    Args:
        filename_stem: Filename without extension (e.g., 'lesson1').

    Returns:
        Lesson number or None if not found.
    """
    m = re.search(r"lesson\s*(\d+)", filename_stem, re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_lesson_from_content(raw: str) -> Optional[int]:
    """Parse lesson number from text content.

    Prefers heading-style "Bài X." at start of line.
    Falls back to any "BÀI X" occurrence in text.

    Args:
        raw: Raw text content.

    Returns:
        Lesson number or None if not found.
    """
    # Prefer heading-style "Bài X." at start of line
    m = re.search(r"^\s*Bài\s+(\d+)\b", raw, re.IGNORECASE | re.MULTILINE)
    if m:
        return int(m.group(1))
    # Fallback: any "BÀI X" in text
    m = re.search(r"\bBÀI\s*(\d+)\b", raw, re.IGNORECASE)
    return int(m.group(1)) if m else None


def split_by_heading(raw: str) -> List[Tuple[str, str]]:
    """Split text by ## Heading: markers into sections.

    Rules:
    - Text before first heading: attach to first heading (nearest).
    - Subheadings (Câu lệnh): merge into previous heading (no new item).
    - "Câu hỏi" kept as normal heading (may be only CLIP-detected heading).
    - Text outside headings: attach to nearest previous (effective) heading.
    - If no heading exists: one chunk with heading "UNKNOWN".

    Args:
        raw: Raw text with ## Heading: markers.

    Returns:
        List of (heading, content) tuples.
    """
    # Only "câu lệnh" is a true subheading (merged into previous heading)
    # "Câu hỏi" kept because it may be the only CLIP-detected heading
    SUBHEADINGS = {"câu lệnh"}

    def _norm_heading(h: str) -> str:
        return re.sub(r"\s+", " ", h.strip().lower())

    lines = raw.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    preface: List[str] = []

    current_heading: Optional[str] = None
    current_buf: List[str] = []

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            new_heading = m.group(1).strip()
            new_heading_norm = _norm_heading(new_heading)

            # If subheading: don't finalize, insert marker and continue
            if new_heading_norm in SUBHEADINGS:
                if current_heading is None:
                    # If file starts with subheading, create UNKNOWN to hold it
                    current_heading = "UNKNOWN"
                    current_buf = []
                current_buf.append(f"## {new_heading}:")
                continue

            # Main heading: finalize previous section
            if current_heading is not None:
                sections.append((current_heading, current_buf))
            else:
                preface.extend(current_buf)

            current_heading = new_heading
            current_buf = []
        else:
            current_buf.append(line)

    # Finalize last section
    if current_heading is not None:
        sections.append((current_heading, current_buf))
    else:
        full = normalize_text(raw)
        return [("UNKNOWN", full)] if full else []

    # Attach preface to first heading
    if preface and sections:
        first_heading, first_buf = sections[0]
        sections[0] = (first_heading, preface + [""] + first_buf)

    out: List[Tuple[str, str]] = []
    for h, buf in sections:
        content = normalize_text("\n".join(buf))
        # Keep sections even if content is empty (serve as lesson boundaries)
        out.append((h, content if content else h))

    return out


# === MAIN CONVERSION ===

def build_chunks_for_file(
    txt_path: Path,
    input_root: Path,
    chunk_version: str = "v1",
    default_types: str = "LT",
) -> List[Dict]:
    """Build JSON chunks from a text file.

    Expects path structure:
        <root>/<subject>/<kb_folder>/<types>/<file>.txt
        Example: results_v1/htlt/Lop1/general/lesson4.txt

    If path has fewer levels, infers missing metadata:
        - 2 parts: subject/file.txt → infer grade from filename pattern

    Args:
        txt_path: Path to input .txt file.
        input_root: Root directory for computing relative paths.
        chunk_version: Version string for metadata.
        default_types: Default content type if not in path.

    Returns:
        List of chunk dictionaries, each with 'metadata' and 'page_content'.
    """
    rel = txt_path.relative_to(input_root)
    parts = rel.parts

    # Parse path components
    if len(parts) >= 4:
        # Full structure: subject/kb_folder/types/file.txt
        subject = parts[0]
        kb_folder = parts[1]
        types = parts[2]
    elif len(parts) == 3:
        # subject/kb_folder/file.txt — no types subfolder
        subject = parts[0]
        kb_folder = parts[1]
        types = default_types
    elif len(parts) == 2:
        # subject/file.txt — infer grade from filename
        subject = parts[0]
        grade_match = re.search(r"[_\s](\d{1,2})[_\s]", parts[1])
        if grade_match:
            kb_folder = f"Lop{grade_match.group(1)}"
        else:
            kb_folder = "unknown"
        types = default_types
    else:
        subject = "unknown"
        kb_folder = "unknown"
        types = default_types

    rel_file = str(rel)
    kb_id = parse_kb_id(kb_folder)
    raw = txt_path.read_text(encoding="utf-8", errors="ignore")
    file_lesson = parse_lesson_from_content(raw) or parse_lesson(txt_path.stem)
    sections = split_by_heading(raw)

    # Track heading counters for ordering (if same heading appears multiple times)
    heading_counters: Dict[str, int] = {}

    # Track current lesson: update when heading contains "Bài X"
    current_lesson = file_lesson

    chunks: List[Dict] = []
    for heading, content in sections:
        # Extract lesson number from heading (e.g., "Bài 5. Bảng nhân 3")
        lm = _LESSON_IN_HEADING_RE.search(heading)
        if lm:
            current_lesson = int(lm.group(1))

        heading_counters[heading] = heading_counters.get(heading, 0) + 1
        chunk_order = heading_counters[heading]

        chunk_id = compute_chunk_id(subject, kb_folder, types, rel_file, heading, content)

        meta = {
            "kb_id": kb_id,
            "subject": subject,
            "types": types,
            "lesson": current_lesson,
            "chunk_version": chunk_version,
            "chunk_order": chunk_order,
            "chunk_id": chunk_id,
            "heading": heading,
            "length": len(content),
            "length_token": safe_token_count(content),
        }

        chunks.append({"metadata": meta, "page_content": content})

    return chunks


def convert_folder(input_root: str, output_root: str, chunk_version: str = "v1") -> None:
    """Convert all .txt files under input_root to .json files under output_root.

    Mirrors the directory structure from input to output, changing only
    the file extension from .txt to .json.

    Args:
        input_root: Root directory containing .txt files.
        output_root: Root directory for output .json files.
        chunk_version: Version string to include in metadata.

    Raises:
        FileNotFoundError: If input_root does not exist.
    """
    input_root_p = Path(input_root).resolve()
    output_root_p = Path(output_root).resolve()

    if not input_root_p.exists():
        raise FileNotFoundError(f"Input folder not found: {input_root_p}")

    txt_files = list(input_root_p.rglob("*.txt"))
    for txt_path in txt_files:
        chunks = build_chunks_for_file(txt_path, input_root_p, chunk_version=chunk_version)

        rel = txt_path.relative_to(input_root_p)
        out_path = (output_root_p / rel).with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        out_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Done. Converted {len(txt_files)} files to: {output_root_p}")