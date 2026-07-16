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

    In development this is the repo root. When running a build anywhere
    under the source tree (e.g. ``dist/<version>/<AppName>/``), walk up
    the ancestors to find the repo root (marked by ``main.py``) so product
    data matches ``python main.py``. Standalone copies distributed outside
    the source tree fall back to the exe folder.
    """
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        for parent in exe_dir.parents:
            if (parent / "main.py").is_file():
                return parent
        return exe_dir
    return Path(__file__).resolve().parent


def bundle_root() -> Path:
    """Read-only bundled assets directory."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)
