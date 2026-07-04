"""Card detection from inbound photos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from settings.config import resolve_config_path


@dataclass
class CardCrop:
    image: np.ndarray
    bbox: tuple[int, int, int, int]
    source_path: Path


def _imread_unicode(path: Path) -> np.ndarray | None:
    """Read image with Unicode path support on Windows."""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def detect_cards(source_path: Path, config: dict[str, Any]) -> list[CardCrop]:
    """Detect card regions; fallback to whole image as one crop."""
    source_path = Path(source_path)
    image = _imread_unicode(source_path)
    if image is None:
        raise ValueError(f"无法读取图片: {source_path.name}")

    yolo_path = resolve_config_path(config, "yolo_model_path")
    crops: list[CardCrop] = []

    if yolo_path is not None and yolo_path.is_file():
        crops = _detect_yolo(image, source_path, yolo_path, config)

    if not crops:
        crops = _detect_opencv(image, source_path, config)

    if not crops:
        h, w = image.shape[:2]
        crops = [CardCrop(image=image.copy(), bbox=(0, 0, w, h), source_path=source_path)]

    return crops


def _aspect_ratio_ok(
    width: int,
    height: int,
    ratio_min: float,
    ratio_max: float,
) -> bool:
    if width <= 0 or height <= 0:
        return False
    short, long_side = sorted((width, height))
    ratio = short / long_side
    return ratio_min <= ratio <= ratio_max


def _crop_from_bbox(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = bbox
    h_img, w_img = image.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    if x2 <= x1 or y2 <= y1:
        return image.copy()
    return image[y1:y2, x1:x2].copy()


def _detect_opencv(
    image: np.ndarray,
    source_path: Path,
    config: dict[str, Any],
) -> list[CardCrop]:
    ratio_min = float(config.get("card_aspect_ratio_min", 0.55))
    ratio_max = float(config.get("card_aspect_ratio_max", 0.85))
    h_img, w_img = image.shape[:2]
    img_area = h_img * w_img

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int, int, float]] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < img_area * 0.02 or area > img_area * 0.95:
            continue
        if not _aspect_ratio_ok(w, h, ratio_min, ratio_max):
            continue
        candidates.append((x, y, w, h, area))

    candidates.sort(key=lambda item: item[4], reverse=True)
    crops: list[CardCrop] = []
    used: list[tuple[int, int, int, int]] = []

    for x, y, w, h, _area in candidates:
        if _overlaps_existing((x, y, w, h), used, threshold=0.5):
            continue
        bbox = (x, y, w, h)
        crops.append(
            CardCrop(
                image=_crop_from_bbox(image, bbox),
                bbox=bbox,
                source_path=source_path,
            )
        )
        used.append(bbox)

    return crops


def _overlaps_existing(
    bbox: tuple[int, int, int, int],
    existing: list[tuple[int, int, int, int]],
    threshold: float,
) -> bool:
    x, y, w, h = bbox
    area = w * h
    if area <= 0:
        return True
    for ex, ey, ew, eh in existing:
        ix1 = max(x, ex)
        iy1 = max(y, ey)
        ix2 = min(x + w, ex + ew)
        iy2 = min(y + h, ey + eh)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        inter = (ix2 - ix1) * (iy2 - iy1)
        if inter / area >= threshold:
            return True
    return False


def _detect_yolo(
    image: np.ndarray,
    source_path: Path,
    model_path: Path,
    config: dict[str, Any],
) -> list[CardCrop]:
    try:
        from ultralytics import YOLO
    except ImportError:
        return []

    ratio_min = float(config.get("card_aspect_ratio_min", 0.55))
    ratio_max = float(config.get("card_aspect_ratio_max", 0.85))
    model = YOLO(str(model_path))
    results = model(image, verbose=False)
    crops: list[CardCrop] = []

    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            w = int(x2 - x1)
            h = int(y2 - y1)
            if not _aspect_ratio_ok(w, h, ratio_min, ratio_max):
                continue
            bbox = (int(x1), int(y1), w, h)
            crops.append(
                CardCrop(
                    image=_crop_from_bbox(image, bbox),
                    bbox=bbox,
                    source_path=source_path,
                )
            )
    return crops
