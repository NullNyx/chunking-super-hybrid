uv run chunk-pipeline và uv run chunk-pipeline-ocr đang đi theo 2 luồng khác nhau:

  1. chunk-pipeline = full B1→B5
  2. chunk-pipeline-ocr = chỉ chạy B5, nhưng trích text bằng olmOCR

  Entry points

  - chunk-pipeline -> main() trong src/cli.py:599
  - chunk-pipeline-ocr -> main_ocr() trong src/cli.py:652
  - Mapping script nằm ở pyproject.toml:35

  Luồng uv run chunk-pipeline

  1. Nhận input_root (mặc định .\input), detect subject/out_root.
  2. Gọi run_e2e_pdf_folder_to_chunked_json():

  - B1: PDF -> TXT bằng Docling + CLIP heading, qua pdfs_to_mirrored_txt() và run_one_pdf() (src/cli.py:180, src/b1_extract/extract_text_and_heading.py:1025)
  - B2: TXT -> JSON raw convert_folder() (src/b2_convert/convert_text_raw_to_json.py:337)
  - B3: semantic chunking process_json_folder() (src/b3_chunk/merge_and_split_json.py:769)
  - B4: merge lessons merge_all_lessons_to_one_json() (src/b4_merge/post_process_json.py:88)

  3. Sau đó B5 _run_export_step(... use_olmocr=False):

  - split lesson theo TOC + extract text bằng pypdfium2
  - zip output (src/cli.py:501, src/b5_export/page_split.py:344, src/b5_export/export_zip.py:149)

  Luồng uv run chunk-pipeline-ocr

  1. Chỉ chạy B5, bỏ qua B1-B4 (src/cli.py:690).
  2. Bắt buộc phải có out_root/_work_tmp/raw_text.txt từ lần chạy trước để parse TOC, nếu thiếu thì exit.
  3. Gọi _run_export_step(... use_olmocr=True).
  4. Trong split_pdf_to_lessons(), nếu use_olmocr=True thì rẽ sang _split_pdf_to_lessons_olmocr():

  - lấy page range từ TOC
  - gọi extract_pages_via_olmocr() qua API server olmOCR
  - convert markdown -> plain text -> ghi lessonN.txt (src/b5_export/page_split.py:438, src/b1_extract/olmocr_extract.py:109)

  Khác biệt cốt lõi

  - chunk-pipeline: tạo mới toàn bộ dữ liệu B1-B5, dùng Docling/pypdfium2 cho extract chuẩn.
  - chunk-pipeline-ocr: không build lại B1-B4; chỉ thay engine extract ở B5 sang olmOCR cho tất cả PDF trong input.
  - OCR mode phù hợp khi font PDF lỗi/garbled khiến pypdfium2 trích text kém.