from contextlib import closing
import gc
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import imagehash  # noqa: F401
except ModuleNotFoundError:
    sys.modules["imagehash"] = SimpleNamespace()

from db import changelog, database, models, orders


class OrderTests(unittest.TestCase):
    def test_create_edit_rank_and_revert_order(self) -> None:
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

                created = orders.create_order(
                    "20260720-001",
                    [(1, "裸卡", 2), (2, "带卡砖", 3)],
                    "first.png",
                )
                self.assertEqual(created.status, "待发货")
                self.assertEqual(created.product_type_count, 2)
                self.assertEqual(created.total_quantity, 5)
                self.assertEqual(self._stocks(), [8, 7])
                self.assertEqual(self._ranking(), {"商品一": 2, "商品二": 3})

                shipped = orders.update_order_status(created.id, "已发货")
                self.assertEqual(shipped.status, "已发货")
                self.assertEqual(self._stocks(), [8, 7])

                edited = orders.update_order(
                    created.id,
                    "20260720-002",
                    "已成交",
                    [(1, "挂件袋", 4)],
                )
                self.assertEqual(edited.order_no, "20260720-002")
                self.assertEqual(edited.product_type_count, 1)
                self.assertEqual(edited.total_quantity, 4)
                self.assertEqual(self._stocks(), [6, 10])
                self.assertEqual(self._ranking(), {"商品一": 4})

                logs = changelog.list_change_logs()
                self.assertEqual(
                    [log.kind for log in logs],
                    ["order_update", "order_update", "order_create"],
                )
                with self.assertRaisesRegex(ValueError, "更晚的修改"):
                    changelog.revert_change(logs[2].id)

                changelog.revert_change(logs[0].id)
                reverted_edit = orders.get_order(created.id)
                self.assertIsNotNone(reverted_edit)
                assert reverted_edit is not None
                self.assertEqual(reverted_edit.order_no, "20260720-001")
                self.assertEqual(reverted_edit.status, "已发货")
                self.assertEqual(reverted_edit.product_type_count, 2)
                self.assertEqual(self._stocks(), [8, 7])
                self.assertEqual(self._ranking(), {"商品一": 2, "商品二": 3})

                changelog.revert_change(logs[1].id)
                reverted_status = orders.get_order(created.id)
                self.assertIsNotNone(reverted_status)
                assert reverted_status is not None
                self.assertEqual(reverted_status.status, "待发货")

                changelog.revert_change(logs[2].id)
                self.assertIsNone(orders.get_order(created.id))
                self.assertEqual(self._stocks(), [10, 10])
                self.assertEqual(self._ranking(), {})

                del logs
                gc.collect()

    def test_delete_order_restores_stock_and_updates_ranking(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "inventory.db"
            with patch.object(database, "DB_PATH", db_path):
                with closing(database.get_connection()) as conn:
                    conn.executescript(database._SCHEMA)
                    database._migrate_schema(conn)
                    conn.execute(
                        "INSERT INTO products (name, image_path, stock) "
                        "VALUES ('待删除货单商品', 'one.png', 10)"
                    )
                    conn.commit()

                created = orders.create_order(
                    "DELETE-001",
                    [(1, "裸卡", 3)],
                    None,
                )
                self.assertEqual(self._stocks(), [7])
                self.assertEqual(self._ranking(), {"待删除货单商品": 3})

                orders.delete_order(created.id)
                self.assertIsNone(orders.get_order(created.id))
                self.assertEqual(self._stocks(), [10])
                self.assertEqual(self._ranking(), {})

                logs = changelog.list_change_logs()
                self.assertEqual(
                    [log.kind for log in logs],
                    ["order_delete", "order_create"],
                )
                changelog.revert_change(logs[0].id)
                restored = orders.get_order(created.id)
                self.assertIsNotNone(restored)
                self.assertEqual(self._stocks(), [7])
                self.assertEqual(self._ranking(), {"待删除货单商品": 3})

                changelog.revert_change(logs[1].id)
                self.assertIsNone(orders.get_order(created.id))
                self.assertEqual(self._stocks(), [10])
                self.assertEqual(self._ranking(), {})
                del logs
                gc.collect()

    def _stocks(self) -> list[int]:
        with closing(database.get_connection()) as conn:
            return [
                row["stock"]
                for row in conn.execute(
                    "SELECT stock FROM products ORDER BY id"
                ).fetchall()
            ]

    def _ranking(self) -> dict[str, int]:
        ranking = models.list_sales_ranking(
            "2000-01-01 00:00:00",
            "2100-01-01 00:00:00",
        )
        return {row.name: row.sold_qty for row in ranking}


if __name__ == "__main__":
    unittest.main()
