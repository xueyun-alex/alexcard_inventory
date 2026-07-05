"""Operation history tab with rollback."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from db import changelog


class HistoryTab(QWidget):
    data_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._logs: list[changelog.ChangeLog] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("最近 200 条操作记录，可回退到变更前状态。"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "类型", "说明", "操作"])
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
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        self._logs = changelog.list_change_logs()
        self.table.setRowCount(len(self._logs))
        for row_index, log in enumerate(self._logs):
            self.table.setItem(row_index, 0, QTableWidgetItem(log.created_at))
            self.table.setItem(
                row_index,
                1,
                QTableWidgetItem(changelog.kind_label(log.kind)),
            )
            self.table.setItem(row_index, 2, QTableWidgetItem(log.summary))

            if log.reverted_at:
                status = QPushButton("已回退")
                status.setEnabled(False)
            else:
                status = QPushButton("回退")
                status.clicked.connect(
                    lambda _checked=False, log_id=log.id: self._revert(log_id)
                )
            self.table.setCellWidget(row_index, 3, status)

    def _revert(self, log_id: int) -> None:
        log = changelog.get_change_log(log_id)
        if log is None:
            QMessageBox.warning(self, "错误", "操作记录不存在。")
            return
        if log.reverted_at is not None:
            QMessageBox.information(self, "提示", "该操作已回退。")
            self.refresh()
            return

        negative = changelog.check_revert_would_negative_stock(log)
        create_warnings = changelog.check_revert_product_create_warnings(log)
        if negative:
            details = "\n".join(
                f"· {name} 将变为 {stock}" for name, stock in negative
            )
            reply = QMessageBox.question(
                self,
                "确认回退",
                f"回退后以下产品库存将为负数：\n{details}\n\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        elif create_warnings:
            details = "\n".join(f"· {warning}" for warning in create_warnings)
            reply = QMessageBox.question(
                self,
                "确认回退",
                f"回退新增产品将删除对应产品：\n{details}\n\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        else:
            reply = QMessageBox.question(
                self,
                "确认回退",
                f"确定回退此操作？\n\n{log.summary}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            changelog.revert_change(log_id)
        except ValueError as exc:
            QMessageBox.warning(self, "无法回退", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "回退失败", str(exc))
            return

        self.refresh()
        self.data_changed.emit()
        QMessageBox.information(self, "回退成功", "已恢复到变更前状态。")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
