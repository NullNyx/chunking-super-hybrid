import json
from pathlib import Path
from typing import Dict, List

import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPProcessor, CLIPModel


def pad_to_square(img: Image.Image, fill=(255, 255, 255)) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), fill)
    canvas.paste(img, ((s - w)//2, (s - h)//2))
    return canvas


@torch.inference_mode()
def embed_images(model, processor, image_paths: List[Path], device: str) -> torch.Tensor:
    imgs = []
    for p in image_paths:
        im = Image.open(p).convert("RGB")
        im = pad_to_square(im)
        imgs.append(im)

    inputs = processor(images=imgs, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    feats = model.get_image_features(**inputs)
    feats = F.normalize(feats, dim=1)
    return feats


def build_and_save_prototypes_subject_prefixed(
    dataset_heading_dir: str,
    out_path: str = "prototypes_heading.pt",
    out_labels_path: str = "labels.json",
    device: str = "cuda",
):
    """
    dataset_heading/
      htlt/muc_tieu.png  -> label = "htlt_muc_tieu"
      sd/muc_tieu.png    -> label = "sd_muc_tieu"
    """
    root = Path(dataset_heading_dir)
    label_to_paths: Dict[str, List[Path]] = {}

    # each subject folder => prefix in label
    for subject_dir in root.iterdir():
        if not subject_dir.is_dir():
            continue

        subject = subject_dir.name.lower().strip()

        for img_path in subject_dir.glob("*.png"):
            stem = img_path.stem.lower().strip()
            label = f"{subject}_{stem}"
            label_to_paths.setdefault(label, []).append(img_path)

    if not label_to_paths:
        raise ValueError("No PNG files found under dataset_heading_dir")

    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device).eval()
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    prototypes: Dict[str, torch.Tensor] = {}
    for label, paths in label_to_paths.items():
        feats = embed_images(model, processor, paths, device=device)  # [n, d]
        proto = feats.mean(dim=0, keepdim=True)
        proto = F.normalize(proto, dim=1)[0].detach().cpu()
        prototypes[label] = proto

    torch.save(prototypes, out_path)

    labels_sorted = sorted(prototypes.keys())
    Path(out_labels_path).write_text(
        json.dumps(labels_sorted, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"✅ Saved prototypes: {out_path} ({len(labels_sorted)} labels)")
    print(f"✅ Saved labels: {out_labels_path}")
    print("Total labels:", len(labels_sorted))
    print("Sample labels:", labels_sorted[:10])


if __name__ == "__main__":
    build_and_save_prototypes_subject_prefixed(
        dataset_heading_dir=r"./assets/heading",
        out_path=r"./assets/prototypes_heading.pt",
        out_labels_path=r"./assets/labels.json",
        device="cuda" if torch.cuda.is_available() else "cpu",
    )