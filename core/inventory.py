"""Inbound inventory application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from db import models


@dataclass
class InboundItem:
    product_id: int
    source_image_path: Path


def apply_inbound(items: list[InboundItem]) -> int:
    """Apply inbound stock increments in a single transaction."""
    batch = [(item.product_id, str(item.source_image_path)) for item in items]
    return models.apply_inbound_batch(batch)
