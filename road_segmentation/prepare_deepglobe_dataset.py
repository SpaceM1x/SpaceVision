from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def collect_pairs(raw_dir: Path) -> list[tuple[Path, Path, str]]:
    pairs: list[tuple[Path, Path, str]] = []
    for sat_path in sorted(raw_dir.rglob("*_sat.jpg")):
        stem = sat_path.name.removesuffix("_sat.jpg")
        mask_path = sat_path.with_name(f"{stem}_mask.png")
        if mask_path.exists():
            pairs.append((sat_path, mask_path, stem))
    return pairs


def save_image_as_png(src_path: Path, dst_path: Path) -> None:
    with Image.open(src_path) as image:
        rgb = image.convert("RGB")
        rgb.save(dst_path, format="PNG")


def save_binary_mask(src_path: Path, dst_path: Path) -> None:
    with Image.open(src_path) as mask:
        grayscale = mask.convert("L")
        binary = grayscale.point(lambda p: 255 if p > 127 else 0)
        binary.save(dst_path, format="PNG")


def cleanup_stale_dg_files(images_dir: Path, masks_dir: Path, valid_names: set[str]) -> tuple[int, int]:
    removed_images = 0
    removed_masks = 0

    for image_path in images_dir.glob("dg_*.png"):
        if image_path.name not in valid_names:
            image_path.unlink()
            removed_images += 1

    for mask_path in masks_dir.glob("dg_*.png"):
        if mask_path.name not in valid_names:
            mask_path.unlink()
            removed_masks += 1

    current_images = {path.name for path in images_dir.glob("dg_*.png")}
    current_masks = {path.name for path in masks_dir.glob("dg_*.png")}

    orphan_images = current_images - current_masks
    orphan_masks = current_masks - current_images

    for name in orphan_images:
        (images_dir / name).unlink(missing_ok=True)
        removed_images += 1

    for name in orphan_masks:
        (masks_dir / name).unlink(missing_ok=True)
        removed_masks += 1

    return removed_images, removed_masks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare DeepGlobe dataset into data/images and data/masks.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of image/mask pairs processed per batch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be a positive integer.")

    root_dir = Path(__file__).resolve().parent
    data_dir = root_dir / "data"
    raw_dir = data_dir / "deepglobe_raw"
    images_dir = data_dir / "images"
    masks_dir = data_dir / "masks"

    images_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)

    pairs = collect_pairs(raw_dir)
    valid_names = {f"dg_{stem}.png" for _, _, stem in pairs}
    removed_images, removed_masks = cleanup_stale_dg_files(images_dir, masks_dir, valid_names)

    total_pairs = len(pairs)
    total_batches = (total_pairs + args.batch_size - 1) // args.batch_size if total_pairs else 0
    processed_pairs = 0

    print(f"Source pairs found: {total_pairs}")
    print(f"Removed stale image files: {removed_images}")
    print(f"Removed stale mask files: {removed_masks}")

    for batch_index in range(total_batches):
        start = batch_index * args.batch_size
        end = min(start + args.batch_size, total_pairs)
        batch_pairs = pairs[start:end]

        for sat_path, mask_path, stem in batch_pairs:
            target_name = f"dg_{stem}.png"
            image_dst = images_dir / target_name
            mask_dst = masks_dir / target_name

            save_image_as_png(sat_path, image_dst)
            save_binary_mask(mask_path, mask_dst)
            processed_pairs += 1

        print(
            f"Batch {batch_index + 1}/{total_batches}: "
            f"processed {len(batch_pairs)} pairs ({start + 1}-{end})"
        )

    total_images = sum(1 for path in images_dir.iterdir() if path.is_file())
    total_masks = sum(1 for path in masks_dir.iterdir() if path.is_file())
    ready_pairs = len(
        {path.name for path in images_dir.glob("dg_*.png")}
        & {path.name for path in masks_dir.glob("dg_*.png")}
    )

    print(f"Pairs processed in this run: {processed_pairs}")
    print(f"Ready image/mask pairs on disk: {ready_pairs}")
    print(f"Total files in {images_dir}: {total_images}")
    print(f"Total files in {masks_dir}: {total_masks}")


if __name__ == "__main__":
    main()
