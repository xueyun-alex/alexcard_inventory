"""Resolve application and bundled resource paths (dev vs PyInstaller exe)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory containing the executable when frozen, else project root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """Writable project directory for data/ and settings/.

    In development this is the repo root. When running a build under
    ``dist/<AppName>/``, reuse the source tree so product data matches
    ``python main.py``. Standalone copies fall back to the exe folder.
    """
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        source_root = exe_dir.parent.parent
        if (source_root / "main.py").is_file():
            return source_root
        return exe_dir
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    """Read-only bundled assets directory."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)
