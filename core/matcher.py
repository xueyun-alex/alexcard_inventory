"""Product matching via pHash prescreen and CLIP cosine similarity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image

from core.embedder import ClipEmbedder
from db import models
from db.database import DATA_DIR
from db.models import ProductMatchRow


@dataclass
class MatchCandidate:
    product_id: int | None
    product_name: str | None
    score: float | None
    stock: int | None
    product_image_path: Path | None


class ProductMatcher:
    def __init__(self, embedder: ClipEmbedder, config: dict[str, Any]) -> None:
        self._embedder = embedder
        self._config = config
        self._products: list[ProductMatchRow] = []
        self._embeddings: np.ndarray | None = None

    def build_index(self) -> None:
        self._products = models.load_products_for_matching()
        if not self._products:
            self._embeddings = None
            return
        vectors = []
        for product in self._products:
            if product.embedding is not None:
                vectors.append(ClipEmbedder.from_blob(product.embedding))
            else:
                vectors.append(np.zeros(512, dtype=np.float32))
        self._embeddings = np.stack(vectors, axis=0)

    @property
    def product_count(self) -> int:
        return len(self._products)

    def match_crop(self, crop_bgr: np.ndarray, crop_phash: str) -> MatchCandidate:
        if not self._products or self._embeddings is None:
            return MatchCandidate(None, None, None, None, None)

        top_k = int(self._config.get("phash_top_k", 20))
        indices = self._select_candidates(crop_phash, top_k)

        crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        crop_vec = self._embedder.embed_pil(Image.fromarray(crop_rgb))

        best_idx: int | None = None
        best_score = -1.0
        for idx in indices:
            if self._products[idx].embedding is None:
                continue
            score = float(np.dot(crop_vec, self._embeddings[idx]))
            if score > best_score:
                best_score = score
                best_idx = idx

        threshold = float(self._config.get("clip_threshold", 0.90))
        if best_idx is None or best_score < threshold:
            return MatchCandidate(None, None, best_score if best_idx is not None else None, None, None)

        product = self._products[best_idx]
        return MatchCandidate(
            product_id=product.id,
            product_name=product.name,
            score=best_score,
            stock=product.stock,
            product_image_path=DATA_DIR / product.image_path,
        )

    def _select_candidates(self, crop_phash: str, top_k: int) -> list[int]:
        if len(self._products) <= top_k:
            return list(range(len(self._products)))

        crop_hash = imagehash.hex_to_hash(crop_phash)
        scored: list[tuple[int, int]] = []
        for idx, product in enumerate(self._products):
            if not product.image_hash:
                scored.append((999, idx))
                continue
            dist = crop_hash - imagehash.hex_to_hash(product.image_hash)
            scored.append((dist, idx))

        scored.sort(key=lambda item: item[0])
        return [idx for _dist, idx in scored[:top_k]]
