"""Coze SDK configuration loaded from environment or settings/coze.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
COZE_CONFIG_PATH = PROJECT_ROOT / "settings" / "coze.json"

COZE_API_TOKEN: str = ""
COZE_BOT_ID: str = ""


def reload_config() -> None:
    """Reload Coze credentials from env vars and settings/coze.json."""
    global COZE_API_TOKEN, COZE_BOT_ID

    COZE_API_TOKEN = os.environ.get("COZE_API_TOKEN", "").strip()
    COZE_BOT_ID = os.environ.get("COZE_BOT_ID", "").strip()

    if not COZE_CONFIG_PATH.exists():
        return

    with COZE_CONFIG_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not COZE_API_TOKEN:
        COZE_API_TOKEN = str(data.get("coze_api_token", "") or "").strip()
    if not COZE_BOT_ID:
        COZE_BOT_ID = str(data.get("coze_bot_id", "") or "").strip()


reload_config()
