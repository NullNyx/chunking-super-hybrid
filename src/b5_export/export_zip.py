"""
B5 - Export ZIP / Export JSON chunks thành ZIP cho CMS import

Input:
- JSON chunks từ B4

Output:
- ZIP file với cấu trúc:
    subjectFolder/Lop{gradeNum}/general/lesson{lessonNum}.txt
    subjectFolder/Lop{gradeNum}/LT/lesson{lessonNum}.txt
    subjectFolder/Lop{gradeNum}/lesson{lessonNum}.txt

Usage:
    uv run chunk-export
    python -m src.b5_export.export_zip
"""
from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# === HELPER FUNCTIONS ===

def _build_lesson_map(json_root: Path) -> Dict[Tuple[str, int, str, int], List[dict]]:
    """Scan all .json files and group chunks by (subject, grade, types, lesson).

    Args:
        json_root: Root directory containing .json files.

    Returns:
        Dict mapping (subject, grade, types, lesson) -> sorted list of chunks.
    """
    lesson_map: Dict[Tuple[str, int, str, int], List[dict]] = defaultdict(list)

    json_files = [
        p for p in json_root.rglob("*.json")
        if p.is_file() and not p.name.startswith("_")
    ]

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        for item in data:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata", {})
            content = item.get("page_content", "")
            if not content.strip():
                continue

            subject = meta.get("subject", "unknown")
            kb_id = meta.get("kb_id")  # grade number
            types = meta.get("types", "general")
            lesson = meta.get("lesson")

            if kb_id is None or lesson is None:
                continue

            try:
                kb_id = int(kb_id)
                lesson = int(lesson)
            except (ValueError, TypeError):
                continue

            key = (subject, kb_id, types, lesson)
            lesson_map[key].append(item)

    return lesson_map


def _sort_chunks(chunks: List[dict]) -> List[dict]:
    """Sort chunks by chunk_order, subchunk_index, global_order.

    Args:
        chunks: List of chunk dictionaries.

    Returns:
        Sorted list of chunks.
    """
    def _sort_key(item: dict) -> Tuple[int, int, int]:
        meta = item.get("metadata", {})
        return (
            meta.get("chunk_order", 0),
            meta.get("subchunk_index", 0),
            meta.get("global_order", 0),
        )
    return sorted(chunks, key=_sort_key)


def _chunks_to_text(chunks: List[dict]) -> str:
    """Concatenate page_content of sorted chunks into single lesson text.

    Args:
        chunks: List of chunk dictionaries.

    Returns:
        Combined text with ## Heading: markers.
    """
    sorted_chunks = _sort_chunks(chunks)
    parts: List[str] = []

    for item in sorted_chunks:
        meta = item.get("metadata", {})
        heading = meta.get("heading", "")
        content = item.get("page_content", "").strip()

        if heading and heading != "UNKNOWN":
            parts.append(f"## Heading: {heading}")
        if content:
            parts.append(content)
        parts.append("")  # blank line separator

    return "\n".join(parts).strip() + "\n"


def _build_zip_path(subject: str, grade: int, types: str, lesson: int) -> str:
    """Build internal path for ZIP file.

    Args:
        subject: Subject name (e.g., 'toan', 'htlt').
        grade: Grade number (1-12).
        types: Content type ('general', 'LT', 'TH').
        lesson: Lesson number.

    Returns:
        Relative path inside ZIP (e.g., 'toan/Lop3/LT/lesson1.txt').
    """
    types_lower = types.strip().lower()

    # Include types subfolder for known types
    if types_lower in ("general", "lt", "th"):
        return f"{subject}/Lop{grade}/{types}/lesson{lesson}.txt"
    else:
        # Fallback: put in root of Lop folder
        return f"{subject}/Lop{grade}/lesson{lesson}.txt"


# === MAIN EXPORT ===

def export_to_zip(
    source_root: str,
    output_zip: str,
    *,
    verbose: bool = True,
) -> Dict[str, int]:
    """Create ZIP from JSON files, one file per lesson.

    Args:
        source_root: Folder containing .json files (from B3/B4).
        output_zip: Path to output .zip file.

    Returns:
        Stats dict with lesson and chunk counts.

    Raises:
        FileNotFoundError: If source_root does not exist.
    """
    source_root_p = Path(source_root).resolve()
    output_zip_p = Path(output_zip).resolve()
    output_zip_p.parent.mkdir(parents=True, exist_ok=True)

    if not source_root_p.exists():
        raise FileNotFoundError(f"Source root not found: {source_root_p}")

    lesson_map = _build_lesson_map(source_root_p)

    if not lesson_map:
        print(f"[WARN] No lessons found in: {source_root_p}")
        return {"lessons": 0, "chunks": 0}

    stats = {"lessons": 0, "chunks": 0}

    with zipfile.ZipFile(output_zip_p, "w", zipfile.ZIP_DEFLATED) as zf:
        for (subject, grade, types, lesson), chunks in sorted(lesson_map.items()):
            zip_path = _build_zip_path(subject, grade, types, lesson)
            text = _chunks_to_text(chunks)

            zf.writestr(zip_path, text.encode("utf-8"))
            stats["lessons"] += 1
            stats["chunks"] += len(chunks)

            if verbose:
                print(f"  {zip_path} ({len(chunks)} chunks, {len(text)} chars)")

    if verbose:
        print(f"\nExported {stats['lessons']} lessons ({stats['chunks']} chunks) -> {output_zip_p}")
        size_mb = output_zip_p.stat().st_size / (1024 * 1024)
        print(f"ZIP size: {size_mb:.2f} MB", end="")
        if size_mb > 2.0:
            print(f" [WARN] Exceeds 2MB limit! Consider splitting by subject.")
        else:
            print(f" [OK] Within 2MB limit.")

    return stats


def export_to_folder(
    json_root: str,
    output_folder: str,
    *,
    verbose: bool = True,
) -> Dict[str, int]:
    """Export JSON to plain .txt files in a folder (for inspection).

    Args:
        json_root: Root directory containing .json files.
        output_folder: Root directory for output .txt files.

    Returns:
        Stats dict with lesson and chunk counts.
    """
    json_root_p = Path(json_root).resolve()
    output_folder_p = Path(output_folder).resolve()
    output_folder_p.mkdir(parents=True, exist_ok=True)

    lesson_map = _build_lesson_map(json_root_p)

    if not lesson_map:
        print(f"[WARN] No lessons found in: {json_root_p}")
        return {"lessons": 0, "chunks": 0}

    stats = {"lessons": 0, "chunks": 0}

    for (subject, grade, types, lesson), chunks in sorted(lesson_map.items()):
        rel_path = _build_zip_path(subject, grade, types, lesson)
        out_path = output_folder_p / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        text = _chunks_to_text(chunks)
        out_path.write_text(text, encoding="utf-8")

        stats["lessons"] += 1
        stats["chunks"] += len(chunks)

        if verbose:
            print(f"  {rel_path} ({len(chunks)} chunks)")

    if verbose:
        print(f"\nExported {stats['lessons']} lessons -> {output_folder_p}")

    return stats


def main() -> None:
    """Console entry point for `uv run chunk-export`."""
    import sys

    # Default paths
    default_json_root = r".\outputs\ttnt_new\03_chunked_raw"
    default_zip = r".\outputs\export\toan.zip"
    default_folder = r".\outputs\export\toan_txt"

    json_root = sys.argv[1] if len(sys.argv) > 1 else default_json_root

    print(f"Source: {json_root}")
    print("=" * 60)

    # Export to folder (for inspection)
    print("\n[1/2] Exporting to folder...")
    export_to_folder(json_root, default_folder)

    # Export to ZIP
    print("\n[2/2] Exporting to ZIP...")
    export_to_zip(json_root, default_zip)


if __name__ == "__main__":
    main()