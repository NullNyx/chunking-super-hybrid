"""
B5: Export chunked JSON → ZIP ready for "Import Lessons từ ZIP".

Expected ZIP structure:
    subjectFolder/Lop{gradeNum}/general/lesson{lessonNum}.txt
    subjectFolder/Lop{gradeNum}/LT/lesson{lessonNum}.txt
    subjectFolder/Lop{gradeNum}/lesson{lessonNum}.txt

Usage:
    uv run chunk-export
    python -m src.export_zip
"""
from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _build_lesson_map(json_root: Path) -> Dict[Tuple[str, int, str, int], List[dict]]:
    """
    Scan all .json files under json_root.
    Group chunks by (subject, kb_id/grade, types, lesson).
    Returns dict mapping (subject, grade, types, lesson) -> sorted list of chunks.
    """
    lesson_map: Dict[Tuple[str, int, str, int], List[dict]] = defaultdict(list)

    json_files = [p for p in json_root.rglob("*.json") if p.is_file() and not p.name.startswith("_")]

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
    """Sort chunks by chunk_order, subchunk_index, global_order."""
    def _sort_key(item: dict):
        meta = item.get("metadata", {})
        return (
            meta.get("chunk_order", 0),
            meta.get("subchunk_index", 0),
            meta.get("global_order", 0),
        )
    return sorted(chunks, key=_sort_key)


def _chunks_to_text(chunks: List[dict]) -> str:
    """Concatenate page_content of sorted chunks into a single lesson text."""
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
    """
    Build the path inside the ZIP:
        subject/Lop{grade}/types/lesson{lesson}.txt
    or  subject/Lop{grade}/lesson{lesson}.txt  (if types is empty/general at root level)
    """
    # Normalize types
    types_lower = types.strip().lower()

    # If types is one of the known sub-folders, include it
    if types_lower in ("general", "lt", "th"):
        return f"{subject}/Lop{grade}/{types}/lesson{lesson}.txt"
    else:
        # Fallback: put in root of Lop folder
        return f"{subject}/Lop{grade}/lesson{lesson}.txt"


def export_to_zip(
    json_root: str,
    output_zip: str,
    *,
    verbose: bool = True,
) -> Dict[str, int]:
    """
    Read chunked JSON from json_root, group by lesson, export to ZIP.

    Args:
        json_root: path to 03_chunked_raw or 04_merged_all
        output_zip: path to output .zip file

    Returns:
        stats dict with counts
    """
    json_root_p = Path(json_root).resolve()
    output_zip_p = Path(output_zip).resolve()
    output_zip_p.parent.mkdir(parents=True, exist_ok=True)

    if not json_root_p.exists():
        raise FileNotFoundError(f"JSON root not found: {json_root_p}")

    lesson_map = _build_lesson_map(json_root_p)

    if not lesson_map:
        print(f"[WARN] No lessons found in: {json_root_p}")
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
        # Check size
        size_mb = output_zip_p.stat().st_size / (1024 * 1024)
        print(f"ZIP size: {size_mb:.2f} MB", end="")
        if size_mb > 2.0:
            print(f" ⚠️  Exceeds 2MB limit! Consider splitting by subject.")
        else:
            print(f" ✓ Within 2MB limit.")

    return stats


def export_to_folder(
    json_root: str,
    output_folder: str,
    *,
    verbose: bool = True,
) -> Dict[str, int]:
    """
    Same as export_to_zip but writes plain .txt files to a folder
    (useful for inspection before zipping).
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
    """Console entry point: `uv run chunk-export`."""
    import sys

    # Default: read from 03_chunked_raw, output to outputs/export/
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
