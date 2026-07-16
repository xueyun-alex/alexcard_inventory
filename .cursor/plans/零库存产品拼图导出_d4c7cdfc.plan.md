---
name: 零库存产品拼图导出
overview: 在产品类右键菜单中新增"导出零库存产品图"功能：收集该类下库存为 0 的产品照片，用 Pillow 拼成一张网格大图并保存到用户选择的位置。
todos:
  - id: collage-core
    content: 新建 core/collage.py，实现零库存产品图片网格拼图函数（缩放、贴图、绘制产品名、保存）
    status: completed
  - id: context-menu
    content: 在 ui/product_tab.py 的 _category_context_menu 中新增"导出零库存产品图"菜单项
    status: completed
  - id: export-handler
    content: 实现 ProductTab._export_zero_stock_collage：查询零库存产品、保存对话框、调用拼图并提示结果
    status: completed
  - id: verify
    content: 运行应用验证：有/无零库存产品、图片缺失等情况下的导出效果
    status: completed
isProject: false
---

# 产品类右键导出零库存产品拼图

## 目标

在产品类列表右键菜单中新增一项"导出零库存产品图"：查询该产品类下 `stock = 0` 的产品，把它们的照片拼成一张网格大图（每张图下方标注产品名），弹出保存对话框让用户选择输出位置（PNG/JPG）。

## 现状

- 产品类右键菜单在 [ui/product_tab.py](ui/product_tab.py) 的 `_category_context_menu`（约 668–684 行），目前只有"重命名"和"删除"两项。
- 库存存在 SQLite `products.stock`；按分类查产品用 [db/models.py](db/models.py) 的 `list_products(category_id)`，图片绝对路径用 `get_product_image_path(product)`。
- 项目已依赖 Pillow，无需新增依赖。目前没有现成的拼图逻辑，需要新写。

## 实现方案

### 1. 拼图工具函数（新文件 `core/collage.py`）

新增 `build_zero_stock_collage(products, output_path)`（或接收 `(name, image_path)` 列表）：

- 用 Pillow 打开每张产品图，等比缩放并居中贴到固定单元格（如 300×300），图片下方留约 40px 绘制产品名（超长截断省略号）。
- 网格布局：固定每行 5 列（不足 5 张按实际数量），行数按数量向上取整；单元格间留白，整体白底。
- 图片缺失或打开失败的产品跳过并计数，用于结果提示。
- 按 `output_path` 后缀保存（`.png` / `.jpg`，JPG 时先转 RGB）。
- 返回成功拼入的数量和跳过的数量。

### 2. 右键菜单接入（[ui/product_tab.py](ui/product_tab.py)）

在 `_category_context_menu` 中新增菜单项：

```python
export_action = menu.addAction("导出零库存产品图")
...
elif action == export_action:
    self._export_zero_stock_collage(category_id)
```

新增 `ProductTab._export_zero_stock_collage(category_id)`：

1. `zeros = [p for p in models.list_products(category_id) if p.stock == 0]`；为空时 `QMessageBox.information` 提示"该产品类下没有库存为 0 的产品"并返回。
2. `QFileDialog.getSaveFileName` 选择输出路径，默认文件名 `{产品类名}_零库存_{日期}.png`，过滤器 PNG/JPG。
3. 调用拼图函数，用 `QApplication.setOverrideCursor` 显示等待光标（产品数通常不多，同步执行即可）。
4. 完成后提示成功（包含拼入张数、跳过张数），失败时 `QMessageBox.warning` 显示错误。

## 说明

- 右键菜单对"全部/未归类"两个特殊项目前直接 return，保持不变，本功能只对真实产品类生效。
- 不改动数据库层，直接复用 `list_products` 在内存中过滤 `stock == 0`。