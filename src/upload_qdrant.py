# """
#      start "UPLOAD_QDRANT" /b cmd /c ^ "python src/upload_qdrant.py > logs\run_upload_qdrant_07012026_v0.log 2>&1"   
# """

from __future__ import annotations
import traceback
import os
import re
import json
import time
import uuid
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple

from tqdm import tqdm
from underthesea import word_tokenize

from fastembed.sparse import SparseTextEmbedding
from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import PointStruct
import sys

def _force_utf8_console() -> None:
    # Prefer UTF-8 mode for Python
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # Reconfigure stdout/stderr if supported (Python 3.7+ on most builds)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Even if this fails, we don't want to crash
        pass              
              
_force_utf8_console()

# =========================
# Vietnamese normalize/tokenize (for sparse BM25)
# =========================
_RE_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_RE_SPACES = re.compile(r"\s+", re.UNICODE)

def normalize_vi(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text.lower())
    text = _RE_NON_WORD.sub(" ", text)
    text = _RE_SPACES.sub(" ", text)
    return text.strip()

def safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        # Last-resort fallback
        print(msg.encode("utf-8", "replace").decode("utf-8", "replace"))

_TOKEN_CACHE: Dict[str, str] = {}

def tokenize_vi_cached(text: str, fast: bool = False) -> str:
    """
    fast=False: underthesea word_tokenize (chậm nhưng tốt)
    fast=True : chỉ normalize (nhanh hơn rất nhiều, chất lượng BM25 giảm nhẹ)
    """
    text = normalize_vi(text)
    if not text:
        return ""
    hit = _TOKEN_CACHE.get(text)
    if hit is not None:
        return hit

    if fast:
        tok = text
    else:
        tok = word_tokenize(text, format="text")

    _TOKEN_CACHE[text] = tok
    return tok


# =========================
# CONFIG
# =========================
@dataclass
class Config:
    # Qdrant
    qdrant_url: str = "http://100.65.71.50:6333/"
    collection_prefix: str = ""
    timeout: int = 120

    # Batching
    embed_batch_size: int = 128   # ↓ giảm từ 64 để warmup nhanh hơn (tùy máy tăng lại)
    upsert_batch_size: int = 512

    # Models
    dense_model_path: str = r"E:\QuangNV\QandA_Bank\models\Vietnamese_Embedding"
    dense_dim: int = 1024
    sparse_model_name: str = "Qdrant/bm25"

    # Behavior
    skip_if_collection_exists: bool = True

    # Speed knob
    fast_sparse_tokenize: bool = True  # True = cực nhanh, bỏ underthesea


config = Config()


# =========================
# Qdrant helpers
# =========================
def init_qdrant() -> QdrantClient:
    url = os.getenv("QDRANT_URL", config.qdrant_url).rstrip("/")
    api_key = os.getenv("QDRANT_API_KEY")
    return QdrantClient(url=url, api_key=api_key, timeout=config.timeout)

def wait_for_qdrant(client: QdrantClient, retries: int = 5, delay: int = 3) -> None:
    for attempt in range(1, retries + 1):
        try:
            client.get_collections()
            return
        except Exception as exc:
            if attempt == retries:
                raise SystemExit(
                    f"Cannot reach Qdrant at attempt {attempt}/{retries}: {exc}\n"
                    "Please ensure Qdrant is running and QDRANT_URL is correct."
                )
            print(f"Qdrant not reachable (attempt {attempt}/{retries}): {exc}. Retrying in {delay}s...")
            time.sleep(delay)

def upsert_with_retry(client: QdrantClient, collection_name: str, points: list,
                      retries: int = 3, delay: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            client.upsert(collection_name=collection_name, points=points)
            return
        except Exception as exc:
            if attempt == retries:
                raise
            print(f"Upsert failed (attempt {attempt}/{retries}) for {collection_name}: {exc}. Retrying in {delay}s...")
            time.sleep(delay)

def collection_exists(client: QdrantClient, name: str) -> bool:
    try:
        client.get_collection(name)
        return True
    except Exception:
        return False

def create_collection(client: QdrantClient, name: str) -> None:
    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": models.VectorParams(
                size=config.dense_dim,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=True)
            ),
        },
        on_disk_payload=True,
        shard_number=1,
    )


# =========================
# Model init + embed (BATCH)
# =========================
def init_models():
    # sparse BM25
    sparse = SparseTextEmbedding(model_name=config.sparse_model_name)

    # dense embedding
    dense = HuggingFaceEmbeddings(
        model_name=config.dense_model_path,
        model_kwargs={"local_files_only": True, "trust_remote_code": True},
    )
    return dense, sparse

def embed_texts_batch(
    texts: List[str],
    dense_model,
    sparse_model,
) -> Tuple[List[List[float]], List[models.SparseVector]]:
    # Dense batch
    dense_vecs: List[List[float]] = dense_model.embed_documents(texts)

    # Sparse batch
    sparse_inputs = [tokenize_vi_cached(t, fast=config.fast_sparse_tokenize) for t in texts]
    sparse_embs = list(sparse_model.embed(sparse_inputs))

    sparse_vecs: List[models.SparseVector] = []
    for emb in sparse_embs:
        sparse_vecs.append(
            models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())
        )

    return dense_vecs, sparse_vecs


# =========================
# IO helpers
# =========================
def infer_collection_name(json_path: Path) -> str:
    return f"{config.collection_prefix}{json_path.stem}"

def iter_merged_book_files(input_root: Path) -> List[Path]:
    return sorted(input_root.rglob("*.json"))

def upload_points_fast(client: QdrantClient, collection_name: str, points: List[PointStruct]) -> None:
    """
    Prefer Qdrant client's upload_points (if available). Fallback to upsert.
    """
    if not points:
        return

    # Some versions expose upload_points, some not
    if hasattr(client, "upload_points"):
        # Let client handle batching internally
        client.upload_points(
            collection_name=collection_name,
            points=points,
            batch_size=config.upsert_batch_size,
        )
    else:
        # Fallback to your retry upsert
        upsert_with_retry(client, collection_name, points)

def upload_one_file(jf: str) -> Tuple[str, int]:
    jf = Path(jf)
    collection_name = infer_collection_name(jf)
    try:
        client = init_qdrant()
        wait_for_qdrant(client)

        # init models inside each process
        dense_model, sparse_model = init_models()

        if config.skip_if_collection_exists and collection_exists(client, collection_name):
            safe_print(f"[SKIP] Collection exists: {collection_name} (file: {jf.name})")
            return (collection_name, 0)

        if not collection_exists(client, collection_name):
            safe_print(f"[INFO] Creating collection: {collection_name}")
            create_collection(client, collection_name)

        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            safe_print(f"[SKIP] Cannot read JSON: {jf} ({e})")
            return (collection_name, 0)

        if not isinstance(data, list):
            safe_print(f"[SKIP] JSON is not a list: {jf}")
            return (collection_name, 0)

        buf_texts: List[str] = []
        buf_metas: List[Dict[str, Any]] = []
        points: List[PointStruct] = []
        counter = 0

        def flush_embed_and_upload() -> None:
            nonlocal buf_texts, buf_metas, points, counter

            if not buf_texts:
                return

            dense_vecs, sparse_vecs = embed_texts_batch(buf_texts, dense_model, sparse_model)
            for i in range(len(buf_texts)):
                points.append(
                    PointStruct(
                        id=str(uuid.uuid4()),
                        payload={"metadata": buf_metas[i], "page_content": buf_texts[i]},
                        vector={"dense": dense_vecs[i], "sparse": sparse_vecs[i]},
                    )
                )

            buf_texts, buf_metas = [], []

            # Upload in batches
            if len(points) >= config.upsert_batch_size:
                upload_points_fast(client, collection_name, points)
                counter += len(points)
                points = []

        for it in data:
            if not isinstance(it, dict):
                continue
            page_content = str(it.get("page_content") or "").strip()
            if not page_content:
                continue

            meta = it.get("metadata") or {}
            buf_texts.append(page_content)
            buf_metas.append(meta)

            if len(buf_texts) >= config.embed_batch_size:
                flush_embed_and_upload()

        flush_embed_and_upload()

        if points:
            upload_points_fast(client, collection_name, points)
            counter += len(points)

        safe_print(f"[OK] {collection_name}: upserted {counter} points from {jf.name}")
        return (collection_name, counter)
    except Exception as e:
        # log crash per-file
        crash_dir = Path("logs") / "crashes"
        crash_dir.mkdir(parents=True, exist_ok=True)
        (crash_dir / f"{collection_name}.log").write_text(
            f"FILE: {jf}\nCOLLECTION: {collection_name}\nERROR: {repr(e)}\n\n{traceback.format_exc()}",
            encoding="utf-8"
        )
        raise
def upload_folder_parallel(input_root: str, max_workers: int = 4) -> None:
    in_root = Path(input_root).resolve()
    book_files = iter_merged_book_files(in_root)
    if not book_files:
        print(f"[WARN] No .json files found under: {in_root}")
        return

    # Convert to strings for multiprocessing pickling
    jobs = [str(p) for p in book_files]
    safe_print(f"[INFO] Parallel upload files={len(jobs)} max_workers={max_workers}")

    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed

    ctx = mp.get_context("spawn")  # Windows safe

    ok_total = 0
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
        futs = [ex.submit(upload_one_file, jf) for jf in jobs]
        for fut in as_completed(futs):
            name, cnt = fut.result()
            ok_total += cnt

    safe_print(f"[DONE] Total upserted points: {ok_total}")

# =========================
# Main upload per file -> per collection (FAST + DEBUG)
# =========================
def upload_folder_merged_books_to_qdrant_fast(input_root: str) -> None:
    in_root = Path(input_root).resolve()
    if not in_root.exists():
        raise FileNotFoundError(f"Input folder not found: {in_root}")

    client = init_qdrant()
    wait_for_qdrant(client)

    print("[INFO] Init models ...")
    t0 = time.time()
    dense_model, sparse_model = init_models()
    print(f"[INFO] Init models done in {time.time() - t0:.1f}s")

    book_files = iter_merged_book_files(in_root)
    if not book_files:
        print(f"[WARN] No .json files found under: {in_root}")
        return

    safe_print(f"[INFO] Found {len(book_files)} merged book files under: {in_root}")
    safe_print(f"[INFO] embed_batch_size={config.embed_batch_size} upsert_batch_size={config.upsert_batch_size} fast_sparse_tokenize={config.fast_sparse_tokenize}")

    for jf in book_files:
        collection_name = infer_collection_name(jf)

        if config.skip_if_collection_exists and collection_exists(client, collection_name):
            safe_print(f"[SKIP] Collection exists: {collection_name} (file: {jf.name})")
            continue

        if not collection_exists(client, collection_name):
            safe_print(f"[INFO] Creating collection: {collection_name}")
            create_collection(client, collection_name)

        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            safe_print(f"[SKIP] Cannot read JSON: {jf} ({e})")
            continue

        if not isinstance(data, list):
            safe_print(f"[SKIP] JSON is not a list: {jf}")
            continue

        total = len(data)
        safe_print(f"[INFO] Start upload: {collection_name} items={total} file={jf.name}")

        # buffers
        buf_texts: List[str] = []
        buf_metas: List[Dict[str, Any]] = []
        points: List[PointStruct] = []
        counter = 0

        # progress: update theo batch để giảm overhead
        pbar = tqdm(total=total, desc=f"Upload {collection_name}", unit="item")
        warmed = False

        def flush_embed_and_queue() -> None:
            nonlocal buf_texts, buf_metas, points, counter, warmed

            if not buf_texts:
                return

            if not warmed:
                print("[INFO] Warmup embedding first batch ...")
                tt = time.time()

            dense_vecs, sparse_vecs = embed_texts_batch(buf_texts, dense_model, sparse_model)

            if not warmed:
                safe_print(f"[INFO] Warmup done in {time.time() - tt:.1f}s")
                warmed = True

            for i in range(len(buf_texts)):
                points.append(
                    PointStruct(
                        id=str(uuid.uuid4()),
                        payload={"metadata": buf_metas[i], "page_content": buf_texts[i]},
                        vector={"dense": dense_vecs[i], "sparse": sparse_vecs[i]},
                    )
                )

            buf_texts = []
            buf_metas = []

            if len(points) >= config.upsert_batch_size:
                upload_points_fast(client, collection_name, points)
                counter += len(points)
                points = []

        # iterate
        for it in data:
            # update bar per item read (cheap enough); nếu vẫn muốn nhanh nữa, đổi thành update theo batch size.
            pbar.update(1)

            if not isinstance(it, dict):
                continue

            page_content = str(it.get("page_content") or "").strip()
            if not page_content:
                continue

            meta = it.get("metadata") or {}
            buf_texts.append(page_content)
            buf_metas.append(meta)

            if len(buf_texts) >= config.embed_batch_size:
                flush_embed_and_queue()

        flush_embed_and_queue()

        if points:
            upload_points_fast(client, collection_name, points)
            counter += len(points)
            points = []

        pbar.close()
        safe_print(f"[OK] {collection_name}: upserted {counter} points from {jf.name}")

    print("=== DONE UPLOADING MERGED BOOKS ===")


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    input_root = r"E:\QuangNV\Chunking_Final\z\chunking_super_hybrid\outputs\chunking_08012026_v0\04_dataset_09012026"
    # upload_folder_merged_books_to_qdrant_fast(input_root)
    upload_folder_parallel(input_root, max_workers=1)
