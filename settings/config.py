"""Application configuration loaded from settings/config.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app_paths import project_root, resource_path

PROJECT_ROOT = project_root()
CONFIG_PATH = PROJECT_ROOT / "settings" / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "yolo_model_path": None,
    "card_aspect_ratio_min": 0.55,
    "card_aspect_ratio_max": 0.85,
}


def _seed_config_file() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    bundled = resource_path("settings", "config.json")
    if bundled.is_file():
        shutil.copy2(bundled, CONFIG_PATH)
        return
    CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_config() -> dict[str, Any]:
    """Load config from disk, creating defaults if missing."""
    if not CONFIG_PATH.exists():
        _seed_config_file()
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
