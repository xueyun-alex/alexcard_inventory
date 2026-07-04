"""Application configuration loaded from settings/config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "settings" / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "clip_threshold": 0.90,
    "phash_top_k": 20,
    "clip_model_path": "data/models/clip-vit-base-patch32.onnx",
    "yolo_model_path": None,
    "card_aspect_ratio_min": 0.55,
    "card_aspect_ratio_max": 0.85,
}


def load_config() -> dict[str, Any]:
    """Load config from disk, creating defaults if missing."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dict(DEFAULT_CONFIG)
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def resolve_config_path(config: dict[str, Any], key: str) -> Path | None:
    """Resolve a config path value relative to project root."""
    value = config.get(key)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
