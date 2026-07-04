"""Create a minimal CLIP-like ONNX model for local testing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "data" / "models" / "clip-vit-base-patch32.onnx"


def main() -> None:
    try:
        import onnx
        from onnx import TensorProto, helper
    except ImportError:
        print("请先安装 onnx: pip install onnx")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(42)
    weights = rng.standard_normal((512, 3)).astype(np.float32) * 0.1
    bias = rng.standard_normal((512,)).astype(np.float32) * 0.01

    w_tensor = helper.make_tensor("W", TensorProto.FLOAT, [512, 3], weights.flatten().tolist())
    b_tensor = helper.make_tensor("B", TensorProto.FLOAT, [512], bias.flatten().tolist())

    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 512])

    gap = helper.make_node("GlobalAveragePool", ["input"], ["gap_out"], name="gap")
    flatten = helper.make_node("Flatten", ["gap_out"], ["flat"], name="flatten")
    gemm = helper.make_node(
        "Gemm",
        ["flat", "W", "B"],
        ["output"],
        name="gemm",
        transB=1,
    )

    graph = helper.make_graph(
        [gap, flatten, gemm],
        "test_clip",
        [input_info],
        [output_info],
        [w_tensor, b_tensor],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.checker.check_model(model)
    onnx.save(model, str(OUTPUT))
    print(f"已创建测试模型: {OUTPUT}")


if __name__ == "__main__":
    main()
