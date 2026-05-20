from pathlib import Path
import argparse


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
        default=Path("road_segmentation/outputs"),
        help="Directory for saving predicted segmentation masks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("Road segmentation inference script")
    print(f"Input image: {args.image.resolve()}")
    print(f"Checkpoint: {args.checkpoint.resolve()}")
    print(f"Output directory: {args.output_dir.resolve()}")
    print("TODO: load model checkpoint, preprocess image, run inference, save mask.")


if __name__ == "__main__":
    main()
