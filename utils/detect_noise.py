from __future__ import annotations

from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple


def find_weird_chars_in_text(
    text: str,
    context: int = 20,
    top_k: int = 30,
) -> List[Dict]:
    """
    Tìm các ký tự unicode lạ trong text và trả về list dict:
    {
      "char": "...",
      "codepoint": "U+....",
      "count": n,
      "examples": ["...<ch>...", ...]
    }

    'Lạ' ở đây nghĩa là:
    - Không phải ASCII
    - Không phải whitespace
    - Không nằm trong các block Latin phổ biến (bao gồm tiếng Việt)
    - Không nằm trong punctuation phổ biến
    """
    # Allowed ranges: ASCII handled separately
    allowed_ranges = [
        (0x00A0, 0x00FF),  # Latin-1 Supplement
        (0x0100, 0x024F),  # Latin Extended-A/B
        (0x1E00, 0x1EFF),  # Latin Extended Additional
        (0x2000, 0x206F),  # General punctuation
        (0x20A0, 0x20CF),  # Currency symbols
        (0x3000, 0x303F),  # CJK symbols/punct (hiếm nhưng vô hại)
    ]

    def is_allowed(cp: int) -> bool:
        for a, b in allowed_ranges:
            if a <= cp <= b:
                return True
        return False

    # Count weird chars
    weird_positions: Dict[str, List[int]] = {}
    counter = Counter()

    for i, ch in enumerate(text):
        cp = ord(ch)

        if ch.isspace():
            continue
        if cp <= 0x007F:
            continue  # ASCII ok
        if is_allowed(cp):
            continue  # Vietnamese/Latin punctuation ok

        counter[ch] += 1
        weird_positions.setdefault(ch, []).append(i)

    results = []
    for ch, cnt in counter.most_common(top_k):
        cps = f"U+{ord(ch):04X}"
        ex = []
        for pos in weird_positions[ch][:5]:  # lấy tối đa 5 ví dụ
            start = max(0, pos - context)
            end = min(len(text), pos + context + 1)
            snippet = text[start:pos] + f"[{ch}]" + text[pos + 1:end]
            ex.append(snippet.replace("\n", "\\n"))
        results.append({
            "char": ch,
            "codepoint": cps,
            "count": cnt,
            "examples": ex
        })

    return results


def scan_raw_with_images_and_suggest_rules(
    raw_with_images_path: str,
    top_k: int = 30,
) -> None:
    """
    Đọc raw_with_images.txt, tìm ký tự lạ, in ra thống kê + gợi ý rule
    để bạn copy vào fix_weird_vietnamese_glyph_noise().
    """
    p = Path(raw_with_images_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    text = p.read_text(encoding="utf-8", errors="ignore")
    weird = find_weird_chars_in_text(text, top_k=top_k)

    if not weird:
        print("✅ Không tìm thấy ký tự lạ theo tiêu chí hiện tại.")
        return

    print(f"⚠️ Found {len(weird)} weird chars (top {top_k}):\n")

    for item in weird:
        ch = item["char"]
        cp = item["codepoint"]
        cnt = item["count"]

        print(f"- Char: '{ch}'  ({cp})  count={cnt}")
        for ex in item["examples"]:
            print(f"    ex: {ex}")
        print()

    print("-----\nGợi ý rule để dán vào fix_weird_vietnamese_glyph_noise():\n")
    print("def fix_weird_vietnamese_glyph_noise(text: str) -> str:")

    # In rule skeleton: bạn tự điền mapping đúng sau khi xem examples
    for item in weird:
        ch = item["char"]
        cp = item["codepoint"]
        # placeholder replacement
        print(f"    # TODO map '{ch}' ({cp})")
        print(f"    text = text.replace('{ch}', '...')")

    print("    return text")


# Example usage:
if __name__ == "__main__":
    scan_raw_with_images_and_suggest_rules(
        raw_with_images_path=r"E:\QuangNV\Chunking_Final\z\labels_result_htlt_class_4_done_clean.txt",
        top_k=30
    )
