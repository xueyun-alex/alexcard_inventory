"""Packaging selection dialog for manual stock decreases."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from db import models
from db.models import Product

PACKAGE_TYPES = ("裸卡", "挂件袋", "带卡砖")
PREVIEW_SIZE = 96


@dataclass(frozen=True)
class StockDecreaseSelection:
    product: Product
    package_type: str
    quantity: int


class StockDecreaseDialog(QDialog):
    def __init__(
        self,
        products: list[Product],
        quantity: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._products = products
        self._combos: dict[int, QComboBox] = {}
        self._quantity_spins: dict[int, QSpinBox] = {}
        self._export_requested = True
        self.setWindowTitle("选择出库包装")
        self.setMinimumWidth(680)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "请选择每个商品的包装类型和减少数量；导出后会自动创建货单。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        number_row = QHBoxLayout()
        number_row.addWidget(QLabel("货单编号（可选）"))
        self.order_number_edit = QLineEdit()
        self.order_number_edit.setPlaceholderText("留空将自动生成，例如 20260720-001")
        self.order_number_edit.setMaxLength(64)
        number_row.addWidget(self.order_number_edit, stretch=1)
        layout.addLayout(number_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(4, 4, 4, 4)

        for product in products:
            rows.addWidget(self._build_product_row(product, quantity))
        rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定并导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        stock_only_button = buttons.addButton(
            "仅减少库存",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        buttons.accepted.connect(self._accept_with_export)
        stock_only_button.clicked.connect(self._accept_stock_only)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        visible_rows = min(len(products), 5)
        self.resize(720, min(180 + visible_rows * 126, 780))

    def _accept_with_export(self) -> None:
        self._export_requested = True
        self.accept()

    def _accept_stock_only(self, _checked: bool = False) -> None:
        self._export_requested = False
        self.accept()

    def _build_product_row(self, product: Product, quantity: int) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(frame)

        image_label = QLabel()
        image_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet(
            "background-color: #f0f0f0; border: 1px solid #cccccc;"
        )
        image_path = models.get_product_image_path(product)
        pixmap = QPixmap(str(image_path)) if image_path.exists() else QPixmap()
        if pixmap.isNull():
            image_label.setText("图片缺失")
        else:
            image_label.setPixmap(
                pixmap.scaled(
                    PREVIEW_SIZE,
                    PREVIEW_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        row.addWidget(image_label)

        details = QVBoxLayout()
        name_label = QLabel(product.name)
        name_label.setWordWrap(True)
        details.addWidget(name_label)
        details.addWidget(QLabel(f"当前库存：{product.stock}"))
        details.addStretch()
        row.addLayout(details, stretch=1)

        controls = QVBoxLayout()
        controls.addWidget(QLabel("包装类型"))
        combo = QComboBox()
        combo.addItems(PACKAGE_TYPES)
        combo.setMinimumWidth(120)
        self._combos[product.id] = combo
        controls.addWidget(combo)

        controls.addWidget(QLabel("本次减少"))
        quantity_row = QHBoxLayout()
        decrease_button = QPushButton("−")
        decrease_button.setFixedWidth(32)
        quantity_spin = QSpinBox()
        quantity_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        quantity_spin.setRange(1, 99999)
        quantity_spin.setValue(quantity)
        quantity_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        increase_button = QPushButton("+")
        increase_button.setFixedWidth(32)
        decrease_button.clicked.connect(
            lambda _checked=False, spin=quantity_spin: spin.setValue(
                spin.value() - 1
            )
        )
        increase_button.clicked.connect(
            lambda _checked=False, spin=quantity_spin: spin.setValue(
                spin.value() + 1
            )
        )
        quantity_row.addWidget(decrease_button)
        quantity_row.addWidget(quantity_spin, stretch=1)
        quantity_row.addWidget(increase_button)
        self._quantity_spins[product.id] = quantity_spin
        controls.addLayout(quantity_row)
        row.addLayout(controls)
        return frame

    @property
    def selections(self) -> list[StockDecreaseSelection]:
        return [
            StockDecreaseSelection(
                product=product,
                package_type=self._combos[product.id].currentText(),
                quantity=self._quantity_spins[product.id].value(),
            )
            for product in self._products
        ]

    @property
    def export_requested(self) -> bool:
        return self._export_requested

    @property
    def order_number(self) -> str:
        return self.order_number_edit.text().strip()
