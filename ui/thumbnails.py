"""Shared async thumbnail loading."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QImage


class ThumbnailSignals(QObject):
    loaded = Signal(str, QImage)


class ThumbnailLoader(QRunnable):
    """Load a thumbnail in a background thread; key identifies the target cell."""

    def __init__(
        self,
        key: str,
        image_path: Path,
        size: int,
        signals: ThumbnailSignals,
        generation: int,
        generation_holder: list[int],
    ) -> None:
        super().__init__()
        self.key = key
        self.image_path = image_path
        self.size = size
        self.signals = signals
        self.generation = generation
        self.generation_holder = generation_holder

    def run(self) -> None:
        try:
            generation = self.generation
            generation_holder = self.generation_holder
        except (AttributeError, RuntimeError):
            return
        if generation != generation_holder[0]:
            return
        try:
            with Image.open(self.image_path) as img:
                img = img.convert("RGBA")
                img.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                qimage = QImage.fromData(buffer.getvalue(), "PNG")
        except Exception:
            qimage = QImage(
                self.size,
                self.size,
                QImage.Format.Format_ARGB32,
            )
            qimage.fill(Qt.GlobalColor.lightGray)

        if generation == generation_holder[0]:
            try:
                self.signals.loaded.emit(self.key, qimage)
            except RuntimeError:
                # The owning widget may have closed while this worker finished.
                return
