"""Main application window."""

from PySide6.QtWidgets import QMainWindow, QTabWidget

from ui.product_tab import ProductTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("卡牌库存管理")
        self.resize(1200, 800)

        tabs = QTabWidget()
        tabs.addTab(ProductTab(), "产品管理")

        stock_tab = QTabWidget()
        stock_tab.setEnabled(False)
        tabs.addTab(stock_tab, "入库")

        clear_tab = QTabWidget()
        clear_tab.setEnabled(False)
        tabs.addTab(clear_tab, "清库存")

        self.setCentralWidget(tabs)
