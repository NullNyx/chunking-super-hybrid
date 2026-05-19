---
inclusion: auto
---

# Project: Chunking Super Hybrid

## Mục đích
Pipeline tự động chuyển đổi PDF sách giáo khoa tiếng Việt → file `.txt` theo từng bài học, sẵn sàng import vào hệ thống CMS giáo dục.

## Input
- PDF sách giáo khoa đặt trong `input/<subject>/` (ví dụ `input/toan/Toan_3_Tap_1-6.3.25.pdf`)
- Tên file chứa thông tin: `{Subject}_{Grade}_Tap_{Volume}-{date}.pdf`

## Output mong muốn
ZIP file chứa cấu trúc:
```
subject/Lop{grade}_{volume}/LT/lesson{N}.txt
```
Ví dụ: `toan/Lop3_1/LT/lesson1.txt`

Mỗi file `.txt` có format:
```
##Title: Bài {N}. {Tên bài}\r\n
\r\n
{Nội dung bài học - plain text, CRLF}\r\n
```

## Pipeline (5 bước)

### B1: PDF → Raw Text + CLIP Heading Detection
- **Docling** (no OCR) extract text + images từ PDF
- **CLIP** (CUDA fp16 batch) phân loại heading icons (Khởi động, Khám phá, Ghi nhớ...)
- Inject `## Heading:` markers vào text
- Output: `01_extract_txt_raw/`, `_work_tmp/`

### B2: Raw Text → JSON chunks thô
- Tách theo `## Heading:` markers
- Parse metadata (subject, grade, types, lesson number)
- Output: `02_convert_json_raw/`

### B3: Chunking + Overlap
- Chia nhỏ theo semantic units, target ~400 tokens, max 650
- Overlap 2 câu cuối
- Output: `03_chunked_raw/`

### B4: Merge lessons
- Gộp theo subject/grade/types
- Output: `04_merged_all/`

### B5: Page-based Lesson Splitting + ZIP Export (CHÍNH)
- **pypdfium2** extract text theo từng trang
- Parse mục lục (TOC) → mapping `{lesson: start_page}`
- Split content theo page range → mỗi bài = 1 file `.txt`
- Clean noise: page numbers, chapter headers, duplicate titles, sidebar labels
- Export ZIP đúng format CMS
- Output: `05_export/txt/`, `05_export/{subject}.zip`

## Lệnh chạy
```powershell
uv run chunk-pipeline          # Chạy full B1→B5
uv run chunk-check-env         # Kiểm tra môi trường
uv run chunk-export            # Chỉ chạy B5 (nếu B1-B4 đã có)
```

## Cấu trúc code chính
- `src/cli.py` — Entry point, điều phối pipeline
- `src/extract_text_and_heading.py` — B1: Docling + CLIP
- `src/convert_text_raw_to_json.py` — B2: Text → JSON
- `src/merge_and_split_json.py` — B3: Chunking
- `src/post_process_json.py` — B4: Merge
- `src/page_split.py` — B5: Page-based split + clean + export
- `src/export_zip.py` — ZIP creation
- `src/olmocr_extract.py` — olmOCR server client (cho PDF font lỗi)
- `src/upload_qdrant.py` — Optional: upload Qdrant
- `src/check_env.py` — Kiểm tra môi trường
- `main.py` — Thin shim (import src.cli)

## Môi trường
- Python 3.11, uv managed
- torch 2.6.0+cu124 (RTX 3050)
- Docling 2.31.0, CLIP openai/clip-vit-base-patch32
- pypdfium2 cho page-level text extraction

## TOC Parser
Hỗ trợ 2 format mục lục:
1. **Bảng** (lớp 3-5, 7-9): `| Bài X. Title | page |`
2. **Plain text** (lớp 6): `Bài X. Title` + page number dòng sau

## Clean Rules (B5)
- Xoá standalone page numbers (dòng chỉ chứa số)
- Xoá section headers lặp (Khám phá, luyện tập, Chủ đề...)
- Xoá duplicate title trong body
- Xoá chapter headers viết HOA ở đầu bài
- Collapse blank lines (max 1 dòng trống)

## Lưu ý quan trọng
- `overwrite_txt=False` → B1 skip PDF đã xử lý (chạy lại nhanh)
- B5 luôn ghi đè → sửa code rồi chạy lại là đủ
- `clip_device="cuda"` + `pdf_max_workers=1` (tránh deadlock Windows)
- SSL fix: `_ensure_ssl_ca_bundle()` cho Windows
- `default_types="LT"` — tất cả sách hiện tại là Lý thuyết
