from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .models import Upload

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    cv2 = None


def _mask_metrics(mask_path: Path) -> dict:
    mask = np.array(Image.open(mask_path).convert("L"))
    binary = (mask > 127).astype(np.uint8)
    total_pixels = int(binary.size)
    road_pixels = int(binary.sum())
    background_pixels = total_pixels - road_pixels
    road_percentage = (road_pixels / total_pixels * 100.0) if total_pixels else 0.0

    component_count = 0
    mean_component_area = 0.0
    largest_component_area = 0
    if cv2 is not None and road_pixels > 0:
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        component_areas = stats[1:, cv2.CC_STAT_AREA]
        component_count = int(max(0, num_labels - 1))
        if component_areas.size > 0:
            mean_component_area = float(component_areas.mean())
            largest_component_area = int(component_areas.max())

    return {
        "total_pixels": total_pixels,
        "road_pixels": road_pixels,
        "background_pixels": background_pixels,
        "road_percentage": road_percentage,
        "background_percentage": 100.0 - road_percentage,
        "component_count": component_count,
        "mean_component_area": mean_component_area,
        "largest_component_area": largest_component_area,
    }


def _upload_prediction_paths(upload: Upload, prediction_dir: Path) -> tuple[Path, Path]:
    stem = Path(upload.file_path).stem
    return prediction_dir / f"{stem}_mask.png", prediction_dir / f"{stem}_overlay.png"


def build_analytics_summary(uploads: list[Upload], prediction_dir: Path) -> dict:
    per_upload = []
    valid_metrics = []

    for upload in uploads:
        mask_path, overlay_path = _upload_prediction_paths(upload, prediction_dir)
        if mask_path.exists():
            metrics = _mask_metrics(mask_path)
            valid_metrics.append(metrics)
        else:
            metrics = {
                "total_pixels": 0,
                "road_pixels": 0,
                "background_pixels": 0,
                "road_percentage": 0.0,
                "background_percentage": 0.0,
                "component_count": 0,
                "mean_component_area": 0.0,
                "largest_component_area": 0,
            }

        per_upload.append(
            {
                "id": upload.id,
                "title": upload.title,
                "created_at": upload.created_at,
                "uploaded_by": upload.uploaded_by,
                "road_percentage": metrics["road_percentage"],
                "background_percentage": metrics["background_percentage"],
                "road_pixels": metrics["road_pixels"],
                "background_pixels": metrics["background_pixels"],
                "component_count": metrics["component_count"],
                "mean_component_area": metrics["mean_component_area"],
                "largest_component_area": metrics["largest_component_area"],
                "mask_url": f"/uploads/{upload.id}/mask" if mask_path.exists() else None,
                "overlay_url": f"/uploads/{upload.id}/overlay" if overlay_path.exists() else None,
            }
        )

    total_uploads = len(uploads)
    uploads_with_predictions = len(valid_metrics)
    total_road_pixels = sum(item["road_pixels"] for item in valid_metrics)
    total_background_pixels = sum(item["background_pixels"] for item in valid_metrics)
    total_pixels = total_road_pixels + total_background_pixels
    global_road_coverage = (total_road_pixels / total_pixels * 100.0) if total_pixels else 0.0

    average_road_percentage = (
        float(np.mean([item["road_percentage"] for item in valid_metrics])) if valid_metrics else 0.0
    )
    max_road_percentage = (
        max((item["road_percentage"] for item in valid_metrics), default=0.0)
    )
    average_component_count = (
        float(np.mean([item["component_count"] for item in valid_metrics])) if valid_metrics else 0.0
    )

    # Keep timeline sorted from oldest to newest for charts.
    timeline = [
        {
            "id": item["id"],
            "title": item["title"],
            "created_at": item["created_at"],
            "road_percentage": item["road_percentage"],
        }
        for item in sorted(per_upload, key=lambda item: item["created_at"])
    ]

    return {
        "total_uploads": total_uploads,
        "uploads_with_predictions": uploads_with_predictions,
        "global_road_coverage": global_road_coverage,
        "average_road_percentage": average_road_percentage,
        "max_road_percentage": max_road_percentage,
        "average_component_count": average_component_count,
        "timeline": timeline,
        "items": per_upload,
    }
