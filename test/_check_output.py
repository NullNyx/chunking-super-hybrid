"""Quick check of chunked output."""
import json
from pathlib import Path

f = Path("outputs/toan/03_chunked_raw/toan/Toan_3_Tap_1-6.3.25.json")
data = json.loads(f.read_text(encoding="utf-8"))

print(f"Total chunks: {len(data)}")

lessons = set()
headings = set()
for d in data:
    m = d.get("metadata", {})
    lessons.add(m.get("lesson"))
    h = m.get("heading")
    if isinstance(h, list):
        headings.update(h)
    else:
        headings.add(h)

print(f"Lessons found: {sorted(x for x in lessons if x is not None)}")
print(f"Headings found: {sorted(headings)}")
print(f"\nFirst 3 chunks metadata:")
for d in data[:3]:
    print(json.dumps(d["metadata"], ensure_ascii=False, indent=2))
