"""
Environment Check / Kiểm tra môi trường

Input:
- Kiểm tra dependencies đã cài đặt

Output:
- Print version info + exit code

Usage:
    uv run chunk-check-env
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Check environment and print version information.

    Returns:
        Exit code (0 for success).
    """
    print("python:", sys.version.split()[0], "-", sys.executable)

    # Import third-party dependencies
    import torch
    import torchvision
    import transformers
    import PIL
    import tiktoken
    import tqdm
    import docling
    import docling_core

    # Print version info
    print("torch       :", torch.__version__, "| cuda:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device      :", torch.cuda.get_device_name(0))
    print("torchvision :", torchvision.__version__)
    print("transformers:", transformers.__version__)
    print("docling     :", getattr(docling, "__version__", "?"))
    print("docling_core:", getattr(docling_core, "__version__", "?"))
    print("Pillow      :", PIL.__version__)
    print("tiktoken    :", tiktoken.__version__)
    print("tqdm        :", tqdm.__version__)

    # Verify pipeline modules can be imported
    from src.b1_extract.extract_text_and_heading import run_one_pdf  # noqa: F401
    from src.b2_convert.convert_text_raw_to_json import convert_folder  # noqa: F401
    from src.b3_chunk.merge_and_split_json import process_json_folder  # noqa: F401
    from src.b4_merge.post_process_json import merge_all_lessons_to_one_json  # noqa: F401
    print("pipeline modules import: OK")

    # Verify required assets exist
    # When installed via uv, CWD is the project root.
    # Prefer CWD/assets, fall back to package-relative location.
    candidates = [
        Path.cwd() / "assets",
        Path(__file__).resolve().parents[1] / "assets",
    ]
    assets_dir = next((c for c in candidates if c.exists()), candidates[0])
    proto = assets_dir / "prototypes_heading.pt"
    labels = assets_dir / "labels_heading.json"
    print("prototypes_heading.pt :", "OK" if proto.exists() else "MISSING", "->", proto)
    print("labels_heading.json   :", "OK" if labels.exists() else "MISSING", "->", labels)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())