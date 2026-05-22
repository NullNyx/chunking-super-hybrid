# Repository Guidelines

This repository uses Harness v0 for human-agent collaboration.

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
├── pyproject.toml              # Project config, dependencies, scripts
├── docs/                       # Harness docs + product contract
└── scripts/                    # Harness automation
```

## Source of Truth

Read in this order:

1. `README.md` for project status.
2. `docs/HARNESS.md` for the human-agent operating model.
3. `docs/FEATURE_INTAKE.md` before turning any prompt into work.
4. `docs/ARCHITECTURE.md` for pipeline architecture rules.
5. `docs/stories/` for story packets and backlog.
6. `docs/TEST_MATRIX.md` for proof status.
7. `docs/decisions/` for why important choices were made.

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

## Task Loop

For every task:

1. Classify the request with `docs/FEATURE_INTAKE.md`.
2. Identify whether the input is a new spec, spec slice, change request, new initiative, maintenance request, or harness improvement.
3. Locate the affected product docs and story files.
4. Check `docs/TEST_MATRIX.md` for existing proof and gaps.
5. Work only inside the selected lane: tiny, normal, or high-risk.
6. Before finishing, ask:
   - Did product truth change?
   - Did validation expectations change?
   - Did architecture rules change?
   - Did we discover a repeated failure pattern?
   - Did the next agent need a clearer instruction?
7. Update routine harness files directly, or add a proposal to `docs/HARNESS_BACKLOG.md` when the change is structural.

## Harness Change Policy

Agents may update directly:

- Story status and evidence.
- `docs/TEST_MATRIX.md` rows.
- Links from story packets to product docs.
- Validation notes and reports.
- Small clarifications tied to the current task.

Agents should ask for human confirmation before:

- Changing architecture direction.
- Removing validation requirements.
- Changing the source-of-truth hierarchy.
- Changing risk classification rules.
- Replacing the feature workflow.

## Done Definition

A task is done only when:

- The requested change is completed or the blocker is documented.
- Relevant docs, stories, and test matrix entries remain current.
- Validation commands were run when they exist.
- Missing harness capabilities were added to `docs/HARNESS_BACKLOG.md`.
- The final response says what changed and what was not attempted.