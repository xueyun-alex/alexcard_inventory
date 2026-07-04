"""Product management tab."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QDrag, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from db import models
from db.models import Category, Product
from ui.thumbnails import ThumbnailLoader, ThumbnailSignals

THUMB_SIZE = 120
GRID_COLUMNS = 6

FILTER_ALL = "all"
FILTER_UNCATEGORIZED = "uncategorized"


class ProductCard(QWidget):
    clicked = Signal(int, object)  # product_id, QMouseEvent
    rename_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, product: Product, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.product = product
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.image_label = QLabel()
        self.image_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.stock_label = QLabel(f"×{product.stock}")
        self.stock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stock_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.name_label = QLabel(product.name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumWidth(THUMB_SIZE + 8)
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self.image_label)
        layout.addWidget(self.stock_label)
        layout.addWidget(self.name_label)

        self.setFixedWidth(THUMB_SIZE + 16)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._update_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def is_selected(self) -> bool:
        return self._selected

    def set_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            THUMB_SIZE,
            THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "ProductCard {"
                " background-color: #e8f4fd;"
                " border: 2px solid #0078d4;"
                " border-radius: 4px;"
                "}"
            )
            self.image_label.setStyleSheet(
                "background-color: #d0e8fc; border: 2px solid #0078d4; border-radius: 2px;"
            )
        else:
            self.setStyleSheet(
                "ProductCard {"
                " background-color: transparent;"
                " border: 2px solid transparent;"
                " border-radius: 4px;"
                "}"
            )
            self.image_label.setStyleSheet(
                "background-color: #e0e0e0; border: 1px solid #ccc;"
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.product.id, event)
        super().mousePressEvent(event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        action = menu.exec(self.mapToGlobal(pos))
        if action == rename_action:
            self.rename_requested.emit(self.product)
        elif action == delete_action:
            self.delete_requested.emit(self.product)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self.is_selected():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.product.id))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class CategorySelectDialog(QDialog):
    def __init__(self, categories: list[Category], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择产品类")
        self.selected_category_id: int | None = None

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        uncategorized_item = QListWidgetItem("未归类")
        uncategorized_item.setData(Qt.ItemDataRole.UserRole, None)
        self.list_widget.addItem(uncategorized_item)

        for category in categories:
            item = QListWidgetItem(category.name)
            item.setData(Qt.ItemDataRole.UserRole, category.id)
            self.list_widget.addItem(item)

        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_selection())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)

        layout.addWidget(self.list_widget)
        layout.addWidget(buttons)

    def _accept_selection(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_category_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class ProductTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._current_filter: str | int = FILTER_ALL
        self._cards: dict[int, ProductCard] = {}
        self._last_clicked_id: int | None = None
        self._load_generation = [0]
        self._thread_pool = QThreadPool.globalInstance()
        self._thumb_signals = ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)

        self._build_ui()
        self.refresh_categories()
        self.refresh_products()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QToolBar()
        btn_new_category = QPushButton("新建产品类")
        btn_import = QPushButton("导入图片")
        btn_move = QPushButton("移动到产品类")
        btn_refresh = QPushButton("刷新")
        btn_new_category.clicked.connect(self.create_category_dialog)
        btn_import.clicked.connect(self.import_images_dialog)
        btn_move.clicked.connect(self.move_selected_products)
        btn_refresh.clicked.connect(self.refresh_all)
        toolbar.addWidget(btn_new_category)
        toolbar.addWidget(btn_import)
        toolbar.addWidget(btn_move)
        toolbar.addWidget(btn_refresh)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.category_list = QListWidget()
        self.category_list.setMinimumWidth(180)
        self.category_list.setMaximumWidth(260)
        self.category_list.currentItemChanged.connect(self._on_category_changed)
        self.category_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.category_list.customContextMenuRequested.connect(self._category_context_menu)
        self.category_list.setAcceptDrops(True)
        self.category_list.viewport().setAcceptDrops(True)
        self.category_list.dropEvent = self._category_drop_event  # type: ignore[method-assign]
        self.category_list.dragEnterEvent = self._category_drag_enter  # type: ignore[method-assign]
        self.category_list.dragMoveEvent = self._category_drag_enter  # type: ignore[method-assign]

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll_area.setWidget(self.grid_container)

        splitter.addWidget(self.category_list)
        splitter.addWidget(self.scroll_area)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def refresh_categories(self) -> None:
        current_data = None
        item = self.category_list.currentItem()
        if item is not None:
            current_data = item.data(Qt.ItemDataRole.UserRole)

        counts = models.count_products_by_category()
        total_count = sum(counts.values())
        uncategorized_count = counts.get(None, 0)

        self.category_list.clear()

        all_item = QListWidgetItem(f"全部 ({total_count})")
        all_item.setData(Qt.ItemDataRole.UserRole, FILTER_ALL)
        self.category_list.addItem(all_item)

        uncategorized_item = QListWidgetItem(f"未归类 ({uncategorized_count})")
        uncategorized_item.setData(Qt.ItemDataRole.UserRole, FILTER_UNCATEGORIZED)
        self.category_list.addItem(uncategorized_item)

        for category in models.list_categories():
            count = counts.get(category.id, 0)
            cat_item = QListWidgetItem(f"{category.name} ({count})")
            cat_item.setData(Qt.ItemDataRole.UserRole, category.id)
            self.category_list.addItem(cat_item)

        self.category_list.blockSignals(True)
        try:
            restored = False
            for i in range(self.category_list.count()):
                list_item = self.category_list.item(i)
                if list_item.data(Qt.ItemDataRole.UserRole) == current_data:
                    self.category_list.setCurrentItem(list_item)
                    restored = True
                    break
            if not restored:
                self.category_list.setCurrentRow(0)
        finally:
            self.category_list.blockSignals(False)

    def refresh_all(self) -> None:
        self.refresh_categories()
        self.refresh_products()

    def refresh_products(self) -> None:
        self._load_generation[0] += 1
        generation = self._load_generation[0]

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._cards.clear()
        self._last_clicked_id = None

        if self._current_filter == FILTER_ALL:
            products = models.list_products(None)
        elif self._current_filter == FILTER_UNCATEGORIZED:
            products = models.list_products(-1)
        else:
            products = models.list_products(int(self._current_filter))

        for index, product in enumerate(products):
            card = ProductCard(product)
            card.clicked.connect(self._on_card_clicked)
            card.rename_requested.connect(self.rename_product_dialog)
            card.delete_requested.connect(self.delete_product_confirm)
            row = index // GRID_COLUMNS
            col = index % GRID_COLUMNS
            self.grid_layout.addWidget(card, row, col)
            self._cards[product.id] = card

            image_path = models.get_product_image_path(product)
            loader = ThumbnailLoader(
                str(product.id),
                image_path,
                THUMB_SIZE,
                self._thumb_signals,
                generation,
                self._load_generation,
            )
            self._thread_pool.start(loader)

    @Slot(str, QPixmap)
    def _on_thumbnail_loaded(self, key: str, pixmap: QPixmap) -> None:
        try:
            product_id = int(key)
        except ValueError:
            return
        card = self._cards.get(product_id)
        if card is not None:
            card.set_pixmap(pixmap)

    def _on_category_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        self._current_filter = current.data(Qt.ItemDataRole.UserRole)
        self.refresh_products()

    def _on_card_clicked(self, product_id: int, event: QMouseEvent) -> None:
        modifiers = event.modifiers()
        card = self._cards.get(product_id)
        if card is None:
            return

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            card.set_selected(not card.is_selected())
            self._last_clicked_id = product_id
        elif modifiers & Qt.KeyboardModifier.ShiftModifier and self._last_clicked_id is not None:
            ids = list(self._cards.keys())
            if product_id in ids and self._last_clicked_id in ids:
                start = ids.index(self._last_clicked_id)
                end = ids.index(product_id)
                if start > end:
                    start, end = end, start
                for pid in ids[start : end + 1]:
                    self._cards[pid].set_selected(True)
        else:
            for c in self._cards.values():
                c.set_selected(False)
            card.set_selected(True)
            self._last_clicked_id = product_id

    def selected_product_ids(self) -> list[int]:
        return [pid for pid, card in self._cards.items() if card.is_selected()]

    def create_category_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "新建产品类", "名称:")
        if not ok or not name.strip():
            return
        try:
            models.create_category(name)
            self.refresh_categories()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def _category_context_menu(self, pos: QPoint) -> None:
        item = self.category_list.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data in (FILTER_ALL, FILTER_UNCATEGORIZED):
            return

        category_id = int(data)
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        action = menu.exec(self.category_list.mapToGlobal(pos))
        if action == rename_action:
            self._rename_category(category_id)
        elif action == delete_action:
            self._delete_category(category_id)

    def _rename_category(self, category_id: int) -> None:
        categories = {c.id: c for c in models.list_categories()}
        category = categories.get(category_id)
        if category is None:
            return
        name, ok = QInputDialog.getText(
            self, "重命名产品类", "名称:", text=category.name
        )
        if not ok or not name.strip():
            return
        try:
            models.rename_category(category_id, name)
            self.refresh_categories()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def _delete_category(self, category_id: int) -> None:
        categories = {c.id: c for c in models.list_categories()}
        category = categories.get(category_id)
        if category is None:
            return
        count = models.count_products_in_category(category_id)
        if count > 0:
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"产品类「{category.name}」下有 {count} 个产品，删除后产品将变为未归类。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定删除产品类「{category.name}」？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            models.delete_category(category_id)
            self.refresh_categories()
            self.refresh_products()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def import_images_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        msg = QMessageBox(self)
        msg.setWindowTitle("导入图片")
        msg.setText("选择导入方式")
        files_btn = msg.addButton("选择文件", QMessageBox.ButtonRole.AcceptRole)
        folder_btn = msg.addButton("选择文件夹", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        paths: list[Path] = []

        if clicked == files_btn:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "选择图片",
                "",
                "图片 (*.jpg *.jpeg *.png *.bmp *.webp *.gif)",
            )
            paths = [Path(f) for f in files]
        elif clicked == folder_btn:
            folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
            if folder:
                paths = [Path(folder)]
        else:
            return

        if not paths:
            return

        try:
            products, errors, skipped = models.batch_import(paths)
            self.refresh_categories()
            self.refresh_products()
            message = f"成功导入 {len(products)} 张图片。"
            if skipped:
                message += f"\n跳过 {len(skipped)} 张重复图片。"
                message += "\n" + "\n".join(skipped[:10])
                if len(skipped) > 10:
                    message += f"\n... 共 {len(skipped)} 张跳过"
            if errors:
                message += "\n\n以下文件导入失败:\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    message += f"\n... 共 {len(errors)} 个错误"
            QMessageBox.information(self, "导入完成", message)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))

    def _category_drag_enter(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def _category_drop_event(self, event) -> None:
        item = self.category_list.itemAt(event.position().toPoint())
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data == FILTER_ALL:
            event.ignore()
            return
        if data == FILTER_UNCATEGORIZED:
            category_id = None
        else:
            category_id = int(data)

        try:
            product_id = int(event.mimeData().text())
        except ValueError:
            event.ignore()
            return

        product_ids = self.selected_product_ids()
        if product_id not in product_ids:
            product_ids = [product_id]

        try:
            models.move_products(product_ids, category_id)
            self.refresh_categories()
            self.refresh_products()
            event.acceptProposedAction()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def move_selected_products(self) -> None:
        product_ids = self.selected_product_ids()
        if not product_ids:
            QMessageBox.information(self, "提示", "请先选择要移动的产品。")
            return

        categories = models.list_categories()
        if not categories:
            reply = QMessageBox.question(
                self,
                "提示",
                "尚无产品类，是否先创建一个？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.create_category_dialog()
                categories = models.list_categories()
            if not categories:
                return

        dialog = CategorySelectDialog(categories, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            models.move_products(product_ids, dialog.selected_category_id)
            self.refresh_categories()
            self.refresh_products()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def rename_product_dialog(self, product: Product) -> None:
        name, ok = QInputDialog.getText(
            self, "重命名产品", "名称:", text=product.name
        )
        if not ok or not name.strip():
            return
        try:
            models.rename_product(product.id, name)
            self.refresh_products()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))

    def delete_product_confirm(self, product: Product) -> None:
        product_ids = self.selected_product_ids()
        if product.id not in product_ids:
            product_ids = [product.id]

        if len(product_ids) == 1:
            message = f"确定删除产品「{product.name}」？"
        else:
            message = f"确定删除选中的 {len(product_ids)} 个产品？"

        reply = QMessageBox.question(
            self,
            "确认删除",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            for pid in product_ids:
                models.delete_product(pid)
            self.refresh_categories()
            self.refresh_products()
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))
