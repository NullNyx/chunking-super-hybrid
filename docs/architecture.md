# Pipeline Architecture

## Overview
5-stage PDF→JSON pipeline for Vietnamese textbooks (B1→B5).

## Stages

### B1 - PDF Text Extraction (`src/b1_extract/`)
- **Input:** PDF file
- **Output:** Markdown text with heading markers (`## Heading:`)
- **Workflow:**
  1. Parse PDF using Docling
  2. OCR fallback via olmOCR for garbled fonts
  3. Detect headings using CLIP model
  4. Normalize markdown

### B2 - Convert to JSON (`src/b2_convert/`)
- **Input:** Raw markdown with heading markers
- **Output:** JSON chunks with metadata
- **Workflow:**
  1. Split by `## Heading:` markers
  2. Generate chunk IDs (SHA1)
  3. Add metadata (subject, grade, lesson)

### B3 - Semantic Chunking (`src/b3_chunk/`)
- **Input:** Normalized JSON
- **Output:** Semantic chunks (~400 tokens)
- **Workflow:**
  1. Merge small chunks
  2. Split oversized chunks (max ~650 tokens)
  3. Preserve heading hierarchy
  4. Add 2-sentence overlap

### B4 - Merge (`src/b4_merge/`)
- **Input:** Per-lesson JSON
- **Output:** Per-book JSON
- **Workflow:**
  1. Merge all lessons into single file
  2. Global ordering by lesson number

### B5 - Export (`src/b5_export/`)
- **Input:** Per-book JSON
- **Output:** ZIP for CMS import
- **Workflow:**
  1. Parse TOC from text
  2. Split pages by lesson
  3. Export to ZIP

## Data Flow

```
PDF → [B1] → Markdown → [B2] → JSON chunks → [B3] → Semantic chunks
     → [B4] → Per-book JSON → [B5] → ZIP export
```

## Chunk Schema

```json
{
  "id": "sha1_hash",
  "subject": "toan",
  "grade": 1,
  "lesson": 1,
  "heading": "## Heading: ...",

  "content": "...",
  "tokens": 350,
  "prev_heading": "...",
  "next_heading": "..."
}
```

## Key Heuristics

| Stage | Heuristic |
|-------|------------|
| B1 | CLIP classifies images as heading/none/picture |
| B2 | Split on `## Heading:` markers |
| B3 | Target ~400 tokens, max ~650, 2-sentence overlap |
| B5 | TOC-based page range detection |