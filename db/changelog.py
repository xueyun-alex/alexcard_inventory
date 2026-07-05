"""Change log recording and rollback."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from db.database import DATA_DIR, PRODUCTS_DIR, TRASH_DIR, get_connection

KIND_LABELS: dict[str, str] = {
    "stock": "库存",
    "stock_batch": "库存",
    "category_move": "归类",
    "category_create": "新建产品类",
    "category_rename": "重命名产品类",
    "category_delete": "删除产品类",
    "product_rename": "重命名产品",
    "product_delete": "删除产品",
}


@dataclass
class ChangeLog:
    id: int
    kind: str
    summary: str
    payload: dict
    created_at: str
    reverted_at: str | None


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_change_log(row: sqlite3.Row) -> ChangeLog:
    return ChangeLog(
        id=row["id"],
        kind=row["kind"],
        summary=row["summary"],
        payload=json.loads(row["payload_json"]),
        created_at=row["created_at"],
        reverted_at=row["reverted_at"],
    )


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def record_change(
    kind: str,
    summary: str,
    payload: dict,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    payload_json = json.dumps(payload, ensure_ascii=False)
    if conn is not None:
        cursor = conn.execute(
            """
            INSERT INTO change_logs (kind, summary, payload_json)
            VALUES (?, ?, ?)
            """,
            (kind, summary, payload_json),
        )
        return int(cursor.lastrowid)

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO change_logs (kind, summary, payload_json)
            VALUES (?, ?, ?)
            """,
            (kind, summary, payload_json),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_change_logs(limit: int = 200) -> list[ChangeLog]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM change_logs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_change_log(row) for row in rows]


def get_change_log(log_id: int) -> ChangeLog | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM change_logs WHERE id = ?", (log_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_change_log(row)


def _category_name(conn: sqlite3.Connection, category_id: int | None) -> str:
    if category_id is None:
        return "未归类"
    row = conn.execute(
        "SELECT name FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if row is None:
        return f"产品类#{category_id}"
    return row["name"]


def format_category_move_summary(
    conn: sqlite3.Connection,
    moves: list[dict],
) -> str:
    count = len(moves)
    if count == 1:
        move = moves[0]
        old_name = _category_name(conn, move["old_category_id"])
        new_name = _category_name(conn, move["new_category_id"])
        row = conn.execute(
            "SELECT name FROM products WHERE id = ?", (move["product_id"],)
        ).fetchone()
        product_name = row["name"] if row else f"产品#{move['product_id']}"
        return f"「{product_name}」：{old_name} → {new_name}"
    if not moves:
        return "移动产品归类"
    old_ids = {m["old_category_id"] for m in moves}
    new_ids = {m["new_category_id"] for m in moves}
    if len(old_ids) == 1 and len(new_ids) == 1:
        old_name = _category_name(conn, next(iter(old_ids)))
        new_name = _category_name(conn, next(iter(new_ids)))
        return f"{count} 个产品：{old_name} → {new_name}"
    return f"移动 {count} 个产品归类"


def format_stock_batch_summary(
    conn: sqlite3.Connection,
    entries: list[dict],
    source: str,
) -> str:
    source_label = {"manual": "手动", "inbound": "入库"}.get(source, source)
    if len(entries) == 1:
        entry = entries[0]
        row = conn.execute(
            "SELECT name FROM products WHERE id = ?", (entry["product_id"],)
        ).fetchone()
        name = row["name"] if row else f"产品#{entry['product_id']}"
        delta = entry["delta"]
        sign = f"+{delta}" if delta > 0 else str(delta)
        return f"「{name}」库存 {sign}（{source_label}）"
    return f"{len(entries)} 项库存变更（{source_label}）"


def check_revert_would_negative_stock(log: ChangeLog) -> list[tuple[str, int]]:
    """Return list of (product_name, resulting_stock) that would be negative."""
    warnings: list[tuple[str, int]] = []
    entries: list[dict]
    if log.kind == "stock":
        entries = [log.payload]
    elif log.kind == "stock_batch":
        entries = log.payload.get("entries", [])
    else:
        return warnings

    with get_connection() as conn:
        for entry in entries:
            product_id = entry["product_id"]
            delta = entry["delta"]
            row = conn.execute(
                "SELECT name, stock FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if row is None:
                continue
            resulting = row["stock"] - delta
            if resulting < 0:
                warnings.append((row["name"], resulting))
    return warnings


def revert_change(log_id: int) -> None:
    log = get_change_log(log_id)
    if log is None:
        raise ValueError("操作记录不存在")
    if log.reverted_at is not None:
        raise ValueError("该操作已回退")

    with get_connection() as conn:
        if log.kind in ("stock", "stock_batch"):
            _revert_stock(conn, log)
        elif log.kind == "category_move":
            _revert_category_move(conn, log)
        elif log.kind == "category_create":
            _revert_category_create(conn, log)
        elif log.kind == "category_rename":
            _revert_category_rename(conn, log)
        elif log.kind == "category_delete":
            _revert_category_delete(conn, log)
        elif log.kind == "product_rename":
            _revert_product_rename(conn, log)
        elif log.kind == "product_delete":
            _revert_product_delete(conn, log)
        else:
            raise ValueError(f"不支持回退的操作类型: {log.kind}")

        conn.execute(
            """
            UPDATE change_logs
            SET reverted_at = ?
            WHERE id = ?
            """,
            (_now_local(), log_id),
        )
        conn.commit()


def _revert_stock(conn: sqlite3.Connection, log: ChangeLog) -> None:
    entries = (
        [log.payload]
        if log.kind == "stock"
        else log.payload.get("entries", [])
    )
    for entry in entries:
        product_id = entry["product_id"]
        delta = entry["delta"]
        row = conn.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"产品 #{product_id} 已不存在，无法回退库存")
        conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ?",
            (delta, product_id),
        )
        inventory_log_id = entry.get("inventory_log_id")
        if inventory_log_id is not None:
            conn.execute(
                """
                UPDATE inventory_logs
                SET reverted_at = ?
                WHERE id = ? AND reverted_at IS NULL
                """,
                (_now_local(), inventory_log_id),
            )


def _revert_category_move(conn: sqlite3.Connection, log: ChangeLog) -> None:
    for move in log.payload.get("moves", []):
        product_id = move["product_id"]
        old_category_id = move["old_category_id"]
        row = conn.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"产品 #{product_id} 已不存在，无法回退归类")
        conn.execute(
            "UPDATE products SET category_id = ? WHERE id = ?",
            (old_category_id, product_id),
        )


def _revert_category_create(conn: sqlite3.Connection, log: ChangeLog) -> None:
    category = log.payload["category"]
    category_id = category["id"]
    row = conn.execute(
        "SELECT id FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if row is None:
        raise ValueError("产品类已不存在，无法回退")
    count_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM products WHERE category_id = ?",
        (category_id,),
    ).fetchone()
    if count_row["cnt"] > 0:
        raise ValueError("产品类下已有产品，无法回退新建操作")
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def _revert_category_rename(conn: sqlite3.Connection, log: ChangeLog) -> None:
    category_id = log.payload["category_id"]
    old_name = log.payload["old_name"]
    row = conn.execute(
        "SELECT id FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if row is None:
        raise ValueError("产品类已不存在，无法回退")
    existing = conn.execute(
        "SELECT id FROM categories WHERE name = ? AND id != ?",
        (old_name, category_id),
    ).fetchone()
    if existing is not None:
        raise ValueError(f"已存在名为「{old_name}」的产品类，无法回退")
    conn.execute(
        "UPDATE categories SET name = ? WHERE id = ?",
        (old_name, category_id),
    )


def _revert_category_delete(conn: sqlite3.Connection, log: ChangeLog) -> None:
    category = log.payload["category"]
    old_name = category["name"]
    existing = conn.execute(
        "SELECT id FROM categories WHERE name = ?", (old_name,)
    ).fetchone()
    if existing is not None:
        raise ValueError(f"已存在名为「{old_name}」的产品类，无法回退")
    cursor = conn.execute(
        """
        INSERT INTO categories (id, name, sort_order, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            category["id"],
            category["name"],
            category["sort_order"],
            category["created_at"],
        ),
    )
    new_category_id = cursor.lastrowid
    target_id = category["id"] if new_category_id == category["id"] else new_category_id
    for product_id in log.payload.get("affected_product_ids", []):
        conn.execute(
            "UPDATE products SET category_id = ? WHERE id = ?",
            (target_id, product_id),
        )


def _revert_product_rename(conn: sqlite3.Connection, log: ChangeLog) -> None:
    product_id = log.payload["product_id"]
    old_name = log.payload["old_name"]
    row = conn.execute(
        "SELECT id FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if row is None:
        raise ValueError("产品已不存在，无法回退")
    conn.execute(
        "UPDATE products SET name = ? WHERE id = ?",
        (old_name, product_id),
    )


def _revert_product_delete(conn: sqlite3.Connection, log: ChangeLog) -> None:
    product = log.payload["product"]
    product_id = product["id"]
    existing = conn.execute(
        "SELECT id FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if existing is not None:
        raise ValueError("产品已存在，无法回退删除")

    trash_rel = log.payload.get("trash_dir")
    if not trash_rel:
        raise ValueError("缺少删除快照，无法回退")
    trash_path = DATA_DIR / trash_rel
    if not trash_path.is_dir():
        raise ValueError("删除快照已丢失，无法回退")

    dest_dir = PRODUCTS_DIR / str(product_id)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(trash_path, dest_dir)

    conn.execute(
        """
        INSERT INTO products (
            id, category_id, name, image_path, stock,
            created_at, file_hash, image_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product["id"],
            product.get("category_id"),
            product["name"],
            product["image_path"],
            product.get("stock", 0),
            product["created_at"],
            product.get("file_hash"),
            product.get("image_hash"),
        ),
    )
