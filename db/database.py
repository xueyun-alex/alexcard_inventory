"""SQLite connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app_paths import project_root

PROJECT_ROOT = project_root()
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "inventory.db"
PRODUCTS_DIR = DATA_DIR / "products"
TRASH_DIR = DATA_DIR / "trash"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    parent_id INTEGER NULL REFERENCES categories(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NULL REFERENCES categories(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    image_path TEXT NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


_INVENTORY_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    delta INTEGER NOT NULL,
    source TEXT NOT NULL,
    image_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_inventory_logs_product ON inventory_logs(product_id);
"""

_CHANGE_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS change_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reverted_at TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_logs_created ON change_logs(created_at DESC);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    category_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(categories)").fetchall()
    }
    if "parent_id" not in category_columns:
        conn.execute(
            "ALTER TABLE categories ADD COLUMN parent_id INTEGER "
            "REFERENCES categories(id) ON DELETE RESTRICT"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id)"
    )
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS categories_one_level_insert
        BEFORE INSERT ON categories
        WHEN NEW.parent_id IS NOT NULL
        BEGIN
            SELECT CASE
                WHEN NEW.parent_id = NEW.id
                  OR (SELECT parent_id FROM categories WHERE id = NEW.parent_id) IS NOT NULL
                THEN RAISE(ABORT, '产品类只支持一级子类')
            END;
        END;
        CREATE TRIGGER IF NOT EXISTS categories_one_level_update
        BEFORE UPDATE OF parent_id ON categories
        WHEN NEW.parent_id IS NOT NULL
        BEGIN
            SELECT CASE
                WHEN NEW.parent_id = NEW.id
                  OR (SELECT parent_id FROM categories WHERE id = NEW.parent_id) IS NOT NULL
                  OR EXISTS (
                      SELECT 1 FROM categories WHERE parent_id = NEW.id
                  )
                THEN RAISE(ABORT, '产品类只支持一级子类')
            END;
        END;
        """
    )

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    }
    if "file_hash" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN file_hash TEXT")
    if "image_hash" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN image_hash TEXT")
    if "embedding" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN embedding BLOB")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_file_hash ON products(file_hash)"
    )
    conn.executescript(_INVENTORY_LOGS_SCHEMA)
    conn.executescript(_CHANGE_LOGS_SCHEMA)

    inv_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(inventory_logs)").fetchall()
    }
    if inv_columns and "reverted_at" not in inv_columns:
        conn.execute("ALTER TABLE inventory_logs ADD COLUMN reverted_at TEXT")


def init_db() -> None:
    """Ensure data directories exist and create tables if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
        _migrate_schema(conn)
        conn.commit()

    from db.models import backfill_product_hashes

    backfill_product_hashes()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
