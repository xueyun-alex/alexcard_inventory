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

    def test_stock_only_decrease_is_excluded_from_sales_ranking(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "inventory.db"
            with patch.object(database, "DB_PATH", db_path):
                with closing(database.get_connection()) as conn:
                    conn.executescript(database._SCHEMA)
                    database._migrate_schema(conn)
                    conn.execute(
                        "INSERT INTO products (name, image_path, stock) "
                        "VALUES ('仅减库存商品', 'one.png', 10)"
                    )
                    conn.execute(
                        "INSERT INTO products (name, image_path, stock) "
                        "VALUES ('正常销售商品', 'two.png', 10)"
                    )
                    conn.commit()

                models.adjust_stock_items([(1, -3)], source="stock_only")
                models.adjust_stock_items([(2, -2)])

                with closing(database.get_connection()) as conn:
                    stocks = [
                        row["stock"]
                        for row in conn.execute(
                            "SELECT stock FROM products ORDER BY id"
                        ).fetchall()
                    ]
                    sources = [
                        row["source"]
                        for row in conn.execute(
                            "SELECT source FROM inventory_logs ORDER BY id"
                        ).fetchall()
                    ]

                ranking = models.list_sales_ranking(
                    "2000-01-01 00:00:00",
                    "2100-01-01 00:00:00",
                )

                self.assertEqual(stocks, [7, 8])
                self.assertEqual(sources, ["stock_only", "manual"])
                self.assertEqual(len(ranking), 1)
                self.assertEqual(ranking[0].name, "正常销售商品")
                self.assertEqual(ranking[0].sold_qty, 2)
                gc.collect()


if __name__ == "__main__":
    unittest.main()
