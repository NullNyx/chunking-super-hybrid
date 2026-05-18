"""Sanity check for the chunking pipeline environment (no upload_qdrant deps).

Entry point: `uv run chunk-check-env` (configured in pyproject.toml).
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    print("python:", sys.version.split()[0], "-", sys.executable)

    import torch
    import torchvision
    import transformers
    import PIL
    import tiktoken
    import tqdm
    import docling
    import docling_core

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

    # Pipeline modules import-only (no execution)
    from src.extract_text_and_heading import run_one_pdf  # noqa: F401
    from src.convert_text_raw_to_json import convert_folder  # noqa: F401
    from src.merge_and_split_json import process_json_folder  # noqa: F401
    from src.post_process_json import merge_all_lessons_to_one_json  # noqa: F401
    print("pipeline modules import: OK")

    # Resolve project root: when installed via uv, CWD is the project root,
    # so prefer CWD/assets and fall back to the package-relative location.
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
