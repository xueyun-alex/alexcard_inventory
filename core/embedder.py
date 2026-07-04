"""CLIP ONNX image embedding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
INPUT_SIZE = 224


class ClipEmbedder:
    """Local CLIP ViT-B/32 ONNX inference (CPU)."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"CLIP 模型文件不存在: {self.model_path}\n"
                "请按 README 说明下载 clip-vit-base-patch32.onnx 到 data/models/ 目录。"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "缺少 onnxruntime 依赖。请先安装:\n"
                "  py -3.11 -m pip install onnxruntime\n"
                "或激活虚拟环境后: pip install -r requirements.txt"
            ) from exc

        self._session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name

    def embed_pil(self, image: Image.Image) -> np.ndarray:
        tensor = self._preprocess(image)
        outputs = self._session.run(
            [self._output_name], {self._input_name: tensor}
        )
        vec = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
        return self._l2_normalize(vec)

    def embed_path(self, path: Path) -> np.ndarray:
        with Image.open(path) as image:
            return self.embed_pil(image.convert("RGB"))

    @staticmethod
    def to_blob(vec: np.ndarray) -> bytes:
        return np.asarray(vec, dtype=np.float32).tobytes()

    @staticmethod
    def from_blob(blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32).copy()

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        image = image.convert("RGB")
        image = image.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BICUBIC)
        arr = np.asarray(image, dtype=np.float32) / 255.0
        arr = (arr - CLIP_MEAN) / CLIP_STD
        arr = arr.transpose(2, 0, 1)
        return arr[np.newaxis, ...].astype(np.float32)

    @staticmethod
    def _l2_normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm < 1e-12:
            return vec
        return vec / norm
