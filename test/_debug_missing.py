"""Debug why lessons 25,27,29,31-33,35-38,40 are missing."""
import re
from pathlib import Path

txt = Path("outputs/toan/01_extract_txt_raw/toan/Toan_3_Tap_1-6.3.25.txt").read_text(encoding="utf-8")
lines = txt.splitlines()

missing_titles = {
    25: "Phép chia hết, phép chia có dư",
    27: "Giảm một số đi một số lần",
    29: "Luyện tập chung",
    31: "Gam",
    32: "Mi-li-lít",
    33: "Nhiệt độ. Đơn vị đo nhiệt độ",
    35: "Luyện tập chung",
    36: "Nhân số có ba chữ số với số có một chữ số",
    37: "Chia số có ba chữ số cho số có một chữ số",
    38: "Biểu thức số. Tính giá trị của biểu thức số",
    40: "Luyện tập chung",
}

def normalize(s):
    s = re.sub(r"[\s,;:.\-–—]+", " ", s.upper()).strip()
    return s

for n, title in missing_titles.items():
    norm = normalize(title)
    print(f"Bài {n}: '{title}'")
    print(f"  norm: '{norm}'")
    found = False
    for i, line in enumerate(lines[80:], 81):
        if "|" in line:
            continue
        ln = normalize(line.strip())
        if not ln or len(ln) < 3:
            continue
        # Exact substring
        if norm in ln:
            print(f"  EXACT at line {i}: '{line.strip()[:80]}'")
            found = True
            break
        # Fuzzy: 70% word overlap
        words = norm.split()
        if len(words) >= 2:
            matches = sum(1 for w in words if w in ln)
            if matches / len(words) >= 0.7:
                print(f"  FUZZY at line {i} ({matches}/{len(words)}): '{line.strip()[:80]}'")
                found = True
                break
    if not found:
        print(f"  NOT FOUND!")
    print()
