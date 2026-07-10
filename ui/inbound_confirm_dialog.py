"""Inbound confirmation dialog."""

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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.inventory import InboundItem
from db import models
from db.models import InboundMatch
from ui.thumbnails import ThumbnailLoader, ThumbnailSignals

THUMB_SIZE = 80
DIALOG_MAX_VISIBLE_ROWS = 8


@dataclass
class _RowState:
    match: InboundMatch
    checkbox: QCheckBox


class InboundConfirmDialog(QDialog):
    def __init__(
        self,
        matches: list[InboundMatch],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认入库")
        self.resize(960, 500)
        self.setMinimumSize(640, 360)
        self._matches = matches
        self._rows: list[_RowState] = []
        self._load_generation = [0]
        self._thread_pool = QThreadPool.globalInstance()
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"识别到 {len(matches)} 个匹配项，请确认要入库的项目："))

        self.table = QTableWidget(len(matches), 7)
        self.table.setHorizontalHeaderLabels(
            ["", "入库图", "已有产品", "名称", "匹配原因", "当前库存", "入库后"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        for col in (0, 1, 2):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for row_idx, match in enumerate(matches):
            self._populate_row(row_idx, match)

        row_height = THUMB_SIZE + 12
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        header_height = max(self.table.horizontalHeader().height(), 30)
        visible_rows = min(len(matches), DIALOG_MAX_VISIBLE_ROWS)
        initial_table_height = header_height + row_height * visible_rows + 2
        self.table.setMinimumHeight(min(initial_table_height, 200))
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_row(self, row_idx: int, match: InboundMatch) -> None:
        self.table.setRowHeight(row_idx, THUMB_SIZE + 12)

        checkbox = QCheckBox()
        checkbox.setChecked(True)
        wrapper = QWidget()
        box_layout = QHBoxLayout(wrapper)
        box_layout.addWidget(checkbox)
        box_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box_layout.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row_idx, 0, wrapper)

        source_label = QLabel()
        source_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_label.setStyleSheet("background-color: #e0e0e0; border: 1px solid #ccc;")
        self.table.setCellWidget(row_idx, 1, source_label)
        source_key = f"source:{row_idx}"
        self._thumb_labels[source_key] = source_label
        self._load_thumbnail(source_key, match.source_path)

        product = match.existing_product
        product_label = QLabel()
        product_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        product_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        product_label.setStyleSheet("background-color: #e0e0e0; border: 1px solid #ccc;")
        self.table.setCellWidget(row_idx, 2, product_label)
        product_key = f"product:{row_idx}"
        self._thumb_labels[product_key] = product_label
        self._load_thumbnail(product_key, models.get_product_image_path(product))

        self.table.setItem(row_idx, 3, QTableWidgetItem(product.name))
        self.table.setItem(row_idx, 4, QTableWidgetItem(match.reason))
        self.table.setItem(row_idx, 5, QTableWidgetItem(str(product.stock)))
        self.table.setItem(row_idx, 6, QTableWidgetItem(str(product.stock + 1)))

        self._rows.append(_RowState(match=match, checkbox=checkbox))

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
            if not row.checkbox.isChecked():
                continue
            items.append(
                InboundItem(
                    product_id=row.match.existing_product.id,
                    source_image_path=row.match.source_path,
                )
            )
        return items

    def closeEvent(self, event) -> None:
        self._load_generation[0] += 1
        super().closeEvent(event)
