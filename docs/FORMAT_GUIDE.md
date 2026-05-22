# Code Format Guide

## Docstring Style: Google

```python
def function_name(param1: type1, param2: type2) -> return_type:
    """Short description.

    Longer description if needed.

    Args:
        param1: Description of first parameter.
        param2: Description of second parameter.

    Returns:
        Description of what is returned.

    Raises:
        ExceptionType: When this exception is raised.
    """
```

## File Structure

```
1. Module-level docstring (mục đích file, usage, pipeline step)
2. from __future__ import annotations
3. Imports (stdlib → third-party → local)
4. Constants (CONFIG, Regex patterns) with comments
5. Helper functions (private with _ prefix)
6. Public functions/classes
7. __main__ block (nếu có)
```

## Comment Standards

| Vị trí | Nội dung |
|--------|----------|
| File header | Mô tả module, usage, pipeline step |
| Function | Google docstring + giải thích business logic |
| Complex logic | Giải thích tại sao làm vậy |
| Magic numbers | Comment giải thích ý nghĩa |
| Regex | Comment pattern dùng để làm gì |

## Naming Conventions

- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Private functions: `_private_function`
- Constants: `UPPER_SNAKE_CASE`

## Type Hints

Required on all functions and classes:
```python
def function(param: str) -> int: ...
class MyClass:
    def method(self, param: List[int]) -> Dict[str, Any]: ...
```

## Pipeline Module Structure

```
src/
├── b1_extract/     # B1: PDF → TXT
│   ├── extract_text_and_heading.py
│   └── olmocr_extract.py
├── b2_convert/    # B2: TXT → JSON
│   └── convert_text_raw_to_json.py
├── b3_chunk/       # B3: Chunking
│   └── merge_and_split_json.py
├── b4_merge/       # B4: Merge lessons
│   └── post_process_json.py
└── b5_export/      # B5: Export + ZIP
    ├── page_split.py
    └── export_zip.py
```