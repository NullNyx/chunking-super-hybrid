"""
B4 - Merge / Gộp các lesson JSON thành file per-book

Input:
- JSON files per-lesson từ B3

Output:
- File JSON per-group (subject + grade + types)

Workflow:
1. Group lesson files theo (subject, grade, types)
2. Sort theo lesson number
3. Merge thành single file per group

Example:
    Input:  htlt/Lop1/general/lesson1.json, lesson2.json, ...
    Output: htlt/Lop1/general/htlt_1_general_v2.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# === CONSTANTS ===

# Fields to strip from metadata for cleaner dataset
STRIP_META_FIELDS = True  # Toggle True/False to enable/disable
FIELDS_TO_REMOVE = {"title", "heading_join", "heading_path"}

# Regex to extract lesson number from filename (e.g., lesson4.json)
LESSON_RE = re.compile(r"lesson\s*(\d+)", re.IGNORECASE)


# === HELPER FUNCTIONS ===

def _parse_lesson_from_path(p: Path) -> Optional[int]:
    """Extract lesson number from filename.

    Args:
        p: Path to lesson file (e.g., lesson4.json).

    Returns:
        Lesson number or None if not found.
    """
    m = LESSON_RE.search(p.stem)
    return int(m.group(1)) if m else None


def safe_print(s: str) -> None:
    """Print with Unicode fallback for Windows console.

    Args:
        s: String to print.
    """
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8"))


def strip_metadata_fields(
    meta: Dict[str, Any],
    *,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Remove specified metadata fields to produce cleaner dataset.

    Args:
        meta: Metadata dictionary.
        enabled: If False, returns original metadata unchanged.

    Returns:
        Modified metadata dictionary.
    """
    if not enabled or not isinstance(meta, dict):
        return meta

    for k in FIELDS_TO_REMOVE:
        if k in meta:
            meta.pop(k, None)
    return meta


# === MAIN MERGE ===

def merge_all_lessons_to_one_json(
    input_root: str,
    output_root: str,
    out_version: str = "v2",
    strip_meta_fields: bool = False,
) -> None:
    """Merge all lesson JSON files into single files per subject/grade/types.

    Groups files by (subject, kb_folder, types), sorts lessons by number,
    then merges into one JSON file per group with global ordering.

    Args:
        input_root: Root directory containing lesson .json files.
        output_root: Root directory for merged output files.
        out_version: Version string to update in metadata.
        strip_meta_fields: If True, removes title, heading_join, heading_path.
    """
    in_root = Path(input_root).resolve()
    out_root = Path(output_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Find all JSON files (excluding hidden files)
    json_files = [
        p for p in in_root.rglob("*.json")
        if p.is_file() and not p.name.startswith("_")
    ]
    if not json_files:
        safe_print(f"[WARN] No lesson*.json found under: {in_root}")
        return

    # Group by (subject, kb_folder, types)
    groups: Dict[Tuple[str, str, str], List[Path]] = {}
    for p in json_files:
        rel = p.relative_to(in_root)
        parts = rel.parts
        subject = parts[0] if len(parts) >= 1 else "unknown"
        kb_folder = parts[1] if len(parts) >= 2 else "unknown"
        types = parts[2] if len(parts) >= 3 else "unknown"
        groups.setdefault((subject, kb_folder, types), []).append(p)

    written = 0

    for (subject, kb_folder, types), paths in sorted(groups.items()):
        # Sort lesson files by lesson number
        paths_sorted = sorted(
            paths,
            key=lambda x: (_parse_lesson_from_path(x) or 10**9, x.name)
        )

        merged_items: List[Dict[str, Any]] = []
        kb_id: Optional[int] = None

        for lesson_path in paths_sorted:
            try:
                data = json.loads(lesson_path.read_text(encoding="utf-8"))
            except Exception as e:
                safe_print(f"[SKIP] Cannot read JSON: {lesson_path} ({e})")
                continue

            if not isinstance(data, list):
                safe_print(f"[SKIP] Not a list JSON: {lesson_path}")
                continue

            # Update metadata version and optionally strip fields
            rel_lesson = str(lesson_path.relative_to(in_root)).replace("/", "\\")
            for it in data:
                if not isinstance(it, dict):
                    continue
                meta = it.get("metadata") or {}
                if isinstance(meta, dict):
                    # Get kb_id from metadata if available
                    if kb_id is None and meta.get("kb_id") is not None:
                        try:
                            kb_id = int(meta["kb_id"])
                        except Exception:
                            kb_id = meta.get("kb_id")

                    meta["chunk_version"] = out_version
                    meta = strip_metadata_fields(meta, enabled=strip_meta_fields)
                    it["metadata"] = meta

                merged_items.append(it)

        if not merged_items:
            continue

        # Parse kb_id from folder name if not found in metadata
        if kb_id is None:
            m = re.search(r"(\d+)", kb_folder)
            kb_id = int(m.group(1)) if m else None

        # Sort items for consistent ordering
        def sort_key(it: Dict[str, Any]) -> Tuple[int, int, int]:
            meta = it.get("metadata") or {}
            lesson = meta.get("lesson")
            try:
                lesson_num = int(lesson) if lesson is not None else 10**9
            except Exception:
                lesson_num = 10**9

            chunk_order = meta.get("chunk_order")
            try:
                co = int(chunk_order) if chunk_order is not None else 10**9
            except Exception:
                co = 10**9

            sub_idx = meta.get("subchunk_index")
            try:
                si = int(sub_idx) if sub_idx is not None else 0
            except Exception:
                si = 0

            return (lesson_num, co, si)

        merged_items.sort(key=sort_key)

        # Add global_order after sorting
        for i, it in enumerate(merged_items, start=1):
            meta = it.get("metadata") or {}
            if isinstance(meta, dict):
                meta["global_order"] = i
                it["metadata"] = meta

        # Output path mirrors folder structure, one file per group
        out_dir = out_root / subject / kb_folder / types
        out_dir.mkdir(parents=True, exist_ok=True)

        # Filename: <subject>_<kb_id>_<types>_<version>.json
        kb_id_str = str(kb_id) if kb_id is not None else kb_folder
        out_name = f"{subject}_{kb_id_str}_{types}_{out_version}.json"
        out_path = out_dir / out_name

        out_path.write_text(
            json.dumps(merged_items, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        written += 1

        safe_print(f"[OK] {subject}/{kb_folder}/{types}: {len(merged_items)} items -> {out_path}")

    safe_print(f"Done. Written {written} merged files into: {out_root}")


if __name__ == "__main__":
    merge_all_lessons_to_one_json(
        input_root=r".\outputs\03_chunked_raw",
        output_root=r".\outputs\04_merged_all",
        out_version="v3",
        strip_meta_fields=True,
    )