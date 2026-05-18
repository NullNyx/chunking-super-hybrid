"""Debug lessons 30, 32, 37."""
import re
from pathlib import Path

txt = Path("outputs/toan/01_extract_txt_raw/toan/Toan_3_Tap_1-6.3.25.txt").read_text(encoding="utf-8")
lines = txt.splitlines()

# TOC
TOC_RE = re.compile(r"\|\s*\|\s*Bài\s+(\d+)\.\s*(.+?)\s*\|\s*(\d+)\s*\|")
toc = {}
for line in lines:
    m = TOC_RE.search(line)
    if m:
        toc[int(m.group(1))] = m.group(2).strip()

for n in [30, 32, 37]:
    title = toc.get(n, "?")
    print(f"Bài {n}: '{title}'")
    # Search in body (non-table, non-heading lines)
    norm = re.sub(r"[\s,;:.\-–—]+", " ", title.upper()).strip()
    print(f"  norm: '{norm}'")
    for i, line in enumerate(lines[80:], 81):
        if "|" in line or line.strip().startswith("##"):
            continue
        ln = re.sub(r"[\s,;:.\-–—]+", " ", line.strip().upper()).strip()
        if norm == ln:
            print(f"  EXACT FULL LINE at {i}: '{line.strip()}'")
            break
        if norm in ln and len(norm) >= len(ln) * 0.5:
            print(f"  SUBSTRING at {i}: '{line.strip()}'")
            break
    else:
        # Try partial
        for i, line in enumerate(lines[80:], 81):
            if "|" in line or line.strip().startswith("##"):
                continue
            ln = re.sub(r"[\s,;:.\-–—]+", " ", line.strip().upper()).strip()
            if not ln:
                continue
            words = norm.split()
            matches = sum(1 for w in words if w in ln)
            if len(words) >= 2 and matches/len(words) >= 0.85 and len(norm)/max(len(ln),1) >= 0.4:
                print(f"  FUZZY at {i} ({matches}/{len(words)}): '{line.strip()[:80]}'")
                break
        else:
            print(f"  NOT FOUND!")
    print()
