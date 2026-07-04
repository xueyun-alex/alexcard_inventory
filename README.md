# alexcard_inventory

Windows 桌面卡牌库存管理工具。

## 环境要求

- Python 3.11+（Windows 推荐：`py -3.11`）

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

若系统默认 Python 版本较低，请用 `py -3.11` 创建虚拟环境。

## CLIP 模型（入库识别必需）

入库功能使用本地 CLIP ONNX 模型进行图像比对。模型**不会自动下载**，需手动放置：

1. 创建目录 `data/models/`
2. 下载 CLIP ViT-B/32 图像编码器 ONNX 模型，保存为：

   `data/models/clip-vit-base-patch32.onnx`

   可从 Hugging Face 等来源获取兼容 OpenAI CLIP 预处理（224×224、ImageNet 归一化）的 ViT-B/32 图像 ONNX 模型。请确保模型输入为 `[1, 3, 224, 224]` float32，输出为图像 embedding 向量。

3. 首次启动或导入产品时，程序会为参考图计算 embedding；若模型缺失，会在控制台提示并跳过补算。

手动补算已有产品的 embedding：

```bash
python scripts/backfill_embeddings.py
```

## 可选：YOLO 卡牌检测

默认使用 OpenCV 轮廓 + 卡牌长宽比检测。若你有自定义卡牌检测 YOLO 模型，可在 `settings/config.json` 中设置：

```json
"yolo_model_path": "data/models/your-card-detector.pt"
```

## 配置

`settings/config.json` 主要项：

| 键 | 默认值 | 说明 |
|----|--------|------|
| `clip_threshold` | 0.90 | CLIP 余弦相似度匹配阈值 |
| `phash_top_k` | 20 | 产品库较大时的 pHash 预筛数量 |
| `clip_model_path` | `data/models/clip-vit-base-patch32.onnx` | CLIP 模型路径 |
| `card_aspect_ratio_min/max` | 0.55 / 0.85 | 卡牌候选框长宽比范围 |

## 运行

```bash
python main.py
```

数据文件保存在 `data/` 目录（运行时自动创建）。

## 入库流程

1. 打开「入库」Tab，批量选择或拖入手机拍照图片
2. 点击「开始识别」——后台检测每张图中的卡牌区域并与产品库比对
3. 在确认对话框中勾选要入库的匹配项，点击「确定」
4. 对应产品库存 +1，并写入 `inventory_logs` 表
