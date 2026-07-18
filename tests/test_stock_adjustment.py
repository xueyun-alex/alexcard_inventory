from contextlib import closing
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest

try:
    import imagehash  # noqa: F401
except ModuleNotFoundError:
    sys.modules["imagehash"] = SimpleNamespace()

from db import changelog, database, models


class PerProductStockAdjustmentTests(unittest.TestCase):
    def test_applies_and_reverts_different_quantities_as_one_change(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "inventory.db"
            with patch.object(database, "DB_PATH", db_path):
                with closing(database.get_connection()) as conn:
                    conn.executescript(database._SCHEMA)
                    database._migrate_schema(conn)
                    conn.execute(
                        "INSERT INTO products (name, image_path, stock) "
                        "VALUES ('商品一', 'one.png', 10)"
                    )
                    conn.execute(
                        "INSERT INTO products (name, image_path, stock) "
                        "VALUES ('商品二', 'two.png', 10)"
                    )
                    conn.commit()

                models.adjust_stock_items([(1, -2), (2, -4)])

                with closing(database.get_connection()) as conn:
                    stocks = [
                        row["stock"]
                        for row in conn.execute(
                            "SELECT stock FROM products ORDER BY id"
                        ).fetchall()
                    ]
                self.assertEqual(stocks, [8, 6])

                logs = changelog.list_change_logs()
                self.assertEqual(len(logs), 1)
                self.assertEqual(logs[0].kind, "stock_batch")
                self.assertEqual(
                    [entry["delta"] for entry in logs[0].payload["entries"]],
                    [-2, -4],
                )

                changelog.revert_change(logs[0].id)
                with closing(database.get_connection()) as conn:
                    restored = [
                        row["stock"]
                        for row in conn.execute(
                            "SELECT stock FROM products ORDER BY id"
                        ).fetchall()
                    ]
                self.assertEqual(restored, [10, 10])
                del logs
                gc.collect()


if __name__ == "__main__":
    unittest.main()
