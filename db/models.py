"""Data models and CRUD operations."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

from db.database import DATA_DIR, PRODUCTS_DIR, get_connection

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
PHASH_SIMILARITY_THRESHOLD = 5


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


@dataclass
class ProductMatchRow:
    id: int
    name: str
    image_path: str
    stock: int
    image_hash: str | None
    embedding: bytes | None


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


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_image_hash(path: Path) -> str:
    with Image.open(path) as image:
        return str(imagehash.phash(image))


def compute_image_hash_pil(image: Image.Image) -> str:
    return str(imagehash.phash(image.convert("RGB")))


def is_visually_similar(
    hash1: str,
    hash2: str,
    threshold: int = PHASH_SIMILARITY_THRESHOLD,
) -> bool:
    return imagehash.hex_to_hash(hash1) - imagehash.hex_to_hash(hash2) <= threshold


def load_product_hashes() -> tuple[set[str], list[tuple[str, Product]]]:
    file_hashes: set[str] = set()
    image_hashes: list[tuple[str, Product]] = []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE file_hash IS NOT NULL OR image_hash IS NOT NULL"
        ).fetchall()
    for row in rows:
        product = _row_to_product(row)
        if row["file_hash"]:
            file_hashes.add(row["file_hash"])
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
    known_file_hashes: set[str],
    known_image_hashes: list[tuple[str, Product]],
) -> tuple[Product | None, str | None]:
    if file_hash in known_file_hashes:
        return None, "内容重复"

    for existing_hash, product in known_image_hashes:
        if is_visually_similar(image_hash, existing_hash):
            return product, f"图片相似（与「{product.name}」）"

    return None, None


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

    _compute_and_save_embedding(product_id, dest_path)
    return _row_to_product(row)


def _compute_and_save_embedding(product_id: int, image_path: Path) -> None:
    try:
        from core.embedder import ClipEmbedder
        from settings.config import load_config, resolve_config_path

        config = load_config()
        model_path = resolve_config_path(config, "clip_model_path")
        if model_path is None or not model_path.is_file():
            return
        embedder = ClipEmbedder(model_path)
        vec = embedder.embed_path(image_path)
        save_product_embedding(product_id, ClipEmbedder.to_blob(vec))
    except Exception:
        return


def save_product_embedding(product_id: int, blob: bytes) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE products SET embedding = ? WHERE id = ?",
            (blob, product_id),
        )
        conn.commit()


def backfill_product_embeddings() -> None:
    try:
        from core.embedder import ClipEmbedder
        from settings.config import load_config, resolve_config_path

        config = load_config()
        model_path = resolve_config_path(config, "clip_model_path")
        if model_path is None or not model_path.is_file():
            print(
                "提示: CLIP 模型未找到，跳过 embedding 补算。"
                "请按 README 下载模型到 data/models/。"
            )
            return
        embedder = ClipEmbedder(model_path)
    except Exception as exc:
        print(f"提示: embedding 补算跳过 ({exc})")
        return

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, image_path FROM products WHERE embedding IS NULL"
        ).fetchall()
        for row in rows:
            image_path = DATA_DIR / row["image_path"]
            if not image_path.is_file():
                continue
            try:
                vec = embedder.embed_path(image_path)
                conn.execute(
                    "UPDATE products SET embedding = ? WHERE id = ?",
                    (ClipEmbedder.to_blob(vec), row["id"]),
                )
            except Exception:
                continue
        conn.commit()


def load_products_for_matching() -> list[ProductMatchRow]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, image_path, stock, image_hash, embedding
            FROM products
            WHERE image_path != '' AND embedding IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
    return [
        ProductMatchRow(
            id=row["id"],
            name=row["name"],
            image_path=row["image_path"],
            stock=row["stock"],
            image_hash=row["image_hash"],
            embedding=row["embedding"],
        )
        for row in rows
    ]


def get_product(product_id: int) -> Product | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_product(row)


def increment_stock(
    product_id: int,
    delta: int,
    source: str,
    image_path: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    def _run(connection: sqlite3.Connection) -> None:
        connection.execute(
            "UPDATE products SET stock = stock + ? WHERE id = ?",
            (delta, product_id),
        )
        connection.execute(
            """
            INSERT INTO inventory_logs (product_id, delta, source, image_path)
            VALUES (?, ?, ?, ?)
            """,
            (product_id, delta, source, image_path),
        )

    if conn is not None:
        _run(conn)
        return

    with get_connection() as connection:
        _run(connection)
        connection.commit()


def apply_inbound_batch(
    items: list[tuple[int, str | None]],
) -> int:
    """Apply multiple inbound increments in one transaction."""
    if not items:
        return 0
    with get_connection() as conn:
        for product_id, image_path in items:
            increment_stock(
                product_id,
                delta=1,
                source="inbound",
                image_path=image_path,
                conn=conn,
            )
        conn.commit()
    return len(items)


def batch_import(
    paths: list[Path],
) -> tuple[list[Product], list[str], list[str]]:
    """Import multiple images. Returns (products, errors, skipped messages)."""
    products: list[Product] = []
    errors: list[str] = []
    skipped: list[str] = []
    known_file_hashes, known_image_hashes = load_product_hashes()

    for path in collect_image_paths(paths):
        try:
            file_hash = compute_file_hash(path)
            image_hash = compute_image_hash(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        _existing_product, reason = _find_duplicate_by_hashes(
            file_hash,
            image_hash,
            known_file_hashes,
            known_image_hashes,
        )
        if reason:
            skipped.append(f"{path.name}: {reason}")
            continue

        try:
            product = import_product(path, file_hash, image_hash)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        products.append(product)
        known_file_hashes.add(file_hash)
        known_image_hashes.append((image_hash, product))

    return products, errors, skipped


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
