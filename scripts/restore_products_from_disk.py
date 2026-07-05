"""Rebuild products table from data/products/{id}/ image directories."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.database import PRODUCTS_DIR, get_connection, init_db
from db.models import IMAGE_EXTENSIONS, backfill_product_hashes, is_image_file


def _find_product_image(product_dir: Path) -> Path | None:
    for child in sorted(product_dir.iterdir()):
        if is_image_file(child):
            return child
    return None


def restore_products_from_disk(*, clear_existing: bool = True) -> int:
    init_db()

    restored = 0
    with get_connection() as conn:
        if clear_existing:
            conn.execute("DELETE FROM inventory_logs")
            conn.execute("DELETE FROM products")
            conn.commit()

        for product_dir in sorted(PRODUCTS_DIR.iterdir(), key=lambda p: int(p.name)):
            if not product_dir.is_dir() or not product_dir.name.isdigit():
                continue

            image_path = _find_product_image(product_dir)
            if image_path is None:
                continue

            product_id = int(product_dir.name)
            relative_path = image_path.relative_to(PRODUCTS_DIR.parent).as_posix()
            name = image_path.stem

            conn.execute(
                """
                INSERT INTO products (id, category_id, name, image_path, stock)
                VALUES (?, NULL, ?, ?, 0)
                """,
                (product_id, name, relative_path),
            )
            restored += 1

        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name = 'products'"
        )
        max_id = conn.execute("SELECT MAX(id) FROM products").fetchone()[0]
        if max_id is not None:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('products', ?)",
                (max_id,),
            )
        conn.commit()

    backfill_product_hashes()
    return restored


def main() -> None:
    count = restore_products_from_disk()
    print(f"Restored {count} products from disk.")


if __name__ == "__main__":
    main()
