---
inclusion: auto
---

# Workflow Tổng Thể: Sách Giáo Khoa → DB Teacher

## Bối cảnh
Project này là **một phần** của workflow lớn hơn để đưa nội dung sách giáo khoa lên hệ thống DB Teacher phục vụ giáo viên. Workflow gồm 5 bước, project `chunking_super_hybrid` đảm nhận chủ yếu bước #2 và hỗ trợ bước #4.

## 5 Bước Workflow

### #1. Xác định bộ sách giáo khoa
- Xác định: Môn học, Khối lớp, Bộ sách đang sử dụng
- Output: file PDF sách giáo khoa
- **Trong project**: Ngầm định qua cấu trúc folder `input/<subject>/` và `assets/heading/<bộ sách>/`

### #2. Export sách ra text ⭐ (Core của project này)
- Cắt từng bài trong sách thành file PDF riêng
- Gắn metadata cho từng bài
- Convert PDF → text (workflow gốc dùng olmOCR, project này dùng **Docling + CLIP + pypdfium2**)
- Mỗi sách có cấu trúc khác nhau → cần monitor xử lý trường hợp đặc biệt
- Output: Folder text theo cấu trúc:
```
Tên Môn/
  Lớp X/
    LT/
      lesson1.txt
      lesson2.txt
    TH/
      lesson1.txt
      lesson2.txt
```
- Format text chuẩn:
```
## Topic: Chủ đề 1: ...
## Title: Bài 1: Tên bài
## Heading: Mục tiêu
...
## Heading: Khởi động
...
## Heading: Khám phá
...
## Heading: Thực hành
...
```

### #3. QC Verify & Chuẩn hóa nội dung
- Kiểm tra text metadata khớp với sách PDF gốc
- Kiểm tra format: thêm `##Title`, `##Heading` nếu thiếu
- Input: PDF gốc + PDF cắt bài + folder text output
- Output: Danh sách lỗi + nội dung đã chuẩn hóa
- **Trong project**: Có auto-clean (loại artifact, normalize), có `_failures.json`. Thiếu tool hỗ trợ QC thủ công (so sánh side-by-side).

### #4. Đẩy lesson lên DB Teacher
- Zip từng môn lại
- Upload bằng tool admin
- Nếu chưa có môn → thêm môn mới trong code, build lại, enable qua admin
- Kiểm tra dữ liệu và output
- **Trong project**: `export_zip.py` tạo ZIP đúng format. Upload lên admin tool vẫn là thủ công.

### #5. Flow tổng thể
```
Xác định bộ sách
  ↓
Export PDF → text (Docling/CLIP/pypdfium2)
  ↓
QC Verify & chuẩn hóa nội dung
  ↓
Đẩy lesson lên DB Teacher (admin tool)
```

## Project Coverage Map

| Bước | Mức độ | Ghi chú |
|------|--------|---------|
| #1 Xác định SGK | ✅ Ngầm định | Folder structure + heading assets |
| #2 Export PDF→text | ✅ Đầy đủ | Core pipeline B1→B5 |
| #3 QC Verify | ⚠️ Một phần | Auto-clean có, manual QC tool chưa có |
| #4 Upload DB | ⚠️ Một phần | ZIP tạo tự động, upload vẫn manual |
| #5 Orchestration | ✅ Đầy đủ | `cli.py` điều phối E2E |

## Khác biệt so với workflow gốc
- **OCR**: Workflow gốc dùng olmOCR (server Thành host). Project dùng Docling (no OCR) + CLIP heading detection + pypdfium2 page extraction.
- **Heading detection**: Thay vì OCR nhận diện text heading, project dùng CLIP so khớp ảnh icon heading với prototype embeddings.
- **Chunking cho RAG**: Project mở rộng thêm chunking (B2-B4) phục vụ Qdrant vector DB — phần này nằm ngoài workflow gốc nhưng dùng chung dữ liệu.

## Downstream Systems
- **DB Teacher (CMS)**: Nhận ZIP file lesson → import qua admin tool
- **Qdrant Vector DB**: Nhận chunked JSON → embed dense+sparse → phục vụ RAG/search
