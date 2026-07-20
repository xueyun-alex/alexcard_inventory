"""Data models and CRUD operations."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

from db.database import DATA_DIR, PRODUCTS_DIR, TRASH_DIR, get_connection

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
PHASH_SIMILARITY_THRESHOLD = 5


@dataclass
class Category:
    id: int
    name: str
    sort_order: int
    parent_id: int | None
    created_at: str


@dataclass
class Product:
    id: int
    category_id: int | None
    name: str
    image_path: str
    stock: int
    created_at: str


@dataclass
class SalesRankingRow:
    product_id: int
    name: str
    image_path: str
    sold_qty: int


@dataclass
class ImportDuplicate:
    source_path: Path
    source_name: str
    existing_product: Product
    reason: str


@dataclass
class InboundMatch:
    source_path: Path
    source_name: str
    existing_product: Product
    reason: str
    file_hash: str


@dataclass
class InboundMatchGroup:
    source_path: Path
    source_name: str
    existing_product: Product
    reason: str
    quantity: int
    source_paths: list[Path]


def _row_to_category(row: sqlite3.Row) -> Category:
    return Category(
        id=row["id"],
        name=row["name"],
        sort_order=row["sort_order"],
        parent_id=row["parent_id"],
        created_at=row["created_at"],
    )


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(
        id=row["id"],
        category_id=row["category_id"],
        name=row["name"],
        image_path=row["image_path"],
        stock=row["stock"],
        created_at=row["created_at"],
    )


def create_category(name: str, parent_id: int | None = None) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("产品类名称不能为空")
    from db import changelog

    with get_connection() as conn:
        parent_name: str | None = None
        if parent_id is not None:
            parent_row = conn.execute(
                "SELECT name, parent_id FROM categories WHERE id = ?",
                (parent_id,),
            ).fetchone()
            if parent_row is None:
                raise ValueError("父产品类不存在")
            if parent_row["parent_id"] is not None:
                raise ValueError("产品类只支持一级子类")
            parent_name = parent_row["name"]
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
            FROM categories
            WHERE parent_id IS ?
            """,
            (parent_id,),
        ).fetchone()
        sort_order = row["next_order"]
        cursor = conn.execute(
            "INSERT INTO categories (name, sort_order, parent_id) VALUES (?, ?, ?)",
            (name, sort_order, parent_id),
        )
        category_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        category = _row_to_category(row)
        changelog.record_change(
            "category_create",
            (
                f"新建子类：{parent_name} / {category.name}"
                if parent_name is not None
                else f"新建产品类：{category.name}"
            ),
            {
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "sort_order": category.sort_order,
                    "parent_id": category.parent_id,
                    "created_at": category.created_at,
                }
            },
            conn=conn,
        )
        conn.commit()
        return category


def rename_category(category_id: int, name: str) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("产品类名称不能为空")
    from db import changelog

    with get_connection() as conn:
        old_row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if old_row is None:
            raise ValueError("产品类不存在")
        old_name = old_row["name"]
        conn.execute(
            "UPDATE categories SET name = ? WHERE id = ?",
            (name, category_id),
        )
        row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        category = _row_to_category(row)
        changelog.record_change(
            "category_rename",
            f"产品类重命名：{old_name} → {name}",
            {
                "category_id": category_id,
                "old_name": old_name,
                "new_name": name,
            },
            conn=conn,
        )
        conn.commit()
        return category


def count_products_in_category(category_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM products
            WHERE category_id = ?
               OR category_id IN (
                   SELECT id FROM categories WHERE parent_id = ?
               )
            """,
            (category_id, category_id),
        ).fetchone()
        return row["cnt"]


def count_products_by_category() -> dict[int | None, int]:
    """Return product counts keyed by category_id. None key = uncategorized."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT category_id, COUNT(*) AS cnt FROM products GROUP BY category_id"
        ).fetchall()
        return {row["category_id"]: row["cnt"] for row in rows}


def get_product_stats_by_category() -> dict[int | None, tuple[int, int]]:
    """Return direct stats for children and rolled-up stats for parent categories."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT category_id, COUNT(*) AS product_count,
                   COALESCE(SUM(stock), 0) AS total_stock
            FROM products
            GROUP BY category_id
            """
        ).fetchall()
        stats = {
            row["category_id"]: (row["product_count"], row["total_stock"])
            for row in rows
        }
        categories = conn.execute(
            "SELECT id, parent_id FROM categories WHERE parent_id IS NOT NULL"
        ).fetchall()
        for category in categories:
            child_count, child_stock = stats.get(category["id"], (0, 0))
            parent_count, parent_stock = stats.get(category["parent_id"], (0, 0))
            stats[category["parent_id"]] = (
                parent_count + child_count,
                parent_stock + child_stock,
            )
        return stats


def delete_category(category_id: int) -> int:
    """Delete category. Returns count of products that were in this category."""
    from db import changelog

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row is None:
            raise ValueError("产品类不存在")
        child_row = conn.execute(
            "SELECT name FROM categories WHERE parent_id = ? ORDER BY sort_order, id LIMIT 1",
            (category_id,),
        ).fetchone()
        if child_row is not None:
            raise ValueError("该产品类下还有子类，请先删除子类")
        affected_rows = conn.execute(
            "SELECT id FROM products WHERE category_id = ?",
            (category_id,),
        ).fetchall()
        affected_product_ids = [r["id"] for r in affected_rows]
        count = len(affected_product_ids)
        category = _row_to_category(row)
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        summary = (
            f"删除产品类：{category.name}（含 {count} 个产品）"
            if count > 0
            else f"删除产品类：{category.name}"
        )
        changelog.record_change(
            "category_delete",
            summary,
            {
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "sort_order": category.sort_order,
                    "parent_id": category.parent_id,
                    "created_at": category.created_at,
                },
                "affected_product_ids": affected_product_ids,
            },
            conn=conn,
        )
        conn.commit()
    return count


def list_categories() -> list[Category]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT child.*
            FROM categories AS child
            LEFT JOIN categories AS parent ON parent.id = child.parent_id
            ORDER BY
                COALESCE(parent.sort_order, child.sort_order),
                COALESCE(parent.id, child.id),
                CASE WHEN child.parent_id IS NULL THEN 0 ELSE 1 END,
                child.sort_order,
                child.id
            """
        ).fetchall()
        return [_row_to_category(row) for row in rows]


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def collect_image_paths(paths: list[Path]) -> list[Path]:
    """Expand folders and filter to image files."""
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        path = Path(path)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if is_image_file(child):
                    resolved = child.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        result.append(child)
        elif is_image_file(path):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(path)
    return result


def expand_inbound_paths(paths: list[Path]) -> list[Path]:
    """Expand folders to image files, preserving duplicate user entries."""
    result: list[Path] = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if is_image_file(child):
                    result.append(child)
        elif is_image_file(path):
            result.append(path)
    return result


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_image_hash(path: Path) -> str:
    with Image.open(path) as image:
        return str(imagehash.phash(image))


def compute_image_hash_pil(image: Image.Image) -> str:
    return str(imagehash.phash(image.convert("RGB")))


def phash_hamming_distance(hash1: str, hash2: str) -> int:
    return imagehash.hex_to_hash(hash1) - imagehash.hex_to_hash(hash2)


def is_visually_similar(
    hash1: str,
    hash2: str,
    threshold: int = PHASH_SIMILARITY_THRESHOLD,
) -> bool:
    return phash_hamming_distance(hash1, hash2) <= threshold


def load_product_hashes() -> tuple[dict[str, Product], list[tuple[str, Product]]]:
    file_hashes: dict[str, Product] = {}
    image_hashes: list[tuple[str, Product]] = []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE file_hash IS NOT NULL OR image_hash IS NOT NULL"
        ).fetchall()
    for row in rows:
        product = _row_to_product(row)
        if row["file_hash"]:
            file_hashes[row["file_hash"]] = product
        if row["image_hash"]:
            image_hashes.append((row["image_hash"], product))
    return file_hashes, image_hashes


def backfill_product_hashes() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, image_path FROM products WHERE file_hash IS NULL OR image_hash IS NULL"
        ).fetchall()
        for row in rows:
            image_path = DATA_DIR / row["image_path"]
            if not image_path.is_file():
                continue
            try:
                file_hash = compute_file_hash(image_path)
                image_hash_value = compute_image_hash(image_path)
            except Exception:
                continue
            conn.execute(
                "UPDATE products SET file_hash = ?, image_hash = ? WHERE id = ?",
                (file_hash, image_hash_value, row["id"]),
            )
        conn.commit()


def _find_duplicate_by_hashes(
    file_hash: str,
    image_hash: str,
    known_file_hashes: dict[str, Product],
    known_image_hashes: list[tuple[str, Product]],
) -> tuple[Product | None, str | None]:
    if file_hash in known_file_hashes:
        return known_file_hashes[file_hash], "内容重复"

    for existing_hash, product in known_image_hashes:
        if is_visually_similar(image_hash, existing_hash):
            return product, "图片相似"

    return None, None


def _product_row_to_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "category_id": row["category_id"],
        "name": row["name"],
        "image_path": row["image_path"],
        "stock": row["stock"],
        "created_at": row["created_at"],
        "file_hash": row["file_hash"],
        "image_hash": row["image_hash"],
    }


def import_product(
    source_path: Path,
    file_hash: str,
    image_hash: str,
) -> Product:
    source_path = Path(source_path)
    if not is_image_file(source_path):
        raise ValueError(f"不支持的图片格式: {source_path.name}")

    name = source_path.stem
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO products (name, image_path, file_hash, image_hash)
            VALUES (?, ?, ?, ?)
            """,
            (name, "", file_hash, image_hash),
        )
        product_id = cursor.lastrowid
        conn.commit()

    product_dir = PRODUCTS_DIR / str(product_id)
    product_dir.mkdir(parents=True, exist_ok=True)
    dest_path = product_dir / f"{source_path.stem}{source_path.suffix.lower()}"
    shutil.copy2(source_path, dest_path)

    relative_path = dest_path.relative_to(PRODUCTS_DIR.parent).as_posix()
    with get_connection() as conn:
        conn.execute(
            "UPDATE products SET image_path = ? WHERE id = ?",
            (relative_path, product_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()

    return _row_to_product(row)


def get_product(product_id: int) -> Product | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_product(row)


def _increment_stock_core(
    connection: sqlite3.Connection,
    product_id: int,
    delta: int,
    source: str,
    image_path: str | None,
) -> tuple[int, int, str]:
    row = connection.execute(
        "SELECT stock, name FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"产品 #{product_id} 不存在")
    stock_before = row["stock"]
    connection.execute(
        "UPDATE products SET stock = stock + ? WHERE id = ?",
        (delta, product_id),
    )
    cursor = connection.execute(
        """
        INSERT INTO inventory_logs (product_id, delta, source, image_path)
        VALUES (?, ?, ?, ?)
        """,
        (product_id, delta, source, image_path),
    )
    return int(cursor.lastrowid), stock_before, row["name"]


def increment_stock(
    product_id: int,
    delta: int,
    source: str,
    image_path: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    record: bool = True,
) -> int:
    """Adjust stock and optionally record a single change log. Returns inventory_log_id."""
    from db import changelog

    def _run(connection: sqlite3.Connection) -> int:
        inventory_log_id, stock_before, product_name = _increment_stock_core(
            connection, product_id, delta, source, image_path
        )
        if record:
            source_label = {"manual": "手动", "inbound": "入库"}.get(source, source)
            sign = f"+{delta}" if delta > 0 else str(delta)
            summary = f"「{product_name}」库存 {sign}（{source_label}）"
            changelog.record_change(
                "stock",
                summary,
                {
                    "product_id": product_id,
                    "delta": delta,
                    "source": source,
                    "inventory_log_id": inventory_log_id,
                    "stock_before": stock_before,
                },
                conn=connection,
            )
        return inventory_log_id

    if conn is not None:
        return _run(conn)

    with get_connection() as connection:
        inventory_log_id = _run(connection)
        connection.commit()
        return inventory_log_id


def adjust_stock_batch(product_ids: list[int], delta: int) -> None:
    """Apply the same stock delta to multiple products as one logged operation."""
    if delta == 0 or not product_ids:
        return
    adjust_stock_items([(product_id, delta) for product_id in product_ids])


def adjust_stock_items(
    items: list[tuple[int, int]],
    *,
    source: str = "manual",
) -> None:
    """Apply per-product stock deltas as one logged operation."""
    items = [(product_id, delta) for product_id, delta in items if delta != 0]
    if not items:
        return
    source = source.strip()
    if not source:
        raise ValueError("库存变更来源不能为空")
    from db import changelog

    with get_connection() as conn:
        entries: list[dict] = []
        for product_id, delta in items:
            inventory_log_id, stock_before, _product_name = _increment_stock_core(
                conn, product_id, delta, source, None
            )
            entries.append(
                {
                    "product_id": product_id,
                    "delta": delta,
                    "source": source,
                    "inventory_log_id": inventory_log_id,
                    "stock_before": stock_before,
                }
            )
        summary = changelog.format_stock_batch_summary(conn, entries, source)
        changelog.record_change(
            "stock_batch",
            summary,
            {"source": source, "entries": entries},
            conn=conn,
        )
        conn.commit()


def apply_inbound_batch(
    items: list[tuple[int, str | None]],
) -> int:
    """Apply multiple inbound increments in one transaction."""
    if not items:
        return 0
    from db import changelog

    with get_connection() as conn:
        entries: list[dict] = []
        for product_id, image_path in items:
            inventory_log_id, stock_before, _product_name = _increment_stock_core(
                conn, product_id, 1, "inbound", image_path
            )
            entries.append(
                {
                    "product_id": product_id,
                    "delta": 1,
                    "source": "inbound",
                    "inventory_log_id": inventory_log_id,
                    "stock_before": stock_before,
                    "image_path": image_path,
                }
            )
        summary = changelog.format_stock_batch_summary(conn, entries, "inbound")
        changelog.record_change(
            "stock_batch",
            summary,
            {"source": "inbound", "entries": entries},
            conn=conn,
        )
        conn.commit()
    return len(items)


def match_inbound_images(
    paths: list[Path],
) -> tuple[list[InboundMatch], list[str]]:
    """Match images against existing products using the same logic as import dedup."""
    matches: list[InboundMatch] = []
    unmatched: list[str] = []
    known_file_hashes, known_image_hashes = load_product_hashes()

    for path in expand_inbound_paths(paths):
        try:
            file_hash = compute_file_hash(path)
            image_hash = compute_image_hash(path)
        except Exception:
            unmatched.append(path.name)
            continue

        existing_product, reason = _find_duplicate_by_hashes(
            file_hash,
            image_hash,
            known_file_hashes,
            known_image_hashes,
        )
        if existing_product is not None and reason is not None:
            matches.append(
                InboundMatch(
                    source_path=path,
                    source_name=path.name,
                    existing_product=existing_product,
                    reason=reason,
                    file_hash=file_hash,
                )
            )
        else:
            unmatched.append(path.name)

    return matches, unmatched


def aggregate_inbound_matches(
    matches: list[InboundMatch],
) -> list[InboundMatchGroup]:
    """Merge matches by product and file content hash."""
    groups: dict[tuple[int, str], InboundMatchGroup] = {}
    order: list[tuple[int, str]] = []
    for match in matches:
        key = (match.existing_product.id, match.file_hash)
        if key not in groups:
            groups[key] = InboundMatchGroup(
                source_path=match.source_path,
                source_name=match.source_name,
                existing_product=match.existing_product,
                reason=match.reason,
                quantity=1,
                source_paths=[match.source_path],
            )
            order.append(key)
            continue
        group = groups[key]
        group.quantity += 1
        group.source_paths.append(match.source_path)
    return [groups[key] for key in order]


def batch_import(
    paths: list[Path],
) -> tuple[list[Product], list[str], list[ImportDuplicate]]:
    """Import multiple images. Returns (products, errors, duplicates)."""
    products: list[Product] = []
    errors: list[str] = []
    duplicates: list[ImportDuplicate] = []
    known_file_hashes, known_image_hashes = load_product_hashes()

    for path in collect_image_paths(paths):
        try:
            file_hash = compute_file_hash(path)
            image_hash = compute_image_hash(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        existing_product, reason = _find_duplicate_by_hashes(
            file_hash,
            image_hash,
            known_file_hashes,
            known_image_hashes,
        )
        if reason:
            if existing_product is None:
                errors.append(f"{path.name}: {reason}")
            else:
                duplicates.append(
                    ImportDuplicate(
                        source_path=path,
                        source_name=path.name,
                        existing_product=existing_product,
                        reason=reason,
                    )
                )
            continue

        try:
            product = import_product(path, file_hash, image_hash)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        products.append(product)
        known_file_hashes[file_hash] = product
        known_image_hashes.append((image_hash, product))

    if products:
        from db import changelog

        with get_connection() as conn:
            payloads = []
            for product in products:
                row = conn.execute(
                    "SELECT * FROM products WHERE id = ?", (product.id,)
                ).fetchone()
                if row is not None:
                    payloads.append(_product_row_to_payload(row))
            if not payloads:
                return products, errors, duplicates
            if len(payloads) == 1:
                product = payloads[0]
                changelog.record_change(
                    "product_create",
                    f"新增产品：{product['name']}",
                    {"product": product},
                    conn=conn,
                )
            else:
                summary = changelog.format_product_create_batch_summary(conn, payloads)
                changelog.record_change(
                    "product_create_batch",
                    summary,
                    {"products": payloads},
                    conn=conn,
                )
            conn.commit()

    return products, errors, duplicates


def list_products(category_id: int | None = None) -> list[Product]:
    with get_connection() as conn:
        if category_id is None:
            rows = conn.execute(
                "SELECT * FROM products ORDER BY id DESC"
            ).fetchall()
        elif category_id == -1:
            rows = conn.execute(
                "SELECT * FROM products WHERE category_id IS NULL ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM products
                WHERE category_id = ?
                   OR category_id IN (
                       SELECT id FROM categories WHERE parent_id = ?
                   )
                ORDER BY id DESC
                """,
                (category_id, category_id),
            ).fetchall()
        return [_row_to_product(row) for row in rows]


def move_products(product_ids: list[int], category_id: int | None) -> None:
    if not product_ids:
        return
    from db import changelog

    placeholders = ",".join("?" * len(product_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, category_id FROM products WHERE id IN ({placeholders})",
            product_ids,
        ).fetchall()
        moves = [
            {
                "product_id": row["id"],
                "old_category_id": row["category_id"],
                "new_category_id": category_id,
            }
            for row in rows
        ]
        if not moves:
            return
        conn.execute(
            f"UPDATE products SET category_id = ? WHERE id IN ({placeholders})",
            [category_id, *product_ids],
        )
        summary = changelog.format_category_move_summary(conn, moves)
        changelog.record_change(
            "category_move",
            summary,
            {"moves": moves},
            conn=conn,
        )
        conn.commit()


def rename_product(product_id: int, name: str) -> Product:
    name = name.strip()
    if not name:
        raise ValueError("产品名称不能为空")
    from db import changelog

    with get_connection() as conn:
        old_row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if old_row is None:
            raise ValueError("产品不存在")
        old_name = old_row["name"]
        conn.execute(
            "UPDATE products SET name = ? WHERE id = ?",
            (name, product_id),
        )
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        product = _row_to_product(row)
        changelog.record_change(
            "product_rename",
            f"产品重命名：{old_name} → {name}",
            {
                "product_id": product_id,
                "old_name": old_name,
                "new_name": name,
            },
            conn=conn,
        )
        conn.commit()
        return product


def delete_product(product_id: int) -> None:
    import json

    from db import changelog

    product_dir = PRODUCTS_DIR / str(product_id)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ValueError("产品不存在")

        product_data = {
            "id": row["id"],
            "category_id": row["category_id"],
            "name": row["name"],
            "image_path": row["image_path"],
            "stock": row["stock"],
            "created_at": row["created_at"],
            "file_hash": row["file_hash"],
            "image_hash": row["image_hash"],
        }
        log_id = changelog.record_change(
            "product_delete",
            f"删除产品：{row['name']}",
            {"product": product_data, "trash_dir": ""},
            conn=conn,
        )
        trash_dir = TRASH_DIR / str(log_id) / str(product_id)
        trash_dir.mkdir(parents=True, exist_ok=True)
        if product_dir.exists():
            for item in product_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, trash_dir / item.name)
        trash_rel = trash_dir.relative_to(DATA_DIR).as_posix()
        conn.execute(
            "UPDATE change_logs SET payload_json = ? WHERE id = ?",
            (
                json.dumps(
                    {"product": product_data, "trash_dir": trash_rel},
                    ensure_ascii=False,
                ),
                log_id,
            ),
        )
        conn.execute(
            "DELETE FROM inventory_logs WHERE product_id = ?", (product_id,)
        )
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()

    if product_dir.exists():
        shutil.rmtree(product_dir)


def get_product_image_path(product: Product) -> Path:
    from db.database import DATA_DIR

    return DATA_DIR / product.image_path


def list_sales_ranking(start: str, end: str) -> list[SalesRankingRow]:
    """Rank products by summed manual stock decreases in [start, end]."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.image_path, SUM(-il.delta) AS sold_qty
            FROM inventory_logs il
            JOIN products p ON p.id = il.product_id
            WHERE il.source = 'manual'
              AND il.delta < 0
              AND il.reverted_at IS NULL
              AND il.created_at >= ?
              AND il.created_at <= ?
            GROUP BY p.id
            ORDER BY sold_qty DESC
            """,
            (start, end),
        ).fetchall()
    return [
        SalesRankingRow(
            product_id=row["id"],
            name=row["name"],
            image_path=row["image_path"],
            sold_qty=int(row["sold_qty"]),
        )
        for row in rows
    ]
