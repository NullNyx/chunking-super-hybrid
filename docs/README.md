# Pipeline Chunking PDF -> JSON -> Qdrant

## Muc dich
- Lay noi dung PDF, chen heading tu anh, chuan hoa, chia nho, gop bai hoc.
- Xuat du lieu san sang index Qdrant (dense + sparse).

## Thanh phan chinh
- `main.py`: dieu phoi E2E 4 buoc.
- `src/extract_text_and_heading.py`: Docling (khong OCR) -> markdown + anh; CLIP gan nhan anh tu `assets/prototypes_heading.pt`; thay anh bang `## Heading: ...`; xuat `raw_with_headings.txt`.
- `src/convert_text_raw_to_json.py`: doi `.txt` co heading thanh `.json` chunk tho, sinh metadata (subject, kb_id, lesson, chunk_id, length, token...).
- `src/merge_and_split_json.py`: cat nho theo don vi ngu nghia/token (target ~400, max ~650, overlap 2 cau), giu heading chinh/phu, them reference; gop bai theo `subject/kb_folder/types`.
- `src/post_process_json.py`: gop tat ca lesson thanh 1 file, cap nhat version, tuy chon bo bot metadata.
- `src/upload_qdrant.py`: embed dense + sparse va upsert len Qdrant.
- `assets/`: checkpoint CLIP + mapping nhan -> heading; thu muc minh hoa heading.
- `outputs/`: ket qua theo phien ban.

## Cay buoc tong quat
```
Pipeline (main.py)
├─ B1: PDF -> TXT co heading
│  └─ Docling tach text + anh, CLIP gan nhan anh, chen "## Heading:"
├─ B2: TXT -> JSON tho
│  └─ Cat theo heading, tao metadata co ban
├─ B3: Chunk nho + overlap
│  └─ Chia theo y nghia/token, giu heading chinh/phu, them reference
├─ B4: Gop bai hoc
│  └─ Gom subject/lop/loai, sap xep, them global_order
└─ (Tuy chon) Upload Qdrant
   └─ Embed dense+sparse, upsert batch
```

## Chi tiet chunking (B3)
- Phan heading: main vs sub; danh sach heading "no-split" (vd. "Ghi nho") luon giu nguyen khoi.
- Subheading/dan nhap duoc nhap ve heading truoc de khong vo manh context.
- Don vi cat: uu tien khoi nghia (bullet/so/La Ma/case) truoc; chi fallback tach cau khi khong con cau truc.
- Token guard: muc tieu ~400, tran 650; neu mot unit vuot tran thi cat mem theo cau/tu.
- Overlap: 2 cau cuoi (co gioi han token) de giu mach khi truy van/LLM.
- Thu tu & truy vet: them `heading_path`, `heading_join`, `subchunk_index`, `global_order`, `reference` de biet sach/lop/bai va dung thu tu khi hien thi.

## Logic chi tiet theo buoc
```
Pipeline (main.py)
├─ B1: PDFs -> TXT co heading goc (pdfs_to_mirrored_txt)
│  ├─ Song song nhieu PDF (ProcessPoolExecutor; neu GPU thi giam max_workers=1)
│  ├─ Docling khong OCR => text sach, anh tach rieng
│  ├─ CLIP + prototypes_heading.pt => gan nhan anh, map sang heading TV
│  └─ Thay anh bang heading => text giu cau truc, giam phu thuoc layout PDF
├─ B2: TXT -> JSON tho (convert_folder)
│  ├─ Tach theo "## Heading:"; subheading/dan nhap nhap ve heading gan nhat
│  └─ Metadata tu path (subject/lop/loai) + lesson + chunk_id (SHA1) de truy vet
├─ B3: Chunking + overlap (process_json_folder)
│  ├─ Cat theo don vi ngu nghia (bullet/so/La Ma/case), sau do dieu chinh token ~400, tran 650
│  ├─ Overlap 2 cau duoi; tranh tach heading "no-split"
│  ├─ Them heading_path/heading_join, subchunk_index, global_order, reference
│  └─ Ghi 03_chunked_raw
├─ B4: Gop lessons (merge_all_lessons_to_one_json)
│  ├─ Gom theo subject/kb_folder/types, sort lesson + chunk_order + subchunk_index
│  └─ Cap nhat chunk_version=merged_out_version; mot file/nhom de nap downstream
└─ Upload Qdrant (tuy chon) (upload_qdrant.py)
   ├─ Tu tao collection dense+sparse neu chua co (HuggingFace dense + BM25 sparse)
   ├─ Tokenize TV (underthesea hoac fast normalize) cho sparse
   └─ Upsert batch + retry; collection_prefix ho tro versioning
```

## Chay mau (trong `main.py`)
```bash
python main.py
# hoac chay nen kem log:
# start "RUN_CHUNKING" /b cmd /c ^
#   "python main.py > logs\run_chunk_08012026_v0.log 2>&1"
```
Tham so chinh (doi trong `run_e2e_pdf_folder_to_chunked_json`):
- `input_pdfs_root`, `out_root`
- `prototypes_path`, `labels_heading_json`
- `n_pages`, `test_fast`, `clip_score_threshold`, `clip_device`, `label_mode`
- Chunking: `min_tokens`, `target_tokens`, `max_tokens`, `overlap_units`, `chunk_version`

## Upload Qdrant (tom tat)
- `Config`: `qdrant_url`, `collection_prefix`, model dense `Vietnamese_Embedding`, sparse `Qdrant/bm25`, batch size embed/upsert.
- Chay nen:
```bash
# start "UPLOAD_QDRANT" /b cmd /c ^
#   "python src/upload_qdrant.py > logs/run_upload_qdrant_07012026_v0.log 2>&1"
```
- Tu kiem tra ket noi, tao collection, embed batch, upsert batch voi retry.

## Dau vao / Dau ra
- Input: PDF dat theo `subject/kb_folder/types/*.pdf` de auto suy metadata (vd. `htlt/Lop1/general/lesson4.pdf`).
- Output:
  - `01_extract_txt_raw/<...>.txt` + `_stats.json`, `_failures.json`, `_timings.json`.
  - `02_convert_json_raw/<...>.json`: chunk tho theo heading.
  - `03_chunked_raw/<...>.json`: chunk da cat nho, co overlap + reference.
  - `04_merged_all/<subject>_<kb>_<types>_<ver>.json`: san sang index.

## Meo van hanh
- GPU: dat `clip_device="cuda"`, `pdf_max_workers=1`.
- Kiem tra `assets/prototypes_heading.pt` va `assets/labels_heading.json` truoc khi chay.
- Xem `_failures.json` de retry PDF loi.
- Test nhanh: `n_pages` nho, `test_fast=True`, `cleanup_work=True` de don thu muc tam.
