"""Inbound tab: batch upload, recognition, confirmation."""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
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

from core.detector import detect_cards
from core.inventory import apply_inbound
from core.matcher import ProductMatcher
from core.types import RecognitionResult
from db import models
from db.database import DATA_DIR
from db.models import (
    backfill_product_hashes,
    compute_file_hash,
    compute_image_hash,
    compute_image_hash_pil,
)
from settings.config import load_config
from ui.file_drop import FileDropLabel, FileDropListWidget, enable_file_drop
from ui.match_dialog import MatchConfirmDialog

TEMP_INBOUND_DIR = DATA_DIR / "temp" / "inbound"


def _read_image(path: Path):
    import numpy as np

    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _write_image(path: Path, image) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ValueError(f"无法保存图片: {path.name}")
    encoded.tofile(str(path))


class RecognitionWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, image_paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_paths = image_paths

    def run(self) -> None:
        try:
            config = load_config()
            backfill_product_hashes()
            matcher = ProductMatcher()
            matcher.build_index()

            TEMP_INBOUND_DIR.mkdir(parents=True, exist_ok=True)

            total_crops = 0
            crop_plan: list[tuple[Path, object]] = []
            source_hashes: dict[Path, tuple[str, str]] = {}
            for source_path in self._image_paths:
                source_hashes[source_path] = (
                    compute_file_hash(source_path),
                    compute_image_hash(source_path),
                )
                crops = detect_cards(source_path, config)
                for crop in crops:
                    crop_plan.append((source_path, crop))
            total_crops = max(len(crop_plan), 1)

            results: list[RecognitionResult] = []
            for index, (source_path, crop) in enumerate(crop_plan, start=1):
                source_file_hash, source_image_hash = source_hashes[source_path]
                match = matcher.match_by_hashes(source_file_hash, source_image_hash)
                if match.product_id is None:
                    crop_phash = compute_image_hash_pil(
                        Image.fromarray(cv2.cvtColor(crop.image, cv2.COLOR_BGR2RGB))
                    )
                    match = matcher.match_by_hashes(None, crop_phash)

                crop_filename = f"{uuid.uuid4().hex}.png"
                crop_path = TEMP_INBOUND_DIR / crop_filename
                _write_image(crop_path, crop.image)

                matched = match.product_id is not None
                results.append(
                    RecognitionResult(
                        crop_path=crop_path,
                        source_path=source_path,
                        bbox=crop.bbox,
                        product_id=match.product_id,
                        product_name=match.product_name,
                        score=match.score,
                        stock=match.stock,
                        matched=matched,
                    )
                )
                self.progress.emit(
                    index,
                    total_crops,
                    f"正在识别 {source_path.name} ({index}/{total_crops})",
                )

            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class DetectionPreview(FileDropLabel):
    """Shows source image with detection bounding boxes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background-color: #f5f5f5; border: 1px solid #ccc; color: #666;"
        )
        self.setText("选择上方图片查看检测框预览")
        self._current_path: Path | None = None
        self._bboxes: list[tuple[int, int, int, int]] = []

    def set_detection(
        self,
        source_path: Path | None,
        bboxes: list[tuple[int, int, int, int]],
    ) -> None:
        self._current_path = source_path
        self._bboxes = bboxes
        if source_path is None or not source_path.is_file():
            self.clear()
            self.setText("选择上方图片查看检测框预览")
            return

        image = _read_image(source_path)
        if image is None:
            self.setText("无法加载预览图")
            return

        for x, y, w, h in bboxes:
            cv2.rectangle(image, (x, y), (x + w, y + h), (0, 120, 255), 3)

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimage = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage.copy())
        max_w = max(self.width() - 20, 400)
        max_h = max(self.height() - 20, 220)
        scaled = pixmap.scaled(
            max_w,
            max_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_path is not None:
            self.set_detection(self._current_path, self._bboxes)


class InboundTab(QWidget):
    stock_updated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._paths: list[Path] = []
        self._worker: RecognitionWorker | None = None
        self._last_results: list[RecognitionResult] = []
        self._detection_map: dict[Path, list[tuple[int, int, int, int]]] = {}
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
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.file_list, stretch=2)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("就绪")
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.status_label)
        layout.addLayout(progress_row)

        self.preview = DetectionPreview()
        self.preview.set_file_drop_callback(self._add_paths)
        layout.addWidget(self.preview, stretch=3)

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
        self.preview.set_detection(None, [])
        self._detection_map.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("就绪")

    def _on_selection_changed(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            self.preview.set_detection(None, [])
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        bboxes = self._detection_map.get(path.resolve(), [])
        self.preview.set_detection(path, bboxes)

    def _start_recognition(self) -> None:
        if not self._paths:
            QMessageBox.information(self, "提示", "请先选择或拖入入库图片。")
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._worker = RecognitionWorker(list(self._paths), self)
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

    def _on_finished(self, results: list[RecognitionResult]) -> None:
        self._last_results = results
        self.progress_bar.setValue(100)
        self.status_label.setText(f"识别完成，共 {len(results)} 个检测区域")

        self._detection_map.clear()
        for result in results:
            key = result.source_path.resolve()
            self._detection_map.setdefault(key, []).append(result.bbox)

        self._on_selection_changed()

        if not results:
            QMessageBox.information(self, "识别完成", "未检测到卡牌区域。")
            return

        dialog = MatchConfirmDialog(results, self)
        if dialog.exec() != MatchConfirmDialog.DialogCode.Accepted:
            self._cleanup_temp_crops(results)
            return

        selected = dialog.selected_items()
        if not selected:
            QMessageBox.information(self, "提示", "未选择任何入库项。")
            self._cleanup_temp_crops(results)
            return

        try:
            count = apply_inbound(selected)
            self.stock_updated.emit()
            QMessageBox.information(self, "入库完成", f"已成功入库 {count} 项。")
        except Exception as exc:
            QMessageBox.critical(self, "入库失败", str(exc))
        finally:
            self._cleanup_temp_crops(results)

    def _cleanup_temp_crops(self, results: list[RecognitionResult]) -> None:
        for result in results:
            if result.crop_path.is_file():
                try:
                    result.crop_path.unlink()
                except OSError:
                    pass
        if TEMP_INBOUND_DIR.exists() and not any(TEMP_INBOUND_DIR.iterdir()):
            try:
                TEMP_INBOUND_DIR.rmdir()
            except OSError:
                pass
