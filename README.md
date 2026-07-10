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

## 可选：YOLO 卡牌检测

出库功能（未启用）可选 YOLO 检测模型。若你有自定义卡牌检测 YOLO 模型，可在 `settings/config.json` 中设置：

```json
"yolo_model_path": "data/models/your-card-detector.pt"
```

## 配置

`settings/config.json` 主要项：

| 键 | 默认值 | 说明 |
|----|--------|------|
| `card_aspect_ratio_min/max` | 0.55 / 0.85 | 卡牌候选框长宽比范围 |
| `yolo_model_path` | `null` | 可选 YOLO 检测模型路径 |

## 运行

```bash
python main.py
```

数据文件保存在 `data/` 目录（运行时自动创建）。

## 入库流程

1. 打开「入库」Tab，选择或拖入与库中产品参考图相同/等价的图片文件
2. 点击「开始识别」——对每张图计算 hash 并与产品库比对
3. 在确认对话框中勾选要入库的匹配项，点击「确定」
4. 对应产品库存 +1，并写入 `inventory_logs` 表

## 入库匹配规则

入库识别与「新增产品去重」使用**完全相同**的 hash 判定逻辑：

| 判定 | 方法 | 说明 |
|------|------|------|
| 内容一致 | SHA-256 完全一致 | 文件字节与库中参考图相同 |
| 视觉相似 | pHash 汉明距离 ≤ 5 | 同一张卡牌不同分辨率/压缩仍可匹配 |

判定顺序：先 SHA-256，未命中再遍历全部产品 pHash（第一个命中即匹配）。

## 产品导入去重

导入产品图片时同样使用 SHA-256 + pHash（阈值 5）查重，重复图片会跳过并在结果中汇总。
