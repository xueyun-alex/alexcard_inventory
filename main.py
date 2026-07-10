"""Alexcard inventory application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app_paths import app_root, resource_path
from db.database import init_db
from ui.main_window import MainWindow

APP_ID = "AlexcardInventory.App.1"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def _app_icon() -> QIcon:
    for candidate in (app_root() / "checklist.ico", resource_path("checklist.ico")):
        if candidate.is_file():
            return QIcon(str(candidate))
    return QIcon()


def main() -> None:
    _set_windows_app_id()
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("卡牌库存管理")
    app.setApplicationDisplayName("卡牌库存管理")
    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
