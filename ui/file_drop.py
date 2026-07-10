"""File drag-and-drop helpers for image import tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QLabel, QListWidget, QWidget


def url_to_path(url: QUrl) -> str | None:
    local = url.toLocalFile()
    if local:
        return local
    path = url.path()
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        return path[1:]
    return path or None


def paths_from_event(event: QDragEnterEvent | QDropEvent) -> list[Path]:
    mime = event.mimeData()
    if not mime.hasUrls():
        return []
    paths: list[Path] = []
    for url in mime.urls():
        text = url_to_path(url)
        if text:
            paths.append(Path(text))
    return paths


def accept_file_drag(event: QDragEnterEvent) -> bool:
    if not paths_from_event(event):
        return False
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()
    return True


class FileDropMixin:
    """Mixin that accepts Explorer file/folder drops."""

    _file_drop_callback: Callable[[list[Path]], None] | None = None

    def set_file_drop_callback(
        self, callback: Callable[[list[Path]], None] | None
    ) -> None:
        self._file_drop_callback = callback

    def _dispatch_file_drop(self, paths: list[Path]) -> None:
        callback = self._file_drop_callback
        if callback is not None:
            QTimer.singleShot(0, lambda p=list(paths): callback(p))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragEnterEvent(event)  # type: ignore[misc]

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragMoveEvent(event)  # type: ignore[misc]

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = paths_from_event(event)
        if paths and self._file_drop_callback is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self._dispatch_file_drop(paths)
            return
        super().dropEvent(event)  # type: ignore[misc]


class FileDropListWidget(FileDropMixin, QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.viewport().setAcceptDrops(True)


class FileDropLabel(FileDropMixin, QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)


class FileDropWidget(FileDropMixin, QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)


def enable_file_drop(widget: QWidget, callback: Callable[[list[Path]], None]) -> None:
    """Enable file drops on an existing widget via mixin-style patching."""
    widget.setAcceptDrops(True)
    if isinstance(widget, QListWidget):
        widget.setDragEnabled(False)
        widget.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        widget.setDefaultDropAction(Qt.DropAction.CopyAction)
        widget.viewport().setAcceptDrops(True)

    if isinstance(widget, FileDropMixin):
        widget.set_file_drop_callback(callback)
        return

    # Bind mixin methods onto plain Qt widgets.
    def drag_enter(event: QDragEnterEvent) -> None:
        if accept_file_drag(event):
            return
        type(widget).dragEnterEvent(widget, event)

    def drag_move(event: QDragEnterEvent) -> None:
        if accept_file_drag(event):
            return
        type(widget).dragMoveEvent(widget, event)

    def drop(event: QDropEvent) -> None:
        paths = paths_from_event(event)
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            QTimer.singleShot(0, lambda p=list(paths): callback(p))
            return
        type(widget).dropEvent(widget, event)

    widget.dragEnterEvent = drag_enter  # type: ignore[method-assign]
    widget.dragMoveEvent = drag_move  # type: ignore[method-assign]
    widget.dropEvent = drop  # type: ignore[method-assign]

    viewport = widget.viewport() if hasattr(widget, "viewport") else None
    if viewport is not None:
        viewport.setAcceptDrops(True)
        viewport.dragEnterEvent = drag_enter  # type: ignore[method-assign]
        viewport.dragMoveEvent = drag_move  # type: ignore[method-assign]
        viewport.dropEvent = drop  # type: ignore[method-assign]
