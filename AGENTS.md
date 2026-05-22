# Repository Guidelines

## Project Structure & Module Organization

```
chunking_super_hybrid/
├── src/                        # Pipeline modules (cli, extract, convert, merge, page_split, export, olmocr, upload_qdrant, logger)
├── test/                       # pytest + Hypothesis tests
├── assets/                     # CLIP checkpoint, heading labels, prototypes
├── utils/                      # Standalone helpers (detect_noise, embedding_heading)
├── input/                      # Source PDFs, organized by subject
├── outputs/                    # Pipeline output per step (01_extract_txt_raw → 05_export)
├── logs/                       # Per-run structured logs
├── main.py                     # Root shim (imports src.cli)
└── pyproject.toml              # Project config, dependencies, scripts
```

## Build, Test, and Development Commands

- `uv sync` — Install dependencies (Python 3.11–3.12, CUDA 12.4).
- `uv sync --extra upload` — Include Qdrant upload dependencies.
- `uv run chunk-pipeline` — Run full pipeline (B1→B5).
- `uv run chunk-pipeline-ocr` — Run with olmOCR fallback for garbled-font PDFs.
- `uv run chunk-check-env` — Verify environment (CUDA, models, paths).
- `uv run chunk-export` — Export output as ZIP.
- `pytest` — Run all tests; `pytest test/test_preservation.py` for a single file.

## Coding Style & Naming Conventions

- Python 3.11+; always use `from __future__ import annotations`.
- Type hints on all function signatures and class attributes.
- Snake_case for functions/variables; PascalCase for classes.
- Module-level docstrings explaining purpose and usage.
- No formatter/linter configured — follow existing patterns.
- Keep `main.py` as a thin shim; real logic lives in `src/`.

## Testing Guidelines

- Framework: **pytest** with **Hypothesis** for property-based tests.
- Test files in `test/`, prefixed with `test_`.
- Tests must pass before submitting a PR.

## Commit & Pull Request Guidelines

- Use **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`.
- Optional scope for module-specific changes (e.g., `fix(page_split):`).
- Commit messages in English.
- PRs: clear description, reference related issues, ensure `pytest` passes.

## Architecture Notes

Pipeline processes Vietnamese textbook PDFs through five stages:

1. **B1** — PDF → raw text via Docling; CLIP classifies images; headings injected as `## Heading:` markers.
2. **B2** — Split by heading markers into raw JSON chunks with metadata (subject, grade, lesson, SHA1 chunk IDs).
3. **B3** — Semantic chunking: target ~400 tokens, max ~650, 2-sentence overlap; preserve heading hierarchy.
4. **B4** — Merge per-lesson JSONs into per-book files with global ordering.
5. **B5** — TOC-based page splitting and ZIP export for CMS import.

Output directories follow step numbering: `outputs/<subject>/01_extract_txt_raw/` through `05_export/`.
