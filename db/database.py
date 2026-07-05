"""SQLite connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "inventory.db"
PRODUCTS_DIR = DATA_DIR / "products"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
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


def _migrate_schema(conn: sqlite3.Connection) -> None:
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


def init_db() -> None:
    """Ensure data directories exist and create tables if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
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
