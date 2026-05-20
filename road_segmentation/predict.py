from pathlib import Path
import argparse

import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch


IMAGE_SIZE = 512


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run inference for road segmentation on satellite imagery."
    )
    parser.add_argument(
        "--image",
        type=Path,
        required=True,
        help="Path to input satellite image.",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        required=True,
        help="Path to trained model checkpoint.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Directory for saving predicted segmentation masks.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Threshold for converting probability map to binary mask.",
    )
    return parser.parse_args()


def load_model(checkpoint_path: Path, device: torch.device) -> torch.nn.Module:
    model = smp.Unet(
        encoder_name="resnet34",
        encoder_weights="imagenet",
        in_channels=3,
        classes=1,
        activation=None,
    ).to(device)

    state_dict = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model.load_state_dict(state_dict)
    model.eval()
    return model


def build_transform() -> A.Compose:
    return A.Compose(
        [
            A.PadIfNeeded(min_height=IMAGE_SIZE, min_width=IMAGE_SIZE, border_mode=0, fill=0),
            A.CenterCrop(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
            ToTensorV2(),
        ]
    )


def main() -> None:
    args = parse_args()
    if not args.image.exists():
        raise FileNotFoundError(f"Input image not found: {args.image}")
    if not args.checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {args.checkpoint}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(args.checkpoint, device)
    transform = build_transform()

    image_rgb = np.array(Image.open(args.image).convert("RGB"))
    transformed = transform(image=image_rgb)
    image_tensor = transformed["image"].float().unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(image_tensor)
        probs = torch.sigmoid(logits)
        pred = (probs > args.threshold).float()

    pred_mask = pred.squeeze().cpu().numpy().astype(np.uint8) * 255

    original_prepared = image_tensor.squeeze(0).cpu().permute(1, 2, 0).numpy()
    original_prepared = (
        original_prepared * np.array([0.229, 0.224, 0.225], dtype=np.float32)
        + np.array([0.485, 0.456, 0.406], dtype=np.float32)
    )
    original_prepared = np.clip(original_prepared * 255.0, 0, 255).astype(np.uint8)

    overlay = original_prepared.copy()
    road_pixels = pred_mask > 0
    overlay[road_pixels] = (0.6 * overlay[road_pixels] + 0.4 * np.array([255, 0, 0])).astype(np.uint8)

    stem = args.image.stem
    mask_path = args.output_dir / f"{stem}_mask.png"
    overlay_path = args.output_dir / f"{stem}_overlay.png"

    Image.fromarray(pred_mask, mode="L").save(mask_path)
    Image.fromarray(overlay, mode="RGB").save(overlay_path)

    print(f"Input image: {args.image.resolve()}")
    print(f"Checkpoint: {args.checkpoint.resolve()}")
    print(f"Output directory: {args.output_dir.resolve()}")
    print(f"Saved mask: {mask_path.resolve()}")
    print(f"Saved overlay: {overlay_path.resolve()}")


if __name__ == "__main__":
    main()
