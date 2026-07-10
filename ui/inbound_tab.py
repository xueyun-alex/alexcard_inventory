"""Inbound tab: batch upload, hash matching, confirmation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.inventory import apply_inbound
from db import models
from db.models import InboundMatch
from ui.file_drop import FileDropListWidget, enable_file_drop
from ui.inbound_confirm_dialog import InboundConfirmDialog


class InboundWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list, list)
    error = Signal(str)

    def __init__(self, image_paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_paths = image_paths

    def run(self) -> None:
        try:
            paths = models.collect_image_paths(self._image_paths)
            total = len(paths)
            if total == 0:
                self.finished.emit([], [])
                return

            matches, unmatched = models.match_inbound_images(paths)
            self.progress.emit(total, total, f"识别完成 ({total}/{total})")
            self.finished.emit(matches, unmatched)
        except Exception as exc:
            self.error.emit(str(exc))


class InboundTab(QWidget):
    stock_updated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._paths: list[Path] = []
        self._worker: InboundWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        btn_select = QPushButton("选择图片")
        btn_clear = QPushButton("清空列表")
        btn_start = QPushButton("开始识别")
        btn_select.clicked.connect(self._select_images)
        btn_clear.clicked.connect(self._clear_paths)
        btn_start.clicked.connect(self._start_recognition)
        toolbar.addWidget(btn_select)
        toolbar.addWidget(btn_clear)
        toolbar.addStretch()
        toolbar.addWidget(btn_start)
        layout.addLayout(toolbar)

        self.file_list = FileDropListWidget()
        self.file_list.set_file_drop_callback(self._add_paths)
        layout.addWidget(self.file_list, stretch=1)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("就绪")
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.status_label)
        layout.addLayout(progress_row)

        enable_file_drop(self, self._add_paths)

    def handle_file_drop(self, paths: list[Path]) -> None:
        self._add_paths(paths)

    def _select_images(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择入库图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.gif)",
        )
        if files:
            self._add_paths([Path(f) for f in files])

    def _add_paths(self, paths: list[Path]) -> None:
        for path in models.collect_image_paths(paths):
            resolved = path.resolve()
            if resolved in {p.resolve() for p in self._paths}:
                continue
            self._paths.append(path)
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)

    def _clear_paths(self) -> None:
        self._paths.clear()
        self.file_list.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("就绪")

    def _start_recognition(self) -> None:
        if not self._paths:
            QMessageBox.information(self, "提示", "请先选择或拖入入库图片。")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._worker = InboundWorker(list(self._paths), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在识别...")
        self._worker.start()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        percent = int(current / total * 100) if total else 0
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_error(self, message: str) -> None:
        self.status_label.setText("识别失败")
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "识别失败", message)

    def _on_finished(
        self,
        matches: list[InboundMatch],
        unmatched: list[str],
    ) -> None:
        self.progress_bar.setValue(100)
        self.status_label.setText(
            f"识别完成，匹配 {len(matches)} 项，未匹配 {len(unmatched)} 项"
        )

        if not matches:
            message = "未识别到库中已有产品。"
            if unmatched:
                preview = ", ".join(unmatched[:10])
                suffix = "..." if len(unmatched) > 10 else ""
                message += f"\n\n未匹配 {len(unmatched)} 张：{preview}{suffix}"
            QMessageBox.information(self, "识别完成", message)
            return

        if unmatched:
            preview = ", ".join(unmatched[:10])
            suffix = "..." if len(unmatched) > 10 else ""
            QMessageBox.information(
                self,
                "部分未匹配",
                f"{len(unmatched)} 张图片未匹配到库中产品，已跳过：\n{preview}{suffix}",
            )

        dialog = InboundConfirmDialog(matches, self)
        if dialog.exec() != InboundConfirmDialog.DialogCode.Accepted:
            return

        selected = dialog.selected_items()
        if not selected:
            QMessageBox.information(self, "提示", "未选择任何入库项。")
            return

        try:
            count = apply_inbound(selected)
            self.stock_updated.emit()
            QMessageBox.information(self, "入库完成", f"已成功入库 {count} 项。")
        except Exception as exc:
            QMessageBox.critical(self, "入库失败", str(exc))
