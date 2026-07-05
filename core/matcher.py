"""Product matching via SHA-256 content hash and pHash visual similarity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from db import models
from db.database import DATA_DIR
from db.models import Product


@dataclass
class MatchCandidate:
    product_id: int | None
    product_name: str | None
    score: float | None
    stock: int | None
    product_image_path: Path | None


class ProductMatcher:
    def __init__(self) -> None:
        self._file_hashes: dict[str, Product] = {}
        self._image_hashes: list[tuple[str, Product]] = []
        self._product_count = 0

    def build_index(self) -> None:
        rows = models.load_products_for_matching()
        self._file_hashes = {}
        self._image_hashes = []
        seen_ids: set[int] = set()
        for row in rows:
            product = Product(
                id=row.id,
                category_id=None,
                name=row.name,
                image_path=row.image_path,
                stock=row.stock,
                created_at="",
            )
            seen_ids.add(row.id)
            if row.file_hash:
                self._file_hashes[row.file_hash] = product
            if row.image_hash:
                self._image_hashes.append((row.image_hash, product))
        self._product_count = len(seen_ids)

    @property
    def product_count(self) -> int:
        return self._product_count

    def match_by_hashes(self, file_hash: str | None, image_hash: str) -> MatchCandidate:
        if self._product_count == 0:
            return MatchCandidate(None, None, None, None, None)

        product, _reason, score = models.find_product_by_hashes(
            file_hash,
            image_hash,
            self._file_hashes,
            self._image_hashes,
        )
        if product is None or score is None:
            return MatchCandidate(None, None, None, None, None)

        return MatchCandidate(
            product_id=product.id,
            product_name=product.name,
            score=score,
            stock=product.stock,
            product_image_path=DATA_DIR / product.image_path,
        )
