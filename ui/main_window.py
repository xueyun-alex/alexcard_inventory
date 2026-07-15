"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ui.file_drop import accept_file_drag, paths_from_event
from ui.history_tab import HistoryTab
from ui.inbound_tab import InboundTab
from ui.product_tab import ProductTab
from ui.sales_ranking_tab import SalesRankingTab


class DroppableTabWidget(QTabWidget):
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = paths_from_event(event)
        if paths and self._forward_file_drop(paths):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dropEvent(event)

    def _forward_file_drop(self, paths: list[Path]) -> bool:
        current = self.currentWidget()
        if current is None:
            return False
        handler = getattr(current, "handle_file_drop", None)
        if callable(handler):
            handler(paths)
            return True
        return False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("卡牌库存管理")
        self.resize(1200, 800)
        self.setAcceptDrops(True)

        tabs = DroppableTabWidget()
        tabs.setAcceptDrops(True)
        product_tab = ProductTab()
        inbound_tab = InboundTab()
        history_tab = HistoryTab()
        sales_tab = SalesRankingTab()

        inbound_tab.stock_updated.connect(product_tab.refresh_products)
        inbound_tab.stock_updated.connect(history_tab.refresh)
        product_tab.data_changed.connect(history_tab.refresh)
        product_tab.data_changed.connect(sales_tab.refresh)
        history_tab.data_changed.connect(product_tab.refresh_products)
        history_tab.data_changed.connect(product_tab.refresh_categories)
        history_tab.data_changed.connect(sales_tab.refresh)

        tabs.addTab(product_tab, "产品管理")
        tabs.addTab(inbound_tab, "入库")
        tabs.addTab(history_tab, "操作记录")
        tabs.addTab(sales_tab, "销量排行榜")

        clear_tab = QTabWidget()
        clear_tab.setEnabled(False)
        tabs.addTab(clear_tab, "清库存")

        self._tabs = tabs
        self.setCentralWidget(tabs)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if accept_file_drag(event):
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = paths_from_event(event)
        if paths and self._tabs._forward_file_drop(paths):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dropEvent(event)
