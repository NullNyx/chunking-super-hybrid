import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

LESSON_RE = re.compile(r"lesson\s*(\d+)", re.IGNORECASE)
STRIP_META_FIELDS = True   # <-- đổi True/False để bật/tắt
FIELDS_TO_REMOVE = {"title", "heading_join", "heading_path"}

def _parse_lesson_from_path(p: Path) -> Optional[int]:
    """lesson4.json -> 4"""
    m = LESSON_RE.search(p.stem)
    return int(m.group(1)) if m else None

def safe_print(s: str):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8"))

def merge_all_lessons_to_one_json(
    input_root: str,
    output_root: str,
    out_version: str = "v2",
    strip_meta_fields: bool = False,   # NEW
) -> None:
    """
    Input:  folder root chứa nhiều sách/lớp/types, trong đó mỗi lesson là 1 file .json list items
            ví dụ: results_filnal_v1_json_post/htlt/Lop1/general/lesson4.json

    Output: folder tương tự, nhưng tại mỗi group <subject>/<LopX>/<types>/ sẽ có 1 file:
            <subject>_<kb_id>_<types>_<out_version>.json
            ví dụ: ttnt_1_LT_v2.json
    """
    in_root = Path(input_root).resolve()
    out_root = Path(output_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    json_files = [
        p for p in in_root.rglob("*.json")
        if p.is_file() and not p.name.startswith("_")
    ]
    if not json_files:
        print(f"[WARN] No lesson*.json found under: {in_root}")
        return

    # group key: (subject, kb_folder, types)
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
        # sort lesson files by lesson number
        paths_sorted = sorted(paths, key=lambda x: (_parse_lesson_from_path(x) or 10**9, x.name))

        merged_items: List[Dict[str, Any]] = []
        kb_id: Optional[int] = None

        for lesson_path in paths_sorted:
            try:
                data = json.loads(lesson_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[SKIP] Cannot read JSON: {lesson_path} ({e})")
                continue

            if not isinstance(data, list):
                print(f"[SKIP] Not a list JSON: {lesson_path}")
                continue

            # attach trace info + update version
            rel_lesson = str(lesson_path.relative_to(in_root)).replace("/", "\\")
            for it in data:
                if not isinstance(it, dict):
                    continue
                meta = it.get("metadata") or {}
                if isinstance(meta, dict):
                    # lấy kb_id chuẩn (nếu có)
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

        # nếu kb_id không lấy được từ metadata, thử parse từ kb_folder "Lop2" -> 2
        if kb_id is None:
            m = re.search(r"(\d+)", kb_folder)
            kb_id = int(m.group(1)) if m else None

        # sort items for consistent ordering
        def sort_key(it: Dict[str, Any]):
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

        # add global_order after sorting
        for i, it in enumerate(merged_items, start=1):
            meta = it.get("metadata") or {}
            if isinstance(meta, dict):
                meta["global_order"] = i
                it["metadata"] = meta

        # output path mirrors folder structure, but one file per group
        out_dir = out_root / subject / kb_folder / types
        out_dir.mkdir(parents=True, exist_ok=True)

        # file name: ttnt_1_LT_v2.json
        kb_id_str = str(kb_id) if kb_id is not None else kb_folder
        out_name = f"{subject}_{kb_id_str}_{types}_{out_version}.json"
        out_path = out_dir / out_name

        out_path.write_text(json.dumps(merged_items, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

        safe_print(f"[OK] {subject}/{kb_folder}/{types}: {len(merged_items)} items -> {out_path}")

    safe_print(f"Done. Written {written} merged files into: {out_root}")

def strip_metadata_fields(meta: Dict[str, Any], *, enabled: bool = True) -> Dict[str, Any]:
    """
    Xoá một số field metadata để dataset gọn hơn.
    enabled=False -> giữ nguyên.
    """
    if not enabled or not isinstance(meta, dict):
        return meta

    for k in FIELDS_TO_REMOVE:
        if k in meta:
            meta.pop(k, None)
    return meta

if __name__ == "__main__":
    merge_all_lessons_to_one_json(
        input_root=r"E:\QuangNV\Chunking_Final\z\chunking_super_hybrid\outputs\chunking_08012026_v0\03_chunked_v2",
        output_root=r"E:\QuangNV\Chunking_Final\z\chunking_super_hybrid\outputs\chunking_08012026_v0\04_dataset_09012026",
        out_version="v3",
        strip_meta_fields=True,   # <-- bật xoá
    )