"""Persistent outbound orders and their stock effects."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from db.database import DATA_DIR, get_connection

ORDER_STATUSES = ("待发货", "已发货", "已成交")
PACKAGE_TYPES = ("裸卡", "挂件袋", "带卡砖")


@dataclass(frozen=True)
class OrderItem:
    id: int
    order_id: int
    product_id: int | None
    product_name: str
    image_path: str
    package_type: str
    quantity: int


@dataclass(frozen=True)
class Order:
    id: int
    order_no: str
    status: str
    export_path: str | None
    created_at: str
    updated_at: str
    items: tuple[OrderItem, ...]

    @property
    def product_type_count(self) -> int:
        return len(self.items)

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)


def _row_to_item(row: sqlite3.Row) -> OrderItem:
    return OrderItem(
        id=row["id"],
        order_id=row["order_id"],
        product_id=row["product_id"],
        product_name=row["product_name"],
        image_path=row["image_path"],
        package_type=row["package_type"],
        quantity=row["quantity"],
    )


def _rows_to_orders(
    order_rows: list[sqlite3.Row],
    item_rows: list[sqlite3.Row],
) -> list[Order]:
    items_by_order: dict[int, list[OrderItem]] = {}
    for row in item_rows:
        item = _row_to_item(row)
        items_by_order.setdefault(item.order_id, []).append(item)
    return [
        Order(
            id=row["id"],
            order_no=row["order_no"],
            status=row["status"],
            export_path=row["export_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            items=tuple(items_by_order.get(row["id"], [])),
        )
        for row in order_rows
    ]


def list_orders() -> list[Order]:
    with get_connection() as conn:
        order_rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC, id DESC"
        ).fetchall()
        item_rows = conn.execute(
            "SELECT * FROM order_items ORDER BY order_id DESC, id"
        ).fetchall()
    return _rows_to_orders(order_rows, item_rows)


def get_order(order_id: int) -> Order | None:
    with get_connection() as conn:
        order_row = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            return None
        item_rows = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
    return _rows_to_orders([order_row], item_rows)[0]


def get_order_item_image_path(item: OrderItem) -> Path:
    return DATA_DIR / item.image_path


def safe_filename_part(value: str) -> str:
    invalid = '<>:"/\\|?*'
    result = "".join("_" if char in invalid else char for char in value.strip())
    return result.rstrip(". ") or "货单"


def next_order_number() -> str:
    prefix = datetime.now().strftime("%Y%m%d")
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT order_no FROM orders WHERE order_no LIKE ?",
            (f"{prefix}-%",),
        ).fetchall()
    suffixes: list[int] = []
    for row in rows:
        suffix = row["order_no"].removeprefix(f"{prefix}-")
        if suffix.isdigit():
            suffixes.append(int(suffix))
    return f"{prefix}-{max(suffixes, default=0) + 1:03d}"


def order_number_exists(order_no: str, exclude_order_id: int | None = None) -> bool:
    with get_connection() as conn:
        if exclude_order_id is None:
            row = conn.execute(
                "SELECT 1 FROM orders WHERE order_no = ?",
                (order_no.strip(),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM orders WHERE order_no = ? AND id != ?",
                (order_no.strip(), exclude_order_id),
            ).fetchone()
    return row is not None


def _normalize_items(
    items: list[tuple[int, str, int]],
) -> list[tuple[int, str, int]]:
    normalized: list[tuple[int, str, int]] = []
    seen: set[int] = set()
    for product_id, package_type, quantity in items:
        if product_id in seen:
            raise ValueError("同一个商品不能在一张货单中重复")
        if package_type not in PACKAGE_TYPES:
            raise ValueError(f"不支持的包装类型：{package_type}")
        if quantity <= 0:
            raise ValueError("商品数量必须大于 0")
        seen.add(product_id)
        normalized.append((product_id, package_type, quantity))
    if not normalized:
        raise ValueError("货单至少需要一个商品")
    return normalized


def _product_snapshots(
    conn: sqlite3.Connection,
    product_ids: list[int],
) -> dict[int, sqlite3.Row]:
    placeholders = ",".join("?" * len(product_ids))
    rows = conn.execute(
        f"SELECT id, name, image_path FROM products WHERE id IN ({placeholders})",
        product_ids,
    ).fetchall()
    products = {row["id"]: row for row in rows}
    missing = [product_id for product_id in product_ids if product_id not in products]
    if missing:
        raise ValueError(f"商品 #{missing[0]} 已不存在")
    return products


def _snapshot_order(conn: sqlite3.Connection, order_id: int) -> dict:
    order_row = conn.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order_row is None:
        raise ValueError("货单不存在")
    item_rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()
    return {
        "id": order_row["id"],
        "order_no": order_row["order_no"],
        "status": order_row["status"],
        "export_path": order_row["export_path"],
        "created_at": order_row["created_at"],
        "updated_at": order_row["updated_at"],
        "items": [
            {
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "image_path": row["image_path"],
                "package_type": row["package_type"],
                "quantity": row["quantity"],
            }
            for row in item_rows
        ],
    }


def create_order(
    order_no: str,
    items: list[tuple[int, str, int]],
    export_path: str | None,
) -> Order:
    order_no = order_no.strip()
    if not order_no:
        raise ValueError("货单编号不能为空")
    items = _normalize_items(items)
    from db import changelog
    from db.models import _increment_stock_core

    try:
        with get_connection() as conn:
            products = _product_snapshots(
                conn,
                [product_id for product_id, _package, _quantity in items],
            )
            cursor = conn.execute(
                """
                INSERT INTO orders (order_no, status, export_path)
                VALUES (?, '待发货', ?)
                """,
                (order_no, export_path),
            )
            order_id = int(cursor.lastrowid)
            entries: list[dict] = []
            for product_id, package_type, quantity in items:
                product = products[product_id]
                item_cursor = conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, product_name, image_path,
                        package_type, quantity
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        product_id,
                        product["name"],
                        product["image_path"],
                        package_type,
                        quantity,
                    ),
                )
                inventory_log_id, stock_before, _name = _increment_stock_core(
                    conn,
                    product_id,
                    -quantity,
                    "order",
                    None,
                )
                entries.append(
                    {
                        "product_id": product_id,
                        "delta": -quantity,
                        "source": "order",
                        "inventory_log_id": inventory_log_id,
                        "stock_before": stock_before,
                        "order_item_id": int(item_cursor.lastrowid),
                    }
                )
            changelog.record_change(
                "order_create",
                f"新建货单 {order_no}（{len(items)} 种，共 "
                f"{sum(item[2] for item in items)} 件）",
                {
                    "order_id": order_id,
                    "order_no": order_no,
                    "entries": entries,
                },
                conn=conn,
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        if "orders.order_no" in str(exc):
            raise ValueError(f"货单编号「{order_no}」已存在") from exc
        raise
    order = get_order(order_id)
    if order is None:
        raise RuntimeError("货单创建后无法读取")
    return order


def update_order(
    order_id: int,
    order_no: str,
    status: str,
    items: list[tuple[int, str, int]],
) -> Order:
    order_no = order_no.strip()
    if not order_no:
        raise ValueError("货单编号不能为空")
    if status not in ORDER_STATUSES:
        raise ValueError(f"不支持的货单状态：{status}")
    items = _normalize_items(items)
    from db import changelog
    from db.models import _increment_stock_core

    try:
        with get_connection() as conn:
            old = _snapshot_order(conn, order_id)
            products = _product_snapshots(
                conn,
                [product_id for product_id, _package, _quantity in items],
            )
            old_quantities = {
                item["product_id"]: item["quantity"]
                for item in old["items"]
                if item["product_id"] is not None
            }
            new_quantities = {
                product_id: quantity
                for product_id, _package, quantity in items
            }
            stock_deltas = {
                product_id: old_quantities.get(product_id, 0)
                - new_quantities.get(product_id, 0)
                for product_id in set(old_quantities) | set(new_quantities)
            }

            conn.execute(
                """
                UPDATE orders
                SET order_no = ?, status = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (order_no, status, order_id),
            )
            conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            for product_id, package_type, quantity in items:
                product = products[product_id]
                conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, product_name, image_path,
                        package_type, quantity
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        product_id,
                        product["name"],
                        product["image_path"],
                        package_type,
                        quantity,
                    ),
                )

            entries: list[dict] = []
            for product_id, delta in stock_deltas.items():
                if delta == 0:
                    continue
                inventory_log_id, stock_before, _name = _increment_stock_core(
                    conn,
                    product_id,
                    delta,
                    "order",
                    None,
                )
                entries.append(
                    {
                        "product_id": product_id,
                        "delta": delta,
                        "source": "order",
                        "inventory_log_id": inventory_log_id,
                        "stock_before": stock_before,
                    }
                )

            new = _snapshot_order(conn, order_id)
            changes: list[str] = []
            if old["order_no"] != order_no:
                changes.append(f"编号 {old['order_no']} → {order_no}")
            if old["status"] != status:
                changes.append(f"状态 {old['status']} → {status}")
            if old["items"] != new["items"]:
                changes.append("商品明细")
            changelog.record_change(
                "order_update",
                f"修改货单 {order_no}："
                + ("、".join(changes) if changes else "无变化"),
                {
                    "order_id": order_id,
                    "order_no": order_no,
                    "old_order": old,
                    "new_order": new,
                    "entries": entries,
                },
                conn=conn,
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        if "orders.order_no" in str(exc):
            raise ValueError(f"货单编号「{order_no}」已存在") from exc
        raise
    order = get_order(order_id)
    if order is None:
        raise RuntimeError("货单修改后无法读取")
    return order


def update_order_status(order_id: int, status: str) -> Order:
    order = get_order(order_id)
    if order is None:
        raise ValueError("货单不存在")
    items = [
        (item.product_id, item.package_type, item.quantity)
        for item in order.items
        if item.product_id is not None
    ]
    if len(items) != len(order.items):
        raise ValueError("货单中有已删除商品，请通过编辑窗口处理")
    return update_order(order_id, order.order_no, status, items)


def set_export_path(order_id: int, export_path: str) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE orders
            SET export_path = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (export_path, order_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("货单不存在")
        conn.commit()


def delete_order(order_id: int) -> None:
    """Delete an order and restore its current quantities to stock."""
    from db import changelog
    from db.models import _increment_stock_core

    with get_connection() as conn:
        snapshot = _snapshot_order(conn, order_id)
        entries: list[dict] = []
        for item in snapshot["items"]:
            product_id = item.get("product_id")
            if product_id is None:
                continue
            inventory_log_id, stock_before, _name = _increment_stock_core(
                conn,
                product_id,
                item["quantity"],
                "order",
                None,
            )
            entries.append(
                {
                    "product_id": product_id,
                    "delta": item["quantity"],
                    "source": "order",
                    "inventory_log_id": inventory_log_id,
                    "stock_before": stock_before,
                }
            )
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        changelog.record_change(
            "order_delete",
            f"删除货单 {snapshot['order_no']}，恢复库存 "
            f"{sum(item['quantity'] for item in snapshot['items'])} 件",
            {
                "order_id": order_id,
                "order_no": snapshot["order_no"],
                "old_order": snapshot,
                "entries": entries,
            },
            conn=conn,
        )
        conn.commit()


def restore_order_snapshot(conn: sqlite3.Connection, snapshot: dict) -> None:
    order_id = snapshot["id"]
    existing = conn.execute(
        "SELECT id FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if existing is None:
        raise ValueError("货单已不存在，无法回退修改")
    conflict = conn.execute(
        "SELECT id FROM orders WHERE order_no = ? AND id != ?",
        (snapshot["order_no"], order_id),
    ).fetchone()
    if conflict is not None:
        raise ValueError(f"货单编号「{snapshot['order_no']}」已被占用")
    conn.execute(
        """
        UPDATE orders
        SET order_no = ?, status = ?,
            created_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot["order_no"],
            snapshot["status"],
            snapshot["created_at"],
            snapshot["updated_at"],
            order_id,
        ),
    )
    conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
    for item in snapshot["items"]:
        conn.execute(
            """
            INSERT INTO order_items (
                order_id, product_id, product_name, image_path,
                package_type, quantity
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                item.get("product_id"),
                item["product_name"],
                item["image_path"],
                item["package_type"],
                item["quantity"],
            ),
        )


def insert_order_snapshot(conn: sqlite3.Connection, snapshot: dict) -> None:
    order_id = snapshot["id"]
    existing = conn.execute(
        "SELECT id FROM orders WHERE id = ? OR order_no = ?",
        (order_id, snapshot["order_no"]),
    ).fetchone()
    if existing is not None:
        raise ValueError("货单编号或货单记录已存在，无法回退删除")
    conn.execute(
        """
        INSERT INTO orders (
            id, order_no, status, export_path, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            snapshot["order_no"],
            snapshot["status"],
            snapshot.get("export_path"),
            snapshot["created_at"],
            snapshot["updated_at"],
        ),
    )
    for item in snapshot["items"]:
        conn.execute(
            """
            INSERT INTO order_items (
                order_id, product_id, product_name, image_path,
                package_type, quantity
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                item.get("product_id"),
                item["product_name"],
                item["image_path"],
                item["package_type"],
                item["quantity"],
            ),
        )
