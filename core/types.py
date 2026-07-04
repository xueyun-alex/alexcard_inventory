"""Shared types for recognition pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RecognitionResult:
    crop_path: Path
    source_path: Path
    bbox: tuple[int, int, int, int]
    product_id: int | None
    product_name: str | None
    score: float | None
    stock: int | None
    matched: bool
