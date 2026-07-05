"""Main application window."""

from PySide6.QtWidgets import QMainWindow, QTabWidget

from ui.history_tab import HistoryTab
from ui.inbound_tab import InboundTab
from ui.product_tab import ProductTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("卡牌库存管理")
        self.resize(1200, 800)

        tabs = QTabWidget()
        product_tab = ProductTab()
        inbound_tab = InboundTab()
        history_tab = HistoryTab()

        inbound_tab.stock_updated.connect(product_tab.refresh_products)
        inbound_tab.stock_updated.connect(history_tab.refresh)
        product_tab.data_changed.connect(history_tab.refresh)
        history_tab.data_changed.connect(product_tab.refresh_products)
        history_tab.data_changed.connect(product_tab.refresh_categories)

        tabs.addTab(product_tab, "产品管理")
        tabs.addTab(inbound_tab, "入库")
        tabs.addTab(history_tab, "操作记录")

        clear_tab = QTabWidget()
        clear_tab.setEnabled(False)
        tabs.addTab(clear_tab, "清库存")

        self.setCentralWidget(tabs)
