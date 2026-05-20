from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from PIL import Image


REPO_URL = "https://github.com/parth1620/Road_seg_dataset.git"


def clone_dataset(raw_dir: Path) -> None:
    if raw_dir.exists():
        print(f"Raw dataset already exists: {raw_dir}")
        return
    raw_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", REPO_URL, str(raw_dir)],
        check=True,
    )


def clear_pngs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for file_path in directory.glob("*.png"):
        file_path.unlink()


def copy_images(src_images: Path, dst_images: Path) -> int:
    count = 0
    for file_path in sorted(src_images.glob("*.png")):
        shutil.copy2(file_path, dst_images / file_path.name)
        count += 1
    return count


def copy_and_binarize_masks(src_masks: Path, dst_masks: Path) -> int:
    count = 0
    for file_path in sorted(src_masks.glob("*.png")):
        with Image.open(file_path) as mask:
            grayscale = mask.convert("L")
            binary = grayscale.point(lambda p: 255 if p > 127 else 0)
            binary.save(dst_masks / file_path.name, format="PNG")
        count += 1
    return count


def count_pairs(images_dir: Path, masks_dir: Path) -> int:
    image_names = {path.name for path in images_dir.glob("*.png")}
    mask_names = {path.name for path in masks_dir.glob("*.png")}
    return len(image_names & mask_names)


def find_existing_dir(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    listed = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"None of expected folders exist: {listed}")


def main() -> None:
    root_dir = Path(__file__).resolve().parent
    data_dir = root_dir / "data"
    raw_dir = data_dir / "raw"
    src_image_candidates = [raw_dir / "train_images", raw_dir / "images"]
    src_mask_candidates = [raw_dir / "train_masks", raw_dir / "masks"]
    dst_images = data_dir / "images"
    dst_masks = data_dir / "masks"

    clone_dataset(raw_dir)
    src_images = find_existing_dir(src_image_candidates)
    src_masks = find_existing_dir(src_mask_candidates)

    clear_pngs(dst_images)
    clear_pngs(dst_masks)

    copied_images = copy_images(src_images, dst_images)
    copied_masks = copy_and_binarize_masks(src_masks, dst_masks)
    pairs = count_pairs(dst_images, dst_masks)

    print(f"Copied images: {copied_images}")
    print(f"Copied masks: {copied_masks}")
    print(f"Image/mask pairs: {pairs}")
    print(f"Images path: {dst_images}")
    print(f"Masks path: {dst_masks}")


if __name__ == "__main__":
    main()
