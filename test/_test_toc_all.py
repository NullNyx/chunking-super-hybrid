from src.page_split import parse_toc_from_text
from pathlib import Path

for p in sorted(Path("outputs/toan/_work_tmp/toan").rglob("raw_text.txt")):
    folder = p.parent.name
    entries = parse_toc_from_text(p.read_text(encoding="utf-8"))
    print(f"  {folder}: {len(entries)} entries")
