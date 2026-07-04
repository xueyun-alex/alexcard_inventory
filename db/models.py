"""Data models and CRUD operations."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from db.database import PRODUCTS_DIR, get_connection

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}


@dataclass
class Category:
    id: int
    name: str
    sort_order: int
    created_at: str


@dataclass
class Product:
    id: int
    category_id: int | None
    name: str
    image_path: str
    stock: int
    created_at: str


def _row_to_category(row: sqlite3.Row) -> Category:
    return Category(
        id=row["id"],
        name=row["name"],
        sort_order=row["sort_order"],
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


def create_category(name: str) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("产品类名称不能为空")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM categories"
        ).fetchone()
        sort_order = row["next_order"]
        cursor = conn.execute(
            "INSERT INTO categories (name, sort_order) VALUES (?, ?)",
            (name, sort_order),
        )
        conn.commit()
        category_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        return _row_to_category(row)


def rename_category(category_id: int, name: str) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("产品类名称不能为空")
    with get_connection() as conn:
        conn.execute(
            "UPDATE categories SET name = ? WHERE id = ?",
            (name, category_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row is None:
            raise ValueError("产品类不存在")
        return _row_to_category(row)


def count_products_in_category(category_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM products WHERE category_id = ?",
            (category_id,),
        ).fetchone()
        return row["cnt"]


def delete_category(category_id: int) -> int:
    """Delete category. Returns count of products that were in this category."""
    count = count_products_in_category(category_id)
    with get_connection() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
    return count


def list_categories() -> list[Category]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, id"
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


def import_product(source_path: Path) -> Product:
    source_path = Path(source_path)
    if not is_image_file(source_path):
        raise ValueError(f"不支持的图片格式: {source_path.name}")

    name = source_path.stem
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO products (name, image_path) VALUES (?, ?)",
            (name, ""),
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


def batch_import(paths: list[Path]) -> tuple[list[Product], list[str]]:
    """Import multiple images. Returns (successful products, error messages)."""
    products: list[Product] = []
    errors: list[str] = []
    for path in collect_image_paths(paths):
        try:
            products.append(import_product(path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return products, errors


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
                "SELECT * FROM products WHERE category_id = ? ORDER BY id DESC",
                (category_id,),
            ).fetchall()
        return [_row_to_product(row) for row in rows]


def move_products(product_ids: list[int], category_id: int | None) -> None:
    if not product_ids:
        return
    placeholders = ",".join("?" * len(product_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE products SET category_id = ? WHERE id IN ({placeholders})",
            [category_id, *product_ids],
        )
        conn.commit()


def rename_product(product_id: int, name: str) -> Product:
    name = name.strip()
    if not name:
        raise ValueError("产品名称不能为空")
    with get_connection() as conn:
        conn.execute(
            "UPDATE products SET name = ? WHERE id = ?",
            (name, product_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ValueError("产品不存在")
        return _row_to_product(row)


def delete_product(product_id: int) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT image_path FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ValueError("产品不存在")
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()

    product_dir = PRODUCTS_DIR / str(product_id)
    if product_dir.exists():
        shutil.rmtree(product_dir)


def get_product_image_path(product: Product) -> Path:
    from db.database import DATA_DIR

    return DATA_DIR / product.image_path
