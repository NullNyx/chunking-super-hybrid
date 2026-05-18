import json
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from functools import lru_cache

# =========================
# CONFIG (CHỐT THEO LOGIC CUỐI)
# =========================
MIN_TOKENS = 200          # subheading < MIN -> merge vào main gần nhất
TARGET_TOKENS = 400       # chỉ dùng khi split 1 section quá dài (pack)
MAX_TOKENS = 650          # vượt MAX mới split
OVERLAP_UNITS = 1         # (giữ config, hiện overlap theo 2 câu)
OVERLAP_SENTENCES = 2     # overlap theo 2 câu cuối (CHỈ khi split)
OVERLAP_MAX_TOKENS = 120
CHUNK_VERSION = "v3"

# MAIN headings: KHÔNG bao giờ merge main với main khác
MAIN_HEADINGS = {
    "Mở đầu", "Mục tiêu", "Thực hành", "Vận dụng", "Ghi nhớ",
    "Tóm tắt kiến thức", "Câu hỏi và bài tập", "Khám phá"
}

NO_SPLIT_HEADINGS = {"Ghi nhớ"}

# Map subject -> tên sách (normalize key lower)
SUBJECT_TO_BOOK_TITLE = {
    "ttnt": "Trí tuệ nhân tạo",
    "vhnt": "Giáo dục Văn hóa - Nghệ thuật",
    "htlt": "Hành trình Lý tưởng - Tuổi trẻ Việt Nam",
    "sđ": "Sống đẹp theo gương Bác Hồ",
    "sd": "Sống đẹp theo gương Bác Hồ",
    "sdtgbh": "Sống đẹp theo gương Bác Hồ",
}

# Map types -> nhãn (normalize key lower)
TYPES_LABEL_DEFAULT = {
    "general": "",
    "lt": "Lý thuyết",
    "th": "Thực hành",
}

# =========================
# Token counting
# =========================
WORD_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

@lru_cache(maxsize=1)
def _get_encoder():
    import tiktoken  # type: ignore
    return tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    try:
        enc = _get_encoder()
        return len(enc.encode(text))
    except Exception:
        return len(WORD_TOKEN_RE.findall(text))

def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()

def sha1_id(*parts: str) -> str:
    raw = "|".join([p for p in parts if p is not None]).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()

def _is_no_split_heading(h: str) -> bool:
    return norm_heading(h) in NO_SPLIT_HEADINGS_N

def norm_heading(h: str) -> str:
    """
    Normalize heading để so sánh:
    - strip
    - gom nhiều space -> 1 space
    - casefold (mạnh hơn lower, hợp tiếng Việt)
    """
    return re.sub(r"\s+", " ", (h or "").strip()).casefold()

# Precompute normalized sets (để compare nhanh + không phụ thuộc hoa/thường)
MAIN_HEADINGS_N = {norm_heading(x) for x in MAIN_HEADINGS}
NO_SPLIT_HEADINGS_N = {norm_heading(x) for x in NO_SPLIT_HEADINGS}
# =========================
# Vietnamese sentence splitter (robust overlap "2 câu chuẩn")
# =========================
_ABBR_PATTERNS = [
    r"TP\.HCM\.", r"TP\.", r"Q\.", r"P\.", r"H\.", r"TX\.", r"T\.", r"Đ\.",
    r"ThS\.", r"TS\.", r"PGS\.", r"GS\.", r"CN\.", r"THCS\.", r"THPT\.",
    r"VD\.", r"Vd\.", r"V\.d\.", r"V\.d\:", r"vd\.",
    r"Mr\.", r"Mrs\.", r"Ms\.", r"Dr\.",
]
_ABBR_RE = re.compile("|".join(f"(?:{p})" for p in _ABBR_PATTERNS))
_DECIMAL_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")  # 3.5, 1.2
_SENT_END_RE = re.compile(r"([\.!?…]+)(\s+|$)")   # dấu kết câu + khoảng trắng/EOF

def _mask_text_for_sentence_split(text: str) -> Tuple[str, Dict[str, str]]:
    mapping: Dict[str, str] = {}
    out = text

    def put(token: str) -> str:
        key = f"__MASK{len(mapping)}__"
        mapping[key] = token
        return key

    out = _ABBR_RE.sub(lambda m: put(m.group(0)), out)
    out = _DECIMAL_DOT_RE.sub("__DOT__", out)
    return out, mapping

def _unmask_text(masked: str, mapping: Dict[str, str]) -> str:
    out = masked.replace("__DOT__", ".")
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out

def split_sentences_vi(text: str) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return []

    sents: List[str] = []
    for para in paragraphs:
        masked, mapping = _mask_text_for_sentence_split(para)

        start = 0
        for m in _SENT_END_RE.finditer(masked):
            end = m.end(1)
            sent = masked[start:end].strip()
            start = m.end()

            if sent:
                sent = _unmask_text(sent, mapping).strip()
                if sent:
                    sents.append(sent)

        tail = masked[start:].strip()
        if tail:
            tail = _unmask_text(tail, mapping).strip()
            if tail:
                sents.append(tail)

    sents = [re.sub(r"\s+", " ", s).strip() for s in sents if s.strip()]
    return sents

def get_last_n_sentences(text: str, n: int = 2) -> str:
    text = normalize_text(text)
    if not text or n <= 0:
        return ""

    sents = split_sentences_vi(text)
    if not sents:
        return ""

    tail = sents[-n:] if len(sents) >= n else sents
    return normalize_text(" ".join(tail))

# =========================
# Semantic unit splitting (PRIORITY)
# =========================
ROMAN_ITEM_RE = re.compile(
    r"""^\s*
    (?P<roman>
        (?:M{0,4}(?:CM|CD|D?C{0,3})
        (?:XC|XL|L?X{0,3})
        (?:IX|IV|V?I{1,3})|V|I{1,3}|X|L|C|D|M)
    )
    (?:\s*[\.\)\:\-]\s+|\s+)
    """,
    re.IGNORECASE | re.VERBOSE
)
NUM_ITEM_RE = re.compile(r"^\s*\d+\s*[\.\)]\s+", re.UNICODE)
ALPHA_ITEM_RE = re.compile(r"^\s*[a-zA-Z]\s*[\)\.]\s+", re.UNICODE)
CASE_LINE_RE = re.compile(r"^\s*(Trường\s*hợp|Tình\s*huống)\b", re.IGNORECASE)
BULLET_LINE_RE = re.compile(r"^\s*([-+*•])\s+", re.UNICODE)

# fallback sentence splitter (cho fallback units)
SENT_SPLIT_RE = re.compile(r"(?<=[\.\!\?\。\…])\s+")

def _get_heading_str(meta_heading: Any) -> str:
    if isinstance(meta_heading, list) and meta_heading:
        return str(meta_heading[0])
    if meta_heading is None:
        return "UNKNOWN"
    return str(meta_heading)

def _is_main_heading(h: str) -> bool:
    return norm_heading(h) in MAIN_HEADINGS_N

def _extract_title(meta: Dict[str, Any]) -> str:
    for k in ("title", "lesson_title", "lesson_name"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _normalize_types_label(types: str) -> str:
    t = (types or "").strip().lower()
    return TYPES_LABEL_DEFAULT.get(t, (types or "").strip())

def _format_block(heading: str, content: str, is_main: bool) -> str:
    heading = (heading or "UNKNOWN").strip()
    content = normalize_text(content)
    prefix = "###" if is_main else "##"
    if content:
        return normalize_text(f"{prefix} {heading}:\n{content}")
    else:
        return normalize_text(f"{prefix} {heading}:")

def inject_ellipsis_after_heading(block: str, add_head: bool, add_tail: bool) -> str:
    block = normalize_text(block)
    if not block:
        return block

    lines = block.split("\n")
    if not lines:
        return block

    first = lines[0].strip()
    is_heading_line = first.startswith("### ") or first.startswith("## ")

    out_lines = []
    if is_heading_line:
        out_lines.append(lines[0])
        if add_head:
            out_lines.append("...")
        out_lines.extend(lines[1:])
    else:
        if add_head:
            out_lines.append("...")
        out_lines.extend(lines)

    if add_tail:
        out_lines.append("...")

    return normalize_text("\n".join(out_lines))

def split_into_semantic_units(text: str) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []

    lines = [ln.rstrip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []

    def unit_type(ln: str) -> int:
        if ROMAN_ITEM_RE.match(ln): return 1
        if NUM_ITEM_RE.match(ln): return 2
        if ALPHA_ITEM_RE.match(ln): return 3
        if CASE_LINE_RE.match(ln): return 4
        if BULLET_LINE_RE.match(ln): return 5
        return 999

    if all(unit_type(ln) == 999 for ln in lines):
        sents = SENT_SPLIT_RE.split(text)
        sents = [s.strip() for s in sents if s.strip()]
        if len(sents) <= 1 and len(lines) > 1:
            return [ln.strip() for ln in lines if ln.strip()]
        return sents

    units: List[List[str]] = []
    cur: List[str] = []
    for ln in lines:
        t = unit_type(ln)
        if t != 999:
            if cur:
                units.append(cur)
            cur = [ln.strip()]
        else:
            if not cur:
                cur = [ln.strip()]
            else:
                cur.append(ln.strip())

    if cur:
        units.append(cur)

    return [normalize_text("\n".join(u)) for u in units if u]

def build_heading_path(meta: Dict[str, Any], headings: List[str]) -> str:
    subject = str(meta.get("subject", "") or "").strip()
    types = str(meta.get("types", "") or "").strip()
    kb_id = meta.get("kb_id")
    lesson = meta.get("lesson")

    kb_part = f"Lop{kb_id}" if kb_id is not None and str(kb_id).strip() else ""
    lesson_part = f"lesson{lesson}" if lesson is not None and str(lesson).strip() else ""
    heading_join = " + ".join([str(h).strip() for h in headings if str(h).strip()]).strip()

    parts = []
    if subject: parts.append(subject)
    if kb_part: parts.append(kb_part)
    if types: parts.append(types)
    if lesson_part: parts.append(lesson_part)
    if heading_join: parts.append(heading_join)

    return "/".join(parts)

def build_reference(meta: Dict[str, Any], headings: List[str]) -> str:
    subject_raw = str(meta.get("subject", "") or "").strip()
    subject = subject_raw.lower()
    types = str(meta.get("types", "") or "").strip()
    kb_id = meta.get("kb_id")
    lesson = meta.get("lesson")

    book_title = SUBJECT_TO_BOOK_TITLE.get(subject, subject_raw or "Sách (Unknown)")
    book_part = f"Sách {book_title}"

    if subject == "ttnt":
        label = _normalize_types_label(types)
        if label:
            book_part = f"{book_part} ({label})"

    lop_part = f"Lớp {kb_id}" if kb_id is not None and str(kb_id).strip() else "Lớp ?"
    bai_part = f"Bài {lesson}" if lesson is not None and str(lesson).strip() else "Bài ?"

    return f"{book_part}, {lop_part} {bai_part}"

def wrap_reference(meta: Dict[str, Any], headings: List[str]) -> str:
    ref = build_reference(meta, headings)
    return f'[Reference:"{ref}"]'

def add_reference_prefix(meta: Dict[str, Any], headings: List[str], content: str) -> str:
    ref_line = wrap_reference(meta, headings)
    return normalize_text(ref_line + "\n" + content)

def split_large_text_by_units(
    text: str,
    target_tokens: int,
    max_tokens: int,
    *,
    do_overlap: bool,
    overlap_sentences: int = OVERLAP_SENTENCES,
    overlap_max_tokens: int = OVERLAP_MAX_TOKENS,
) -> List[str]:
    text = normalize_text(text)
    if count_tokens(text) <= max_tokens:
        return [text]

    units = split_into_semantic_units(text)
    if not units:
        return [text]

    chunks: List[str] = []
    buf: List[str] = []
    buf_t = 0

    def flush():
        nonlocal buf, buf_t
        if buf:
            chunks.append(normalize_text("\n".join(buf)))
            buf = []
            buf_t = 0

    for u in units:
        u = u.strip()
        if not u:
            continue
        t = count_tokens(u)

        if t > max_tokens:
            flush()
            hard_parts = re.split(r"(?<=[\.\!\?\;\:])\s+", u)
            hard_parts = [p.strip() for p in hard_parts if p.strip()]

            if len(hard_parts) > 1:
                tmp: List[str] = []
                tmp_t = 0
                for p in hard_parts:
                    pt = count_tokens(p)
                    if tmp and tmp_t + pt > max_tokens:
                        chunks.append(normalize_text("\n".join(tmp)))
                        tmp = [p]
                        tmp_t = pt
                    else:
                        tmp.append(p)
                        tmp_t += pt
                if tmp:
                    chunks.append(normalize_text("\n".join(tmp)))
                continue

            words = u.split()
            tmp = []
            tmp_t = 0
            for w in words:
                wt = count_tokens(w)
                if tmp and tmp_t + wt > max_tokens:
                    chunks.append(normalize_text(" ".join(tmp)))
                    tmp = [w]
                    tmp_t = wt
                else:
                    tmp.append(w)
                    tmp_t += wt
            if tmp:
                chunks.append(normalize_text(" ".join(tmp)))
            continue

        if buf and (buf_t + t > max_tokens):
            flush()

        buf.append(u)
        buf_t += t

        if buf_t >= target_tokens and buf_t >= MIN_TOKENS:
            flush()

    flush()

    # overlap chỉ khi thực sự split ra > 1 phần
    if (not do_overlap) or (len(chunks) <= 1):
        return chunks

    out = [chunks[0]]
    for i in range(1, len(chunks)):
        cur = chunks[i]
        prev_raw = chunks[i - 1]

        tail_text = get_last_n_sentences(prev_raw, overlap_sentences)

        if tail_text and count_tokens(tail_text) > overlap_max_tokens:
            words = tail_text.split()
            while words and count_tokens(" ".join(words)) > overlap_max_tokens:
                words.pop(0)
            tail_text = normalize_text(" ".join(words))

        if tail_text and not cur.startswith(tail_text):
            cur = normalize_text(tail_text + "\n" + cur)

        out.append(cur)

    return out

def _build_full_heading_path(meta: Dict[str, Any], headings: List[str]) -> str:
    return build_heading_path(meta, headings)

# =========================
# POSTPROCESS
# =========================
def postprocess_lesson_items(
    items: List[Dict[str, Any]],
    min_tokens: int = MIN_TOKENS,
    target_tokens: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap_units: int = OVERLAP_UNITS,
    chunk_version: str = CHUNK_VERSION,
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    current_main: Optional[str] = None
    current_main_meta: Optional[Dict[str, Any]] = None

    for it in items:
        meta = it.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        heading = _get_heading_str(meta.get("heading")).strip()
        content = normalize_text(it.get("page_content", "") or "")
        if not content:
            continue

        is_main = _is_main_heading(heading)
        if is_main:
            current_main = heading
            current_main_meta = meta

        sections.append({
            "meta": meta,
            "heading": heading,
            "content": content,
            "is_main": is_main,
            "main_parent": current_main,
            "main_parent_meta": current_main_meta,
        })

    if not sections:
        return []

    out: List[Dict[str, Any]] = []
    heading_counters: Dict[str, int] = {}

    buf_main_meta: Optional[Dict[str, Any]] = None
    buf_main_heading: Optional[str] = None
    buf_main_blocks: List[str] = []
    buf_sub_headings_injected: List[str] = []

    def _emit_chunk(
        base_meta: Dict[str, Any],
        headings_list: List[str],      # ✅ field heading sẽ theo cái này
        blocks: List[str],
        subchunk_info: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
        path_headings_list: Optional[List[str]] = None,  # ✅ dùng để build heading_path ổn định
    ):
        nonlocal out, heading_counters

        title = _extract_title(base_meta)

        stable_path_heads = path_headings_list if path_headings_list else headings_list
        full_heading_path = _build_full_heading_path(base_meta, stable_path_heads)

        clean_blocks = [normalize_text(b) for b in blocks if normalize_text(b)]
        sub_idx = sub_total = None
        if subchunk_info:
            sub_idx = subchunk_info.get("subchunk_index")
            sub_total = subchunk_info.get("subchunk_total")

        add_head = bool(sub_idx and sub_total and sub_total > 1 and sub_idx > 1)
        add_tail = bool(sub_idx and sub_total and sub_total > 1 and sub_idx < sub_total)

        if clean_blocks:
            idx_inject = 0
            for j in range(len(clean_blocks) - 1, -1, -1):
                if "\n" in clean_blocks[j] and normalize_text(clean_blocks[j]).strip():
                    idx_inject = j
                    break
            clean_blocks[idx_inject] = inject_ellipsis_after_heading(
                clean_blocks[idx_inject],
                add_head=add_head,
                add_tail=add_tail
            )

        raw_content = normalize_text("\n\n".join(clean_blocks))

        # ✅ Reference dùng headings_list (đúng theo field heading bạn muốn)
        page_content = add_reference_prefix(base_meta, headings_list, raw_content)

        # ✅ chunk_order ổn định theo heading_path (stable_path_heads)
        heading_key = full_heading_path or (" + ".join(stable_path_heads) if stable_path_heads else "UNKNOWN")
        heading_counters[heading_key] = heading_counters.get(heading_key, 0) + 1
        chunk_order = heading_counters[heading_key]

        chunk_id = sha1_id(
            str(base_meta.get("subject", "")),
            str(base_meta.get("kb_id", "")),
            str(base_meta.get("types", "")),
            str(base_meta.get("lesson", "")),
            str(heading_key),
            str(chunk_version),
            str(chunk_order),
            page_content[:200],
        )

        new_meta = dict(base_meta)
        new_meta["chunk_version"] = chunk_version
        new_meta["chunk_order"] = chunk_order
        new_meta["chunk_id"] = chunk_id
        new_meta["length"] = len(page_content)
        new_meta["length_token"] = count_tokens(page_content)

        # ✅ user wants: heading field đầy đủ
        new_meta["heading"] = headings_list[:]

        if subchunk_info:
            new_meta.update(subchunk_info)
        if extra_meta:
            new_meta.update(extra_meta)

        out.append({"metadata": new_meta, "page_content": page_content})

    def flush_main_buf():
        nonlocal buf_main_meta, buf_main_heading, buf_main_blocks, buf_sub_headings_injected
        if buf_main_meta is None or not buf_main_heading or not buf_main_blocks:
            buf_main_meta, buf_main_heading, buf_main_blocks, buf_sub_headings_injected = None, None, [], []
            return

        # ✅ Field heading: gồm cả sub inject
        headings_list = [buf_main_heading] + (buf_sub_headings_injected[:] if buf_sub_headings_injected else [])

        # ✅ heading_path ổn định: CHỈ theo main
        path_headings_list = [buf_main_heading]

        _emit_chunk(
            base_meta=buf_main_meta,
            headings_list=headings_list,
            blocks=buf_main_blocks,
            subchunk_info=None,
            extra_meta=None,
            path_headings_list=path_headings_list,
        )

        buf_main_meta, buf_main_heading, buf_main_blocks, buf_sub_headings_injected = None, None, [], []

    # ==== loop sections ====
    for sec in sections:
        meta = sec["meta"]
        heading = sec["heading"]
        content = sec["content"]
        is_main = sec["is_main"]
        main_parent = sec["main_parent"]
        main_parent_meta = sec["main_parent_meta"]

        t = count_tokens(content)

        if is_main:
            flush_main_buf()

            if _is_no_split_heading(heading):
                buf_main_meta = dict(meta)
                buf_main_heading = heading
                buf_main_blocks = [_format_block(heading, content, is_main=True)]
                buf_sub_headings_injected = []
                continue

            if t > max_tokens:
                parts = split_large_text_by_units(
                    content,
                    target_tokens=target_tokens,
                    max_tokens=max_tokens,
                    do_overlap=True,
                )

                base_key = f"{meta.get('subject','')}|{meta.get('kb_id','')}|{meta.get('types','')}|{meta.get('lesson','')}|{heading}"
                parent_id = meta.get("chunk_id") or sha1_id(base_key, "PARENT", content[:200])

                for idx, part in enumerate(parts, start=1):
                    blocks = [_format_block(heading, part, is_main=True)]
                    subchunk_info = None
                    if len(parts) > 1:
                        subchunk_info = {
                            "parent_chunk_id": parent_id,
                            "subchunk_index": idx,
                            "subchunk_total": len(parts),
                        }
                    _emit_chunk(
                        base_meta=meta,
                        headings_list=[heading],
                        blocks=blocks,
                        subchunk_info=subchunk_info,
                    )
                continue

            buf_main_meta = dict(meta)
            buf_main_heading = heading
            buf_main_blocks = [_format_block(heading, content, is_main=True)]
            buf_sub_headings_injected = []
            continue

        # sub đứng đầu file
        if not main_parent or not main_parent_meta:
            if t > max_tokens:
                parts = split_large_text_by_units(
                    content,
                    target_tokens=target_tokens,
                    max_tokens=max_tokens,
                    do_overlap=True,
                )
                base_key = f"{meta.get('subject','')}|{meta.get('kb_id','')}|{meta.get('types','')}|{meta.get('lesson','')}|{heading}"
                parent_id = meta.get("chunk_id") or sha1_id(base_key, "PARENT", content[:200])

                for idx, part in enumerate(parts, start=1):
                    blocks = [_format_block(heading, part, is_main=False)]
                    subchunk_info = None
                    if len(parts) > 1:
                        subchunk_info = {
                            "parent_chunk_id": parent_id,
                            "subchunk_index": idx,
                            "subchunk_total": len(parts),
                        }
                    _emit_chunk(
                        base_meta=meta,
                        headings_list=[heading],
                        blocks=blocks,
                        subchunk_info=subchunk_info,
                    )
            else:
                _emit_chunk(
                    base_meta=meta,
                    headings_list=[heading],
                    blocks=[_format_block(heading, content, is_main=False)],
                    subchunk_info=None,
                )
            continue

        # SUB < MIN => inject vào main
        if t < min_tokens:
            injected = normalize_text(f"## {heading}:\n{content}")

            if buf_main_heading != main_parent or buf_main_meta is None:
                blocks = [
                    _format_block(main_parent, "", is_main=True),
                    injected,
                ]
                _emit_chunk(
                    base_meta=main_parent_meta,
                    headings_list=[main_parent, heading],
                    blocks=blocks,
                    subchunk_info=None,
                )
                continue

            buf_main_blocks.append(injected)
            buf_sub_headings_injected.append(heading)
            continue

        # SUB đủ dài => chunk riêng + context main
        if t > max_tokens:
            parts = split_large_text_by_units(
                content,
                target_tokens=target_tokens,
                max_tokens=max_tokens,
                do_overlap=True,
            )

            base_key = (
                f"{main_parent_meta.get('subject','')}|{main_parent_meta.get('kb_id','')}|"
                f"{main_parent_meta.get('types','')}|{main_parent_meta.get('lesson','')}|"
                f"{main_parent}|{heading}"
            )
            parent_id = meta.get("chunk_id") or sha1_id(base_key, "PARENT", content[:200])

            for idx, part in enumerate(parts, start=1):
                blocks = [
                    _format_block(main_parent, "", is_main=True),
                    _format_block(heading, part, is_main=False),
                ]
                subchunk_info = None
                if len(parts) > 1:
                    subchunk_info = {
                        "parent_chunk_id": parent_id,
                        "subchunk_index": idx,
                        "subchunk_total": len(parts),
                    }

                _emit_chunk(
                    base_meta=main_parent_meta,
                    headings_list=[main_parent, heading],
                    blocks=blocks,
                    subchunk_info=subchunk_info,
                )
        else:
            blocks = [
                _format_block(main_parent, "", is_main=True),
                _format_block(heading, content, is_main=False),
            ]
            _emit_chunk(
                base_meta=main_parent_meta,
                headings_list=[main_parent, heading],
                blocks=blocks,
                subchunk_info=None,
            )

    flush_main_buf()
    return out

# =========================
# Folder processing
# =========================
def process_json_folder(
    input_root: str,
    output_root: str,
    min_tokens: int = MIN_TOKENS,
    target_tokens: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap_units: int = OVERLAP_UNITS,
    chunk_version: str = CHUNK_VERSION,
) -> None:
    in_root = Path(input_root).resolve()
    out_root = Path(output_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    json_files = [p for p in in_root.rglob("*.json") if p.is_file() and not p.name.startswith("_")]
    if not json_files:
        print(f"No .json found under: {in_root}")
        return

    processed = 0
    for in_path in json_files:
        rel = in_path.relative_to(in_root)
        out_path = out_root / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = json.loads(in_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[SKIP] Cannot read JSON: {in_path} ({e})")
            continue

        if not isinstance(data, list):
            print(f"[SKIP] Not a list JSON: {in_path}")
            continue

        new_items = postprocess_lesson_items(
            data,
            min_tokens=min_tokens,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_units=overlap_units,
            chunk_version=chunk_version,
        )

        out_path.write_text(json.dumps(new_items, ensure_ascii=False, indent=2), encoding="utf-8")
        processed += 1

    print(f"Done. Processed {processed}/{len(json_files)} files.")
    print(f"Output root: {out_root}")


if __name__ == "__main__":
    process_json_folder(
        input_root=r".\outputs\02_convert_json_raw",
        output_root=r".\outputs\03_chunked_raw",
        min_tokens=MIN_TOKENS,
        target_tokens=TARGET_TOKENS,
        max_tokens=MAX_TOKENS,
        overlap_units=OVERLAP_UNITS,
        chunk_version=CHUNK_VERSION,
    )
