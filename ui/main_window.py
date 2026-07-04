"""Main application window."""

from PySide6.QtWidgets import QMainWindow, QTabWidget

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
        inbound_tab.stock_updated.connect(product_tab.refresh_products)
        tabs.addTab(product_tab, "产品管理")
        tabs.addTab(inbound_tab, "入库")

        clear_tab = QTabWidget()
        clear_tab.setEnabled(False)
        tabs.addTab(clear_tab, "清库存")

        self.setCentralWidget(tabs)
