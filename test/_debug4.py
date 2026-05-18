import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
txt = Path("outputs/toan/01_extract_txt_raw/toan/Toan_3_Tap_1-6.3.25.txt").read_text(encoding="utf-8")
lines = txt.splitlines()

print("=== Lines containing 'Mi-li-m' (not in table/heading) ===")
for i, line in enumerate(lines):
    if "Mi-li-m" in line and "|" not in line and not line.strip().startswith("##"):
        print(f"  {i}: [{line.strip()[:80]}]")

print("\n=== Lines containing 'MI-LI-M' or 'MI LI M' (uppercase) ===")
for i, line in enumerate(lines):
    up = line.upper()
    if ("MI-LI-M" in up or "MI LI M" in up) and "|" not in line and not line.strip().startswith("##"):
        print(f"  {i}: [{line.strip()[:80]}]")

print("\n=== Check normalize of 'Mi-li-mét' ===")
def norm(s):
    s = re.sub(r"[\s,;:.\-\u2013\u2014]+", " ", s.upper()).strip()
    return s
print(f"  'Mi-li-mét' -> '{norm('Mi-li-mét')}'")
print(f"  'MI-LI-MÉT' -> '{norm('MI-LI-MÉT')}'")

# Check what's around line 1400-1470
print("\n=== Lines 1400-1470 (where Bài 30-32 should be) ===")
for i in range(1400, min(1470, len(lines))):
    s = lines[i].strip()
    if s and "|" not in s:
        print(f"  {i}: {s[:80]}")
