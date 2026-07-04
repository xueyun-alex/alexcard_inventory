"""Match confirmation dialog for inbound/outbound flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.inventory import InboundItem
from core.types import RecognitionResult
from ui.thumbnails import ThumbnailLoader, ThumbnailSignals


THUMB_SIZE = 80


@dataclass
class _RowState:
    result: RecognitionResult
    checkbox: QCheckBox
    crop_label: QLabel
    product_label: QLabel


class MatchConfirmDialog(QDialog):
    def __init__(
        self,
        results: list[RecognitionResult],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认入库")
        self.resize(900, 500)
        self._results = results
        self._rows: list[_RowState] = []
        self._load_generation = [0]
        self._thread_pool = QThreadPool.globalInstance()
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(results), 7)
        self.table.setHorizontalHeaderLabels(
            ["", "检测缩略图", "匹配产品", "产品名", "相似度", "当前库存", "入库后"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for row_idx, result in enumerate(results):
            self._populate_row(row_idx, result)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_row(self, row_idx: int, result: RecognitionResult) -> None:
        self.table.setRowHeight(row_idx, THUMB_SIZE + 12)

        checkbox = QCheckBox()
        checkbox.setChecked(result.matched)
        checkbox.setEnabled(result.matched)
        wrapper = QWidget()
        box_layout = QHBoxLayout(wrapper)
        box_layout.addWidget(checkbox)
        box_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box_layout.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row_idx, 0, wrapper)

        crop_label = QLabel()
        crop_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        crop_label.setStyleSheet("background-color: #e0e0e0; border: 1px solid #ccc;")
        self.table.setCellWidget(row_idx, 1, crop_label)
        crop_key = f"crop:{row_idx}"
        self._thumb_labels[crop_key] = crop_label
        self._load_thumbnail(crop_key, result.crop_path)

        product_label = QLabel("—")
        if result.matched and result.product_id is not None:
            from db import models

            product = models.get_product(result.product_id)
            if product is not None:
                product_label = QLabel()
                product_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
                product_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                product_label.setStyleSheet(
                    "background-color: #e0e0e0; border: 1px solid #ccc;"
                )
                product_key = f"product:{row_idx}"
                self._thumb_labels[product_key] = product_label
                self._load_thumbnail(
                    product_key, models.get_product_image_path(product)
                )
        self.table.setCellWidget(row_idx, 2, product_label)

        name_text = result.product_name if result.matched else "未匹配"
        name_item = QTableWidgetItem(name_text)
        score_text = f"{result.score:.2f}" if result.score is not None else "—"
        score_item = QTableWidgetItem(score_text)
        stock_text = str(result.stock) if result.stock is not None else "—"
        stock_item = QTableWidgetItem(stock_text)
        after_text = (
            str(result.stock + 1)
            if result.matched and result.stock is not None
            else "—"
        )
        after_item = QTableWidgetItem(after_text)

        if not result.matched:
            gray = Qt.GlobalColor.gray
            for item in (name_item, score_item, stock_item, after_item):
                item.setForeground(gray)

        self.table.setItem(row_idx, 3, name_item)
        self.table.setItem(row_idx, 4, score_item)
        self.table.setItem(row_idx, 5, stock_item)
        self.table.setItem(row_idx, 6, after_item)

        self._rows.append(
            _RowState(
                result=result,
                checkbox=checkbox,
                crop_label=crop_label,
                product_label=product_label,
            )
        )

    def _load_thumbnail(self, key: str, path: Path) -> None:
        generation = self._load_generation[0]
        loader = ThumbnailLoader(
            key,
            path,
            THUMB_SIZE,
            self._thumb_signals,
            generation,
            self._load_generation,
        )
        self._thread_pool.start(loader)

    @Slot(str, QPixmap)
    def _on_thumbnail_loaded(self, key: str, pixmap: QPixmap) -> None:
        label = self._thumb_labels.get(key)
        if label is None:
            return
        scaled = pixmap.scaled(
            THUMB_SIZE,
            THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)

    def selected_items(self) -> list[InboundItem]:
        items: list[InboundItem] = []
        for row in self._rows:
            if not row.result.matched:
                continue
            if not row.checkbox.isChecked():
                continue
            if row.result.product_id is None:
                continue
            items.append(
                InboundItem(
                    product_id=row.result.product_id,
                    source_image_path=row.result.source_path,
                )
            )
        return items

    def closeEvent(self, event) -> None:
        self._load_generation[0] += 1
        super().closeEvent(event)
