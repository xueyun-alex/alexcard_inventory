"""Backfill CLIP embeddings for existing products."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import init_db
from db.models import backfill_product_embeddings


def main() -> None:
    init_db()
    backfill_product_embeddings()
    print("Embedding 补算完成。")


if __name__ == "__main__":
    main()
