import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

data = json.loads(open(r'outputs\toan\02_convert_json_raw\toan\Toan_3_Tap_1-6.3.25.json','r',encoding='utf-8').read())
headings = [d['metadata']['heading'] for d in data]
print(f"Total sections: {len(headings)}")

# Find sections with lesson 30, 32, 37 or heading containing those numbers
for i, d in enumerate(data):
    h = d['metadata']['heading']
    lesson = d['metadata']['lesson']
    if lesson in (29, 30, 31, 32, 33, 36, 37, 38):
        content_preview = d['page_content'][:60].replace('\n', ' ')
        print(f"  [{i}] lesson={lesson} heading='{h}' content='{content_preview}...'")
