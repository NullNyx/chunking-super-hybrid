from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode
from functools import lru_cache

@lru_cache(maxsize=2)
def _get_clip_bundle(device: str):
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device).eval()
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    return model, processor


# =========================================================
# 0) Regex / constants
# =========================================================

# Match markdown image: ![alt](path)
IMG_MD_RE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

# Docling sometimes writes these HTML comments for images
DOCLING_IMG_COMMENT_RE = re.compile(r"<!--\s*Image\s*-->\s*", flags=re.IGNORECASE)
DOCLING_IMG_MISSING_RE = re.compile(
    r"<!--\s*🖼️❌\s*Image not available\..*?-->",
    flags=re.DOTALL,
)

# Try to detect page markers in markdown to slice first N pages (optional)
PAGE_MARKERS = [
    re.compile(r"^\s*---\s*Page\s+(\d+)\s*---\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*<!--\s*Page\s+(\d+)\s*-->\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*#\s*Page\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE),
]

# Remove ALL markdown headings (##, ###, ...) except your inserted "## Heading:"
OTHER_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?!Heading:)", re.MULTILINE)

# Convert "/uni1EBF" like tokens to actual unicode chars
_UNI_HEX_RE = re.compile(r"/uni([0-9a-fA-F]{4,6})")


# =========================================================
# 1) Text normalization / cleaning helpers
# =========================================================

def fix_uni_glyphs(text: str) -> str:
    """Convert '/uniXXXX' tokens into real unicode characters (best-effort)."""
    def repl(m: re.Match) -> str:
        cp = int(m.group(1), 16)
        try:
            return chr(cp)
        except ValueError:
            return m.group(0)

    return _UNI_HEX_RE.sub(repl, text)


def normalize_weird_case(text: str) -> str:
    """
    Reduce random casing noise:
      - Keep short acronyms (<=5 chars) uppercase
      - If token contains mixed upper+lower => Title-case it
    """
    def fix_tok(tok: str) -> str:
        if not tok or tok.isspace():
            return tok
        if tok.isupper() and len(tok) <= 5:
            return tok

        letters = [c for c in tok if c.isalpha()]
        if not letters:
            return tok

        has_upper = any(c.isupper() for c in letters)
        has_lower = any(c.islower() for c in letters)
        if has_upper and has_lower:
            low = tok.lower()
            return low[:1].upper() + low[1:] if len(low) > 1 else low

        return tok

    parts = re.split(r"(\s+)", text)
    return "".join(fix_tok(p) if not p.isspace() else p for p in parts)


def fix_weird_vietnamese_glyph_noise(text: str) -> str:
    """
    Fix specific broken Vietnamese glyphs you observed in your dataset.

    IMPORTANT:
      - This is project-specific mapping (extend over time).
      - Must return the modified text.
    """
    text = unicodedata.normalize("NFC", text)

    # dataset mappings
    text = text.replace("𞼜", "ực")
    text = text.replace("𞻺", "ữa")
    text = text.replace("𞼚", "ựa")
    text = text.replace("𞫼", "ắc")

    # extra mappings you found
    text = text.replace("", "*")
    text = text.replace("𞼌", "ực")

    # cleanup stray combining acute accent if it appears alone
    text = text.replace("\u0301", "")
    return text


def strip_docling_comments(md: str) -> str:
    """Remove docling image comments / missing-image blocks."""
    md = DOCLING_IMG_MISSING_RE.sub("", md)
    md = DOCLING_IMG_COMMENT_RE.sub("", md)
    return md


def md_keep_image_links(md: str) -> str:
    """
    Keep markdown (including ![](...)) but:
      - remove docling comments
      - fix uni tokens and Vietnamese glyph noise
      - normalize casing
      - compact extra blank lines
    """
    md = strip_docling_comments(md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    md = fix_uni_glyphs(md)
    md = fix_weird_vietnamese_glyph_noise(md)
    md = normalize_weird_case(md)
    return md

def safe_stem_for_windows(p: Path) -> str:
    s = p.stem.rstrip(" .")   # Windows không cho stem kết thúc bằng space/dot
    return s if s else "file"

def md_to_raw_text(md: str) -> str:
    """
    Convert markdown -> raw text (no OCR):
      - remove code fences
      - remove image tags
      - keep link text
      - remove markdown headings markers
      - remove bold/italic markers
      - compact whitespace
      - apply normalization fixes
    """
    md = strip_docling_comments(md)

    md = re.sub(r"```.*?```", "", md, flags=re.DOTALL)            # code blocks
    md = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", md)                 # images
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)             # links -> text
    md = re.sub(r"^\s*#{1,6}\s+", "", md, flags=re.MULTILINE)    # markdown headings
    md = md.replace("**", "").replace("__", "").replace("*", "").replace("_", "")
    md = re.sub(r"^\s*[-*]\s+", "", md, flags=re.MULTILINE)      # bullets
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    md = fix_uni_glyphs(md)
    md = fix_weird_vietnamese_glyph_noise(md)
    md = normalize_weird_case(md)
    return md


def compact_newlines(text: str) -> str:
    """Normalize line endings and collapse 3+ newlines -> 2 newlines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join([ln.rstrip() for ln in text.split("\n")])
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def normalize_my_headings(text: str) -> str:
    """
    Ensure your inserted headings appear as blocks:
      blank line before + blank line after
    Normalize heading format to: '## Heading: X'
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []

    for line in lines:
        m = re.match(r"^\s*##\s*Heading:\s*(.+?)\s*$", line)
        if m:
            heading = m.group(1).strip()
            if out and out[-1].strip() != "":
                out.append("")
            out.append(f"## Heading: {heading}")
            out.append("")
        else:
            out.append(line)

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def compact_paragraphs_keep_lists_and_headings(text: str) -> str:
    """
    Remove empty lines between normal text lines,
    but preserve spacing around your '## Heading:' blocks.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def is_heading(line: str) -> bool:
        return line.startswith("## Heading:")

    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if is_heading(line):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(line)
            out.append("")
            i += 1
            continue

        if line.strip() == "":
            prev = out[-1] if out else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if prev.strip() != "" and not is_heading(prev) and nxt.strip() != "" and not is_heading(nxt):
                i += 1
                continue
            out.append("")
            i += 1
            continue

        out.append(line)
        i += 1

    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# =========================================================
# 2) Docling extraction (no OCR) -> markdown + images list
# =========================================================

def slice_markdown_first_n_pages(md_text: str, n_pages: int) -> Tuple[str, bool]:
    """Try slicing by page markers in markdown. Returns (slice, used_markers)."""
    matches = []
    for pat in PAGE_MARKERS:
        for m in pat.finditer(md_text):
            matches.append((m.start(), int(m.group(1))))

    if not matches:
        return md_text, False

    matches.sort(key=lambda x: x[0])
    start_pos = matches[0][0]  # start from first marker

    # Find end position at page n_pages
    end_pos = None
    for idx, (pos, page) in enumerate(matches):
        if page == n_pages:
            end_pos = matches[idx + 1][0] if idx + 1 < len(matches) else len(md_text)
            break

    if end_pos is None:
        end_pos = len(md_text)

    return md_text[start_pos:end_pos], True


def fallback_slice_by_chars(md_text: str, n_pages: Optional[int]) -> str:
    """Fallback slicing when page markers are missing; used only for quick tests."""
    if not n_pages or n_pages <= 0:
        return md_text
    return md_text[: n_pages * 6000]


def resolve_md_image_path(md_dir: Path, rel_path: str) -> Path:
    """Resolve image relative path inside markdown to absolute Path."""
    p = rel_path.strip().strip('"').strip("'").replace("\\", os.sep).replace("/", os.sep)
    p = os.path.normpath(p)
    return (md_dir / p).resolve()


@dataclass
class ExtractResult:
    """All outputs from docling extraction step."""
    md_path: str
    docling_dir: str
    artifacts_dir: str
    raw_text: str
    raw_with_images: str
    images: List[Dict[str, Any]]
    used_page_markers: bool


def extract_pdf_no_ocr(
    pdf_path: Union[str, Path],
    *,
    n_pages: Optional[int],
    out_dir: Union[str, Path],
    test_fast: bool = True,
    keep_docling_dir: bool = True,
) -> ExtractResult:
    """
    Convert PDF -> docling markdown (no OCR), keep referenced images, produce:
      - raw_text            : plain text (no image tags)
      - raw_with_images     : markdown-like text with ![](...) links kept
      - images              : list of referenced images in the sliced markdown
      - artifacts_dir       : where docling stores referenced images
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    docling_dir = (out_dir / "_docling").resolve()
    docling_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = safe_stem_for_windows(pdf_path)
    md_path = (docling_dir / f"{safe_stem}.md").resolve()
    artifacts_dir = (docling_dir / f"{safe_stem}_artifacts").resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Docling pipeline options (NO OCR)
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 1.2 if test_fast else 2.0
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    res = converter.convert(pdf_path)
    doc = res.document

    # Important: pass artifacts_dir explicitly to avoid path duplication bugs
    doc.save_as_markdown(
        md_path,
        artifacts_dir=artifacts_dir,
        image_mode=ImageRefMode.REFERENCED,
    )

    md_full = md_path.read_text(encoding="utf-8", errors="ignore")

    # Slice pages (optional)
    if not n_pages or n_pages <= 0:
        md_slice = md_full
        used_markers = False
    else:
        md_slice, used_markers = slice_markdown_first_n_pages(md_full, n_pages=n_pages)
        if not used_markers:
            md_slice = fallback_slice_by_chars(md_full, n_pages=n_pages)

    raw_text = md_to_raw_text(md_slice)
    raw_with_images = md_keep_image_links(md_slice)

    # Build images list: only images referenced in markdown slice
    images: List[Dict[str, Any]] = []
    seen: set[str] = set()
    md_dir = md_path.parent

    for m in IMG_MD_RE.finditer(md_slice):
        rel = m.group(1).strip()
        abs_src = resolve_md_image_path(md_dir, rel)
        key = str(abs_src)
        if key in seen:
            continue
        seen.add(key)

        images.append({
            "image_path_rel_in_md": rel,
            "image_path_abs": str(abs_src),
            "exists": abs_src.exists(),
        })

    if not keep_docling_dir:
        shutil.rmtree(docling_dir, ignore_errors=True)

    return ExtractResult(
        md_path=str(md_path),
        docling_dir=str(docling_dir),
        artifacts_dir=str(artifacts_dir),
        raw_text=raw_text,
        raw_with_images=raw_with_images,
        images=images,
        used_page_markers=used_markers,
    )


# =========================================================
# 3) CLIP heading detection
# =========================================================

def pad_to_square(img: Image.Image, fill=(255, 255, 255)) -> Image.Image:
    """Pad image to square to reduce shape bias for CLIP."""
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), fill)
    canvas.paste(img, ((s - w) // 2, (s - h) // 2))
    return canvas


def load_prototypes(prototypes_path: Union[str, Path]) -> Tuple[List[str], torch.Tensor]:
    """
    Load prototypes from .pt.
    Expected format: dict[label -> 1D embedding tensor]
    Return:
      labels: list[str]
      mat:   Tensor [C, D] normalized (cosine-ready), on CPU
    """
    protos: Dict[str, torch.Tensor] = torch.load(str(prototypes_path), map_location="cpu")
    labels = list(protos.keys())
    mat = torch.stack([protos[l] for l in labels], dim=0)  # [C, D]
    mat = F.normalize(mat, dim=1)
    return labels, mat

@lru_cache(maxsize=8)
def _get_prototypes_cached(prototypes_path: str):
    labels, mat = load_prototypes(prototypes_path)
    return labels, mat

@torch.inference_mode()
def predict_label_for_image(
    image_path: Union[str, Path],
    *,
    model: CLIPModel,
    processor: CLIPProcessor,
    labels: List[str],
    proto_mat_cpu: torch.Tensor,
    device: str,
) -> Tuple[str, float]:
    """Compute CLIP image embedding and cosine to prototypes. Return (best_label, score)."""
    img = Image.open(image_path).convert("RGB")
    img = pad_to_square(img)

    inputs = processor(images=[img], return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    feat = model.get_image_features(**inputs)
    feat = F.normalize(feat, dim=1)[0].cpu()  # [D] on CPU

    sims = proto_mat_cpu @ feat  # [C]
    best_idx = int(torch.argmax(sims).item())
    return labels[best_idx], float(sims[best_idx].item())


@dataclass(frozen=True)
class ClipHit:
    """One detected heading icon match."""
    image_path: str
    label: str
    score: float


def clip_label_images(
    image_paths: List[Path],
    *,
    prototypes_path: Union[str, Path],
    score_threshold: float = 0.9,
    device: Optional[str] = None,
) -> List[ClipHit]:
    """
    Label images by CLIP cosine similarity with prototype embeddings.
    Only keep hits >= score_threshold.
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    labels, proto_mat_cpu = _get_prototypes_cached(str(Path(prototypes_path).resolve()))
    model, processor = _get_clip_bundle(device)

    hits: List[ClipHit] = []
    for p in image_paths:
        try:
            label, score = predict_label_for_image(
                p,
                model=model,
                processor=processor,
                labels=labels,
                proto_mat_cpu=proto_mat_cpu,
                device=device,
            )
            if score >= score_threshold:
                hits.append(ClipHit(image_path=str(p), label=label, score=score))
        except Exception:
            # Ignore broken images
            continue

    return hits


def export_hits_tsv(hits: List[ClipHit], out_path: Path) -> None:
    """Write clip hits to TSV: image_path \\t label \\t score."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("image_path\tlabel\tscore\n")
        for h in hits:
            f.write(f"{h.image_path}\t{h.label}\t{h.score:.6f}\n")


def load_labels_to_heading(labels_json_path: Union[str, Path]) -> Dict[str, str]:
    """
    Đọc configs/labels.json và trả về mapping:
        { "khoi_dong": "Khởi động", ... }

    Expected JSON format:
    {
      "labels_to_heading": {
        "khoi_dong": "Khởi động",
        ...
      }
    }
    """
    p = Path(labels_json_path)
    if not p.exists():
        raise FileNotFoundError(f"labels.json not found: {p}")

    data = json.loads(p.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("labels.json must be a JSON object at top-level")

    mapping = data.get("labels_to_heading")
    if mapping is None:
        raise KeyError("labels.json missing key: 'labels_to_heading'")

    if not isinstance(mapping, dict):
        raise TypeError("'labels_to_heading' must be an object/dict")

    # normalize keys (optional): strip + lower để match label_to_display
    out: Dict[str, str] = {}
    for k, v in mapping.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        out[k.strip().lower()] = v.strip()

    return out

# =========================================================
# 4) Inject headings back into markdown text
# =========================================================

# def label_to_display(label: str, path_labels_heading: str) -> str:
#     """
#     Convert internal label to human heading text.
#     Example: 'htlt_thuc_hanh' -> 'Thực hành'
#     Extend mapping as needed.
#     """
#     label = label.strip().lower()

#     # remove subject prefixes
#     for p in ["htlt_", "vhnt_", "ttnt_", "sd_"]:
#         if label.startswith(p):
#             label = label[len(p):]
#             break

#     # remove level prefixes
#     if label.startswith("lt_"):
#         label = label[len("lt_"):]
#     if label.startswith("th_"):
#         label = label[len("th_"):]

#     special = load_labels_to_heading(path_labels_heading)
#     if label in special:
#         return special[label]

#     # fallback: split by underscore and Title-Case
#     words = label.split("_")
#     return " ".join(w.capitalize() for w in words if w)


def load_label_tsv_map(label_path: Union[str, Path]) -> Dict[str, str]:
    """
    Read TSV (image_path \\t label \\t score) and return mapping:
      { basename(image_path) -> label }
    This allows matching both referenced and artifacts modes as long as filenames match.
    """
    p = Path(label_path)
    mapping: Dict[str, str] = {}

    for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines()):
        line = line.strip()
        if not line:
            continue
        if i == 0 and "label" in line.lower():
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        image_path = parts[0].strip()
        label = parts[1].strip()
        if image_path and label:
            mapping[Path(image_path).name] = label

    return mapping


def inject_headings(
    *,
    label_tsv_path: Union[str, Path],
    text_with_images: str,
    path_labels_heading: Union[str, Path],
    drop_unlabeled_images: bool = True,
) -> Tuple[str, int, int]:
    """
    Replace markdown image tags with '## Heading: ...' when the image filename has a label.

    Returns:
      out_text, num_inserted, num_dropped
    """
    label_map = load_label_tsv_map(label_tsv_path)
    inserted = 0
    dropped = 0
    special = load_labels_to_heading(path_labels_heading)

    def label_to_display_fast(label: str) -> str:
        lb = label.strip().lower()
        for p in ["htlt_", "vhnt_", "ttnt_", "sd_"]:
            if lb.startswith(p):
                lb = lb[len(p):]
                break
        if lb.startswith("lt_"):
            lb = lb[3:]
        if lb.startswith("th_"):
            lb = lb[3:]
        if lb in special:
            return special[lb]
        return " ".join(w.capitalize() for w in lb.split("_") if w)
    def repl(m: re.Match) -> str:
        nonlocal inserted, dropped
        img_path = m.group(1).strip()
        filename = Path(img_path).name

        label = label_map.get(filename)
        if not label:
            if drop_unlabeled_images:
                dropped += 1
                return ""
            return m.group(0)

        inserted += 1
        display = label_to_display_fast(label)
        return f"\n\n## Heading: {display}\n\n"

    text = IMG_MD_RE.sub(repl, text_with_images)

    # Remove other markdown headings to avoid interference
    text = OTHER_MD_HEADING_RE.sub("", text)

    # Compact formatting
    text = compact_newlines(text)
    text = compact_paragraphs_keep_lists_and_headings(text)
    text = normalize_my_headings(text)
    text = fix_weird_vietnamese_glyph_noise(text)
    return text, inserted, dropped


# =========================================================
# 5) One-shot pipeline: PDF -> raw_text + raw_with_headings
# =========================================================

def collect_images_for_clip(
    *,
    ex: ExtractResult,
    pdf_path: Union[str, Path],
    label_mode: str,
) -> List[Path]:
    """
    Decide which images to run CLIP on.

    label_mode:
      - 'referenced': only images referenced in markdown slice (recommended for injection)
      - 'artifacts' : all images in docling artifacts folder (can be noisy)
    """
    if label_mode not in ("referenced", "artifacts"):
        raise ValueError("label_mode must be 'referenced' or 'artifacts'")

    if label_mode == "referenced":
        return [Path(x["image_path_abs"]) for x in ex.images if x.get("exists")]

    # artifacts mode: use the exact artifacts folder for this PDF
    artifacts_dir = Path(ex.artifacts_dir)
    if not artifacts_dir.exists():
        return []

    exts = (".png", ".jpg", ".jpeg", ".webp")
    return [p for p in artifacts_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]


def run_one_pdf(
    pdf_path: Union[str, Path],
    *,
    out_dir: Union[str, Path],
    prototypes_path: Union[str, Path],
    n_pages: Optional[int] = None,
    test_fast: bool = True,
    keep_docling_dir: bool = True,
    clip_score_threshold: float = 0.9,
    path_labels_heading: Union[str, Path],
    clip_device: Optional[str] = None,
    drop_unlabeled_images: bool = True,
    label_mode: str = "referenced",
) -> Dict[str, Any]:
    """
    End-to-end:
      1) docling extract (no OCR) -> raw_text + raw_with_images + images.json
      2) choose images -> CLIP label -> labels.tsv + clip_hits.json
      3) inject headings into raw_with_images -> raw_with_headings.txt
      4) write meta.json
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # (1) Extract
    ex = extract_pdf_no_ocr(
        pdf_path,
        n_pages=n_pages,
        out_dir=out_dir,
        test_fast=test_fast,
        keep_docling_dir=keep_docling_dir,
    )

    (out_dir / "raw_text.txt").write_text(ex.raw_text, encoding="utf-8")
    (out_dir / "raw_with_images.txt").write_text(ex.raw_with_images, encoding="utf-8")
    (out_dir / "images.json").write_text(json.dumps(ex.images, ensure_ascii=False, indent=2), encoding="utf-8")

    # (2) CLIP labeling
    image_paths = collect_images_for_clip(ex=ex, pdf_path=pdf_path, label_mode=label_mode)

    hits = clip_label_images(
        image_paths,
        prototypes_path=prototypes_path,
        score_threshold=clip_score_threshold,
        device=clip_device,
    )

    labels_tsv_path = out_dir / "labels.tsv"
    clip_hits_path = out_dir / "clip_hits.json"
    export_hits_tsv(hits, labels_tsv_path)
    clip_hits_path.write_text(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2), encoding="utf-8")

    # (3) Inject headings
    final_text, inserted, dropped = inject_headings(
        label_tsv_path=labels_tsv_path,
        text_with_images=ex.raw_with_images,
        path_labels_heading=path_labels_heading,
        drop_unlabeled_images=drop_unlabeled_images,
    )
    (out_dir / "raw_with_headings.txt").write_text(final_text, encoding="utf-8")

    # (4) Meta
    meta = {
        "pdf": str(pdf_path),
        "out_dir": str(out_dir),
        "n_pages_requested": n_pages,
        "page_slicing_used_markers": ex.used_page_markers,
        "docling_markdown_path": ex.md_path,
        "docling_dir": ex.docling_dir,
        "artifacts_dir": ex.artifacts_dir,
        "label_mode": label_mode,
        "prototypes_path": str(prototypes_path),
        "clip_score_threshold": clip_score_threshold,
        "clip_num_hits": len(hits),
        "num_headings_inserted": inserted,
        "num_images_dropped": dropped,
        "drop_unlabeled_images": drop_unlabeled_images,
        "test_fast": test_fast,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# =========================================================
# 6) Example run
# =========================================================
if __name__ == "__main__":
    meta = run_one_pdf(
        pdf_path=r"E:\QuangNV\Matching_book_logic\GDCD\CDHT GDKTPL 12 CTST (Ruot ITB 17.02.25).pdf",
        out_dir=r"E:\QuangNV\Matching_book_logic\GDCD_export",
        prototypes_path=r"E:\AIBuddy\dev2\v1\book-chunking\chunking_super_hybrid\assets\prototypes_heading.pt",
        n_pages=None,
        test_fast=True,
        keep_docling_dir=True,
        clip_score_threshold=0.9,
        path_labels_heading=r"E:\AIBuddy\dev2\v1\book-chunking\chunking_super_hybrid\assets\labels_heading.json",
        clip_device=None,
        drop_unlabeled_images=True,
        label_mode="artifacts",   # change to "referenced" if you want tighter mapping for injection
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))
