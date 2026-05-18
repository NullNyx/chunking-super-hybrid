import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

HEADING_RE = re.compile(r"^\s*##\s*Heading:\s*(.+?)\s*$", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
WORD_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def safe_token_count(text: str) -> int:
    """
    Token count:
    - Try tiktoken (if installed) for a closer-to-LLM token estimate.
    - Fallback: count word-like tokens.
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
    # Keep line breaks but normalize whitespace within lines
    lines = [WHITESPACE_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def compute_chunk_id(subject: str, kb_folder: str, types: str, rel_file: str, heading: str, content: str) -> str:
    raw = f"{subject}|{kb_folder}|{types}|{rel_file}|{heading}|{content}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def parse_kb_id(kb_folder: str) -> Optional[int]:
    """Lop6 -> 6"""
    m = re.search(r"(\d+)", kb_folder)
    return int(m.group(1)) if m else None


def parse_lesson(filename_stem: str) -> Optional[int]:
    """lesson1 -> 1"""
    m = re.search(r"lesson\s*(\d+)", filename_stem, re.IGNORECASE)
    return int(m.group(1)) if m else None


def split_by_heading(raw: str) -> List[Tuple[str, str]]:
    """
    Return list of (heading, content).

    Rules:
    - Text before first heading -> attach to the first heading (nearest).
    - Subheadings (Câu lệnh/Câu hỏi/Tìm hiểu/Nhận biết) -> merge into previous heading (no new item).
    - Text outside headings -> attach to the nearest previous (effective) heading.
    - If no heading exists -> one chunk with heading "UNKNOWN".
    """

    # Các heading sẽ được coi là subheading và nhập vào heading trước đó
    SUBHEADINGS = {"câu lệnh", "câu hỏi"}

    def _norm_heading(h: str) -> str:
        # normalize để so sánh chắc chắn (không phân biệt hoa thường, dư khoảng trắng)
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

            # Nếu là subheading => không finalize, không tạo section mới
            # mà chèn marker + tiếp tục ghi vào buffer của heading hiện tại
            if new_heading_norm in SUBHEADINGS:
                if current_heading is None:
                    # Nếu file bắt đầu bằng subheading, tạo UNKNOWN để chứa
                    current_heading = "UNKNOWN"
                    current_buf = []
                # current_buf.append("")
                current_buf.append(f"## {new_heading}:")
                # current_buf.append("")
                continue

            # Heading chính: finalize section trước đó
            if current_heading is not None:
                sections.append((current_heading, current_buf))
            else:
                preface.extend(current_buf)

            current_heading = new_heading
            current_buf = []
        else:
            current_buf.append(line)

    # finalize last
    if current_heading is not None:
        sections.append((current_heading, current_buf))
    else:
        full = normalize_text(raw)
        return [("UNKNOWN", full)] if full else []

    # Attach preface to the first heading
    if preface and sections:
        first_heading, first_buf = sections[0]
        sections[0] = (first_heading, preface + [""] + first_buf)

    out: List[Tuple[str, str]] = []
    for h, buf in sections:
        content = normalize_text("\n".join(buf))
        if content:
            out.append((h, content))

    return out


def parse_lesson_from_content(raw: str) -> Optional[int]:
    m = re.search(r"\bBÀI\s*(\d+)\b", raw, re.IGNORECASE)
    return int(m.group(1)) if m else None


def build_chunks_for_file(
    txt_path: Path,
    input_root: Path,
    chunk_version: str = "v1",
) -> List[Dict]:
    """
    Expect path like:
    <root>/<subject>/<kb_folder>/<types>/<file>.txt
    e.g. results_v1/htlt/Lop1/general/lesson4.txt
    """
    rel = txt_path.relative_to(input_root)
    parts = rel.parts

    subject = parts[0] if len(parts) >= 1 else "unknown"
    kb_folder = parts[1] if len(parts) >= 2 else "unknown"
    types = parts[2] if len(parts) >= 3 else "unknown"   # nếu chỉ có 2-3 level thì vẫn ok
    rel_file = str(rel)
    kb_id = parse_kb_id(kb_folder)
    raw = txt_path.read_text(encoding="utf-8", errors="ignore")
    lesson = parse_lesson_from_content(raw) or parse_lesson(txt_path.stem)
    sections = split_by_heading(raw)

    # chunk_order theo heading (nếu heading lặp lại nhiều lần thì order tăng)
    heading_counters: Dict[str, int] = {}

    chunks: List[Dict] = []
    for heading, content in sections:
        heading_counters[heading] = heading_counters.get(heading, 0) + 1
        chunk_order = heading_counters[heading]

        chunk_id = compute_chunk_id(subject, kb_folder, types, rel_file, heading, content)

        meta = {
            "kb_id": kb_id,                 # Lop1 -> 1
            "subject": subject,             # htlt
            "types": types,                 # general / LT / TH
            "lesson": lesson,               # lesson4.txt -> 4
            "chunk_version": chunk_version, # v1 / v2 ...
            "chunk_order": chunk_order,     # per-heading order
            "chunk_id": chunk_id,
            "heading": heading,
            "length": len(content),         # char count
            "length_token": safe_token_count(content),
            # "source_file": rel_file,        # traceability
        }

        chunks.append({"metadata": meta, "page_content": content})

    return chunks


def convert_folder(
    input_root: str,
    output_root: str,
    chunk_version: str = "v1",
) -> None:
    """
    Convert all .txt under input_root into mirrored .json under output_root.
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


# if __name__ == "__main__":
#     convert_folder(
#         input_root=r"E:\QuangNV\Chunking_Final\z\chunking_super_hybrid\outputs\final_06012026",
#         output_root=r"E:\QuangNV\Chunking_Final\z\chunking_super_hybrid\outputs\final_06012026_json"
#     )
