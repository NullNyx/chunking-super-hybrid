"""
chunking_super_hybrid — Pipeline PDF sách giáo khoa → text/JSON → Qdrant.

Module layout:
    cli.py                      Entry point, orchestrates full pipeline (B1→B5)
    check_env.py                Environment sanity check

    # B1: PDF → Raw Text + Heading Detection
    extract_text_and_heading.py Docling extraction + CLIP heading classification

    # B2: Raw Text → JSON chunks
    convert_text_raw_to_json.py Split by heading markers → JSON with metadata

    # B3: Semantic Chunking + Overlap
    merge_and_split_json.py     Token-aware chunking, overlap, reference tracking

    # B4: Merge Lessons
    post_process_json.py        Merge per-lesson JSONs into per-book files

    # B5: Page-based Lesson Splitting + Export
    page_split.py               TOC parsing, page extraction, lesson splitting
    export_zip.py               ZIP creation for CMS import

    # OCR (for PDFs with garbled fonts)
    olmocr_extract.py           olmOCR server client (Vietnamese OCR)

    # Optional: Vector DB Upload
    upload_qdrant.py            Embed + upsert to Qdrant (dense + sparse)
"""
