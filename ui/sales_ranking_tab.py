"""Sales ranking by manual stock decreases."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, QThreadPool, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from db import models
from db.database import DATA_DIR
from ui.thumbnails import ThumbnailLoader, ThumbnailSignals

THUMB_SIZE = 64


class SalesRankingTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._load_generation = [0]
        self._thread_pool = QThreadPool.globalInstance()
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("按时间范围内手动库存减少总量排名（已回退的变更不计入）。")
        )

        filter_row = QHBoxLayout()
        self.btn_today = QPushButton("今天")
        self.btn_7d = QPushButton("近7天")
        self.btn_month = QPushButton("本月")
        self.btn_today.clicked.connect(self._preset_today)
        self.btn_7d.clicked.connect(self._preset_7d)
        self.btn_month.clicked.connect(self._preset_month)
        filter_row.addWidget(self.btn_today)
        filter_row.addWidget(self.btn_7d)
        filter_row.addWidget(self.btn_month)

        filter_row.addWidget(QLabel("从"))
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        filter_row.addWidget(self.start_date)

        filter_row.addWidget(QLabel("到"))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        filter_row.addWidget(self.end_date)

        self.btn_query = QPushButton("查询")
        self.btn_query.clicked.connect(self.refresh)
        filter_row.addWidget(self.btn_query)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["排名", "图片", "产品名称", "减少数量"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMB_SIZE + 12)
        layout.addWidget(self.table)

        today = date.today()
        self._set_range(today - timedelta(days=6), today)
        self.refresh()

    def _set_range(self, start: date, end: date) -> None:
        self.start_date.setDate(QDate(start.year, start.month, start.day))
        self.end_date.setDate(QDate(end.year, end.month, end.day))

    def _preset_today(self) -> None:
        today = date.today()
        self._set_range(today, today)
        self.refresh()

    def _preset_7d(self) -> None:
        today = date.today()
        self._set_range(today - timedelta(days=6), today)
        self.refresh()

    def _preset_month(self) -> None:
        today = date.today()
        self._set_range(today.replace(day=1), today)
        self.refresh()

    def _bounds(self) -> tuple[str, str]:
        start = self.start_date.date().toPython()
        end = self.end_date.date().toPython()
        if end < start:
            start, end = end, start
            self._set_range(start, end)
        return (
            f"{start.isoformat()} 00:00:00",
            f"{end.isoformat()} 23:59:59",
        )

    def refresh(self) -> None:
        self._load_generation[0] += 1
        generation = self._load_generation[0]
        self._thumb_labels.clear()

        start, end = self._bounds()
        rows = models.list_sales_ranking(start, end)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setRowHeight(row_index, THUMB_SIZE + 12)
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row_index + 1)))

            thumb = QLabel()
            thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("background-color: #e0e0e0; border: 1px solid #ccc;")
            self.table.setCellWidget(row_index, 1, thumb)
            key = f"rank:{row_index}"
            self._thumb_labels[key] = thumb
            image_path = DATA_DIR / row.image_path
            loader = ThumbnailLoader(
                key,
                image_path,
                THUMB_SIZE,
                self._thumb_signals,
                generation,
                self._load_generation,
            )
            self._thread_pool.start(loader)

            self.table.setItem(row_index, 2, QTableWidgetItem(row.name))
            self.table.setItem(row_index, 3, QTableWidgetItem(str(row.sold_qty)))

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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
