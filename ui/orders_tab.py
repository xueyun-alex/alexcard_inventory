"""Outbound order list, editing, details, and re-export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.collage import build_vertical_stock_export
from db import models, orders
from db.models import Product

CARD_THUMB_SIZE = 72
DETAIL_THUMB_SIZE = 110
EDIT_THUMB_SIZE = 64


def _image_label(path: Path, size: int) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        "background-color: #f0f0f0; border: 1px solid #cccccc;"
    )
    pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
    if pixmap.isNull():
        label.setText("图片缺失")
        label.setWordWrap(True)
    else:
        label.setPixmap(
            pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return label


class OrderCard(QFrame):
    status_changed = Signal(int, str)
    detail_requested = Signal(int)
    edit_requested = Signal(int)
    export_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(
        self,
        order: orders.Order,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.order = order
        self._expanded = True
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "OrderCard { background: white; border: 1px solid #d8dde5;"
            " border-radius: 6px; }"
        )

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.toggle_button = QPushButton("▲ 收起")
        self.toggle_button.setFixedWidth(72)
        self.toggle_button.clicked.connect(self._toggle)
        header.addWidget(self.toggle_button)

        order_label = QLabel(f"货单编号：{order.order_no}")
        order_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        header.addWidget(order_label, stretch=1)

        header.addWidget(QLabel(f"商品种类：{order.product_type_count}"))
        header.addWidget(QLabel(f"总数量：{order.total_quantity}"))
        header.addWidget(QLabel("状态"))
        status_combo = QComboBox()
        status_combo.addItems(orders.ORDER_STATUSES)
        status_combo.setCurrentText(order.status)
        status_combo.currentTextChanged.connect(
            lambda status: self.status_changed.emit(order.id, status)
        )
        header.addWidget(status_combo)

        detail_button = QPushButton("查看详情")
        detail_button.clicked.connect(
            lambda _checked=False: self.detail_requested.emit(order.id)
        )
        header.addWidget(detail_button)
        edit_button = QPushButton("编辑货单")
        edit_button.clicked.connect(
            lambda _checked=False: self.edit_requested.emit(order.id)
        )
        header.addWidget(edit_button)
        export_button = QPushButton("重新导出")
        export_button.clicked.connect(
            lambda _checked=False: self.export_requested.emit(order.id)
        )
        header.addWidget(export_button)
        delete_button = QPushButton("删除订单")
        delete_button.setStyleSheet(
            "QPushButton { background-color: #d13438; color: white;"
            " border: 1px solid #b52a2e; border-radius: 3px;"
            " padding: 4px 10px; }"
            "QPushButton:hover { background-color: #b52a2e; }"
            "QPushButton:pressed { background-color: #8f2023; }"
        )
        delete_button.clicked.connect(
            lambda _checked=False: self.delete_requested.emit(order.id)
        )
        header.addWidget(delete_button)
        layout.addLayout(header)

        meta = QLabel(
            f"创建时间：{order.created_at}"
            + (
                f"　　最近导出：{order.export_path}"
                if order.export_path
                else ""
            )
        )
        meta.setStyleSheet("color: #687386;")
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(meta)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(8, 2, 8, 4)
        body_layout.setSpacing(6)
        for item in order.items:
            body_layout.addWidget(self._build_item_row(item))
        layout.addWidget(self.body)

    def _build_item_row(self, item: orders.OrderItem) -> QFrame:
        row_frame = QFrame()
        row_frame.setStyleSheet(
            "QFrame { background: #f7f9fc; border-radius: 4px; }"
        )
        row = QHBoxLayout(row_frame)
        row.setContentsMargins(8, 6, 12, 6)
        row.addWidget(
            _image_label(
                orders.get_order_item_image_path(item),
                CARD_THUMB_SIZE,
            )
        )
        name = QLabel(item.product_name)
        name.setWordWrap(True)
        row.addWidget(name, stretch=1)
        package = QLabel(f"包装：{item.package_type}")
        package.setMinimumWidth(110)
        row.addWidget(package)
        quantity = QLabel(f"数量：{item.quantity}")
        quantity.setMinimumWidth(90)
        row.addWidget(quantity)
        return row_frame

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.toggle_button.setText("▲ 收起" if self._expanded else "▼ 展开")


class OrderDetailDialog(QDialog):
    def __init__(
        self,
        order: orders.Order,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.export_requested = False
        self.setWindowTitle(f"货单详情 — {order.order_no}")
        self.resize(700, 650)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"货单编号：{order.order_no}"))
        layout.addWidget(
            QLabel(
                f"状态：{order.status}　　商品种类：{order.product_type_count}"
                f"　　总数量：{order.total_quantity}"
            )
        )
        layout.addWidget(
            QLabel(f"创建时间：{order.created_at}　　更新时间：{order.updated_at}")
        )
        if order.export_path:
            path_label = QLabel(f"最近导出：{order.export_path}")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(path_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        for item in order.items:
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            row = QHBoxLayout(frame)
            row.addWidget(
                _image_label(
                    orders.get_order_item_image_path(item),
                    DETAIL_THUMB_SIZE,
                )
            )
            details = QVBoxLayout()
            name = QLabel(item.product_name)
            name.setWordWrap(True)
            name.setStyleSheet("font-weight: 600; font-size: 15px;")
            details.addWidget(name)
            details.addWidget(QLabel(f"包装：{item.package_type}"))
            details.addWidget(QLabel(f"数量：{item.quantity}"))
            details.addStretch()
            row.addLayout(details, stretch=1)
            rows.addWidget(frame)
        rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        export_button = buttons.addButton(
            "重新导出清单",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        export_button.clicked.connect(self._request_export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _request_export(self) -> None:
        self.export_requested = True
        self.accept()


@dataclass
class _EditItem:
    product_id: int | None
    product_name: str
    image_path: Path
    package_type: str
    quantity: int


class OrderEditDialog(QDialog):
    def __init__(
        self,
        order: orders.Order,
        products: list[Product],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._products = {product.id: product for product in products}
        self._items = [
            _EditItem(
                product_id=item.product_id,
                product_name=item.product_name,
                image_path=orders.get_order_item_image_path(item),
                package_type=item.package_type,
                quantity=item.quantity,
            )
            for item in order.items
        ]
        self.setWindowTitle(f"编辑货单 — {order.order_no}")
        self.resize(820, 650)

        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        form.addWidget(QLabel("货单编号"))
        self.order_no_edit = QLineEdit(order.order_no)
        self.order_no_edit.setMaxLength(64)
        form.addWidget(self.order_no_edit, stretch=1)
        form.addWidget(QLabel("状态"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(orders.ORDER_STATUSES)
        self.status_combo.setCurrentText(order.status)
        form.addWidget(self.status_combo)
        self.count_label = QLabel()
        form.addWidget(self.count_label)
        layout.addLayout(form)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("增加商品"))
        self.product_combo = QComboBox()
        for product in products:
            self.product_combo.addItem(f"#{product.id}　{product.name}", product.id)
        self.product_combo.setMinimumWidth(360)
        add_row.addWidget(self.product_combo, stretch=1)
        add_button = QPushButton("添加到货单")
        add_button.clicked.connect(self._add_product)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["图片", "商品", "包装", "数量", "操作"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for column in (2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存修改")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        self.table.setRowCount(len(self._items))
        for row_index, item in enumerate(self._items):
            self.table.setRowHeight(row_index, EDIT_THUMB_SIZE + 12)
            self.table.setCellWidget(
                row_index,
                0,
                _image_label(item.image_path, EDIT_THUMB_SIZE),
            )
            name = item.product_name
            if item.product_id is None:
                name += "（商品已删除，请移除此项）"
            self.table.setItem(row_index, 1, QTableWidgetItem(name))

            package_combo = QComboBox()
            package_combo.addItems(orders.PACKAGE_TYPES)
            package_combo.setCurrentText(item.package_type)
            package_combo.setEnabled(item.product_id is not None)
            package_combo.currentTextChanged.connect(
                lambda package, state=item: setattr(
                    state,
                    "package_type",
                    package,
                )
            )
            self.table.setCellWidget(row_index, 2, package_combo)

            quantity_spin = QSpinBox()
            quantity_spin.setRange(1, 99999)
            quantity_spin.setValue(item.quantity)
            quantity_spin.setEnabled(item.product_id is not None)
            quantity_spin.valueChanged.connect(
                lambda quantity, state=item: setattr(
                    state,
                    "quantity",
                    quantity,
                )
            )
            self.table.setCellWidget(row_index, 3, quantity_spin)

            remove_button = QPushButton("移除")
            remove_button.clicked.connect(
                lambda _checked=False, state=item: self._remove_item(state)
            )
            self.table.setCellWidget(row_index, 4, remove_button)
        self.count_label.setText(f"商品种类：{len(self._items)}")

    def _add_product(self) -> None:
        product_id = self.product_combo.currentData()
        if product_id is None:
            return
        if any(item.product_id == product_id for item in self._items):
            QMessageBox.information(self, "提示", "该商品已在货单中。")
            return
        product = self._products.get(int(product_id))
        if product is None:
            QMessageBox.warning(self, "错误", "商品不存在，请刷新后重试。")
            return
        self._items.append(
            _EditItem(
                product_id=product.id,
                product_name=product.name,
                image_path=models.get_product_image_path(product),
                package_type=orders.PACKAGE_TYPES[0],
                quantity=1,
            )
        )
        self._rebuild_table()

    def _remove_item(self, item: _EditItem) -> None:
        self._items.remove(item)
        self._rebuild_table()

    def _validate_and_accept(self) -> None:
        if not self.order_no_edit.text().strip():
            QMessageBox.warning(self, "无法保存", "货单编号不能为空。")
            return
        if not self._items:
            QMessageBox.warning(self, "无法保存", "货单至少需要一个商品。")
            return
        if any(item.product_id is None for item in self._items):
            QMessageBox.warning(
                self,
                "无法保存",
                "货单中存在已删除的商品，请先移除该项。",
            )
            return
        self.accept()

    @property
    def order_no(self) -> str:
        return self.order_no_edit.text().strip()

    @property
    def status(self) -> str:
        return self.status_combo.currentText()

    @property
    def items(self) -> list[tuple[int, str, int]]:
        return [
            (int(item.product_id), item.package_type, item.quantity)
            for item in self._items
            if item.product_id is not None
        ]


class OrdersTab(QWidget):
    data_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(
            QLabel("已导出的库存减少清单会自动生成货单，默认状态为“待发货”。")
        )
        toolbar.addStretch()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_button)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.cards_layout = QVBoxLayout(self.content)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, stretch=1)
        self.refresh()

    def refresh(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        order_list = orders.list_orders()
        if not order_list:
            empty = QLabel("暂无货单。完成一次“确定并导出”后会显示在这里。")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #687386; padding: 36px;")
            self.cards_layout.addWidget(empty)
            return

        for order in order_list:
            card = OrderCard(order)
            card.status_changed.connect(self._change_status)
            card.detail_requested.connect(self._show_detail)
            card.edit_requested.connect(self._edit_order)
            card.export_requested.connect(self._reexport_order)
            card.delete_requested.connect(self._delete_order)
            self.cards_layout.addWidget(card)

    def _change_status(self, order_id: int, status: str) -> None:
        order = orders.get_order(order_id)
        if order is None or order.status == status:
            return
        try:
            orders.update_order_status(order_id, status)
        except Exception as exc:
            QMessageBox.warning(self, "状态修改失败", str(exc))
            self.refresh()
            return
        self.refresh()
        self.data_changed.emit()

    def _show_detail(self, order_id: int) -> None:
        order = orders.get_order(order_id)
        if order is None:
            QMessageBox.warning(self, "错误", "货单不存在。")
            self.refresh()
            return
        dialog = OrderDetailDialog(order, self)
        dialog.exec()
        if dialog.export_requested:
            self._reexport_order(order_id)

    def _edit_order(self, order_id: int) -> None:
        order = orders.get_order(order_id)
        if order is None:
            QMessageBox.warning(self, "错误", "货单不存在。")
            self.refresh()
            return
        dialog = OrderEditDialog(order, models.list_products(None), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            orders.update_order(
                order_id,
                dialog.order_no,
                dialog.status,
                dialog.items,
            )
        except Exception as exc:
            QMessageBox.warning(self, "货单修改失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(
            self,
            "修改成功",
            "货单已更新，库存和销量排行榜已同步调整。",
        )

    def _delete_order(self, order_id: int) -> None:
        order = orders.get_order(order_id)
        if order is None:
            QMessageBox.warning(self, "错误", "货单不存在。")
            self.refresh()
            return
        restorable_quantity = sum(
            item.quantity
            for item in order.items
            if item.product_id is not None
        )
        missing_quantity = order.total_quantity - restorable_quantity
        message = (
            f"确定删除货单「{order.order_no}」？\n\n"
            f"将删除 {order.product_type_count} 种、共 {order.total_quantity} 件商品，"
            f"并自动恢复库存 {restorable_quantity} 件。\n"
            "销量排行榜会同步更新。"
        )
        if missing_quantity:
            message += (
                f"\n\n其中 {missing_quantity} 件商品已从产品库删除，"
                "无法恢复对应库存。"
            )
        reply = QMessageBox.question(
            self,
            "确认删除订单",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            orders.delete_order(order_id)
        except Exception as exc:
            QMessageBox.warning(self, "删除订单失败", str(exc))
            return
        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(
            self,
            "删除成功",
            f"货单已删除，库存已恢复 {restorable_quantity} 件。",
        )

    def _reexport_order(self, order_id: int) -> None:
        order = orders.get_order(order_id)
        if order is None:
            QMessageBox.warning(self, "错误", "货单不存在。")
            self.refresh()
            return
        default_name = (
            f"库存减少清单_{orders.safe_filename_part(order.order_no)}.png"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "重新导出库存减少清单",
            default_name,
            "PNG 图片 (*.png);;JPG 图片 (*.jpg *.jpeg)",
        )
        if not file_path:
            return

        output_path = Path(file_path)
        temp_suffix = output_path.suffix or ".png"
        temp_path = output_path.with_name(
            f".{output_path.stem}.{uuid4().hex}.tmp{temp_suffix}"
        )
        export_items = [
            (
                item.product_name,
                orders.get_order_item_image_path(item),
                item.package_type,
                item.quantity,
            )
            for item in order.items
        ]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            added, skipped = build_vertical_stock_export(
                export_items,
                temp_path,
                order.order_no,
            )
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        if added != len(export_items):
            temp_path.unlink(missing_ok=True)
            QMessageBox.warning(
                self,
                "导出失败",
                f"有 {skipped} 个商品图片缺失或无法读取。",
            )
            return
        try:
            temp_path.replace(output_path)
            orders.set_export_path(order.id, str(output_path))
        except Exception as exc:
            QMessageBox.critical(
                self,
                "清单保存失败",
                f"{exc}\n\n临时图片保留在：\n{temp_path}",
            )
            return
        self.refresh()
        QMessageBox.information(
            self,
            "导出成功",
            f"库存减少清单已导出到：\n{output_path}",
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
