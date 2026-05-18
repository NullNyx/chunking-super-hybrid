"""Find why lessons 7,8,15,18,22,29,35,36 are missing."""
import re
from pathlib import Path

txt = Path("outputs/toan/01_extract_txt_raw/toan/Toan_3_Tap_1-6.3.25.txt").read_text(encoding="utf-8")
lines = txt.splitlines()

# Parse TOC
TOC_RE = re.compile(r"\|\s*\|\s*Bài\s+(\d+)\.\s*(.+?)\s*\|\s*(\d+)\s*\|")
toc = {}
for line in lines:
    m = TOC_RE.search(line)
    if m:
        toc[int(m.group(1))] = m.group(2).strip()

missing = [7, 8, 15, 18, 22, 29, 35, 36]
print("Missing lessons and their TOC titles:")
for n in missing:
    title = toc.get(n, "NOT IN TOC")
    norm = re.sub(r"\s+", " ", title.upper().strip())
    print(f"  Bài {n}: '{title}'")
    print(f"    Normalized: '{norm}'")
    # Search in body (after line 80, skip TOC)
    found = False
    for i, line in enumerate(lines[80:], start=81):
        if "|" in line:
            continue
        norm_line = re.sub(r"\s+", " ", line.strip().upper())
        if norm in norm_line:
            print(f"    FOUND at line {i}: '{line.strip()}'")
            found = True
            break
    if not found:
        # Try partial match (first 3 words)
        words = norm.split()[:3]
        partial = " ".join(words)
        for i, line in enumerate(lines[80:], start=81):
            if "|" in line:
                continue
            norm_line = re.sub(r"\s+", " ", line.strip().upper())
            if partial in norm_line:
                print(f"    PARTIAL match at line {i}: '{line.strip()}'")
                found = True
                break
    if not found:
        print(f"    NOT FOUND in body text!")
    print()
