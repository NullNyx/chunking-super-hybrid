import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

def pad_to_square(img: Image.Image, fill=(255,255,255)) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    canvas = Image.new("RGB", (s, s), fill)
    canvas.paste(img, ((s - w)//2, (s - h)//2))
    return canvas

@torch.inference_mode()
def predict_heading_label_topk(
    image_path: str,
    prototypes_path: str = "prototypes_heading.pt",
    device: str = "cuda",
    top_k: int = 3,
):
    prototypes = torch.load(prototypes_path)  # dict[label] -> [d] on CPU
    labels = list(prototypes.keys())
    mat = torch.stack([prototypes[l] for l in labels], dim=0)  # [C, d]

    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device).eval()
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    img = Image.open(image_path).convert("RGB")
    img = pad_to_square(img)

    inputs = processor(images=[img], return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    feat = model.get_image_features(**inputs)
    feat = F.normalize(feat, dim=1)[0].cpu()  # [d]

    sims = mat @ feat  # cosine similarity, shape [C]

    k = min(top_k, sims.numel())
    topk = torch.topk(sims, k=k)

    topk_items = []
    for score, idx in zip(topk.values.tolist(), topk.indices.tolist()):
        topk_items.append({
            "label": labels[int(idx)],
            "score": float(score),
        })

    best_score = topk_items[0]["score"]
    second_score = topk_items[1]["score"] if len(topk_items) > 1 else -1.0
    margin = best_score - second_score

    return {
        "topk": topk_items,              # ✅ top 3
        "best_label": topk_items[0]["label"],
        "best_score": best_score,
        "second_score": second_score,
        "margin": margin,
    }

if __name__ == "__main__":
    print(predict_heading_label_topk(
        image_path=r"E:\QuangNV\Show_image\outputs\step_out_3\htlt\Lop11\general\lesson3\lesson3\images\p000_img0002.png",
        prototypes_path=r"E:\AIBuddy\dev2\v1\book-chunking\chunking_super_hybrid\assets\prototypes_heading.pt",
        device="cuda" if torch.cuda.is_available() else "cpu",
        top_k=3,
    ))
