from pathlib import Path
import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a road segmentation model on satellite imagery."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("road_segmentation/data"),
        help="Path to dataset root directory.",
    )
    parser.add_argument(
        "--checkpoints-dir",
        type=Path,
        default=Path("road_segmentation/checkpoints"),
        help="Directory for saving model checkpoints.",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=20,
        help="Number of training epochs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    print("Road segmentation training script")
    print(f"Dataset directory: {args.data_dir.resolve()}")
    print(f"Checkpoints directory: {args.checkpoints_dir.resolve()}")
    print(f"Epochs: {args.epochs}")
    print("TODO: add dataloaders, model setup, training loop, and checkpoint saving.")


if __name__ == "__main__":
    main()
