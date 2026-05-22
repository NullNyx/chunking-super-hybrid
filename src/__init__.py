"""
chunking_super_hybrid — Pipeline PDF sách giáo khoa → text/JSON

Module layout:
    cli.py                      Entry point, orchestrates full pipeline (B1→B5)
    check_env.py                Environment sanity check

    # B1: PDF → Raw Text + Heading Detection
    b1_extract/
      extract_text_and_heading.py Docling extraction + CLIP heading classification
      olmocr_extract.py           OCR fallback for garbled fonts

    # B2: Raw Text → JSON chunks
    b2_convert/
      convert_text_raw_to_json.py Split by heading markers → JSON with metadata

    # B3: Semantic Chunking + Overlap
    b3_chunk/
      merge_and_split_json.py     Token-aware chunking, overlap, reference tracking

    # B4: Merge Lessons
    b4_merge/
      post_process_json.py        Merge per-lesson JSONs into per-book files

    # B5: Page-based Lesson Splitting + Export
    b5_export/
      page_split.py               TOC parsing, page extraction, lesson splitting
      export_zip.py               ZIP creation for CMS import

    # Utilities
    pipeline_logger.py           Structured logging for pipeline runs
"""
