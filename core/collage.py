"""Compose product photos into a single grid collage image."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CELL_SIZE = 300
LABEL_HEIGHT = 40
CELL_SPACING = 16
MAX_COLUMNS = 5
FONT_SIZE = 18
BACKGROUND_COLOR = (255, 255, 255)
TEXT_COLOR = (30, 30, 30)

# Windows 中文字体候选（Pillow 默认字体无法绘制中文）
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
]


def _load_font(
    size: int = FONT_SIZE,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _truncate_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    if font.getlength(text) <= max_width:
        return text
    ellipsis = "…"
    while text and font.getlength(text + ellipsis) > max_width:
        text = text[:-1]
    return text + ellipsis


def build_collage(
    items: list[tuple[str, Path]],
    output_path: Path,
) -> tuple[int, int]:
    """Paste each (name, image_path) into a grid and save to output_path.

    Returns (added_count, skipped_count); items whose image is missing or
    unreadable are skipped.
    """
    loaded: list[tuple[str, Image.Image]] = []
    skipped = 0
    for name, image_path in items:
        try:
            with Image.open(image_path) as img:
                loaded.append((name, img.convert("RGB")))
        except (OSError, ValueError):
            skipped += 1

    if not loaded:
        return 0, skipped

    columns = min(MAX_COLUMNS, len(loaded))
    rows = (len(loaded) + columns - 1) // columns
    cell_total_height = CELL_SIZE + LABEL_HEIGHT
    canvas_width = columns * CELL_SIZE + (columns + 1) * CELL_SPACING
    canvas_height = rows * cell_total_height + (rows + 1) * CELL_SPACING

    canvas = Image.new("RGB", (canvas_width, canvas_height), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)
    font = _load_font()

    for index, (name, img) in enumerate(loaded):
        row = index // columns
        col = index % columns
        cell_x = CELL_SPACING + col * (CELL_SIZE + CELL_SPACING)
        cell_y = CELL_SPACING + row * (cell_total_height + CELL_SPACING)

        thumb = img.copy()
        thumb.thumbnail((CELL_SIZE, CELL_SIZE), Image.Resampling.LANCZOS)
        paste_x = cell_x + (CELL_SIZE - thumb.width) // 2
        paste_y = cell_y + (CELL_SIZE - thumb.height) // 2
        canvas.paste(thumb, (paste_x, paste_y))

        label = _truncate_text(name, font, CELL_SIZE)
        label_width = font.getlength(label)
        text_x = cell_x + (CELL_SIZE - label_width) / 2
        text_y = cell_y + CELL_SIZE + (LABEL_HEIGHT - FONT_SIZE) / 2
        draw.text((text_x, text_y), label, font=font, fill=TEXT_COLOR)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        canvas.save(output_path, format="JPEG", quality=92)
    else:
        canvas.save(output_path, format="PNG")
    return len(loaded), skipped


def build_vertical_stock_export(
    items: list[tuple[str, Path, str, int]],
    output_path: Path,
) -> tuple[int, int]:
    """Build a vertical stock-decrease summary.

    Each item is ``(product_name, image_path, package_type, quantity)``.
    Returns ``(added_count, skipped_count)``.
    """
    loaded: list[tuple[str, Image.Image, str, int]] = []
    skipped = 0
    for name, image_path, package_type, quantity in items:
        try:
            with Image.open(image_path) as img:
                loaded.append(
                    (name, img.convert("RGB"), package_type, quantity)
                )
        except (OSError, ValueError):
            skipped += 1

    if not loaded or skipped:
        return 0, skipped

    canvas_width = 720
    horizontal_padding = 28
    header_height = 96
    row_height = 272
    row_spacing = 16
    image_size = 232
    canvas_height = (
        header_height
        + horizontal_padding
        + len(loaded) * row_height
        + (len(loaded) - 1) * row_spacing
        + horizontal_padding
    )
    canvas = Image.new("RGB", (canvas_width, canvas_height), (245, 247, 250))
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(30)
    name_font = _load_font(24)
    detail_font = _load_font(22)

    title = "库存减少清单"
    title_width = title_font.getlength(title)
    draw.text(
        ((canvas_width - title_width) / 2, 28),
        title,
        font=title_font,
        fill=(20, 26, 35),
    )

    for index, (name, img, package_type, quantity) in enumerate(loaded):
        row_y = header_height + horizontal_padding + index * (
            row_height + row_spacing
        )
        row_x = horizontal_padding
        row_width = canvas_width - horizontal_padding * 2
        draw.rounded_rectangle(
            (row_x, row_y, row_x + row_width, row_y + row_height),
            radius=16,
            fill=(255, 255, 255),
            outline=(218, 223, 230),
            width=2,
        )

        image_x = row_x + 20
        image_y = row_y + (row_height - image_size) // 2
        thumb = img.copy()
        thumb.thumbnail((image_size, image_size), Image.Resampling.LANCZOS)
        paste_x = image_x + (image_size - thumb.width) // 2
        paste_y = image_y + (image_size - thumb.height) // 2
        canvas.paste(thumb, (paste_x, paste_y))
        draw.rounded_rectangle(
            (
                image_x,
                image_y,
                image_x + image_size,
                image_y + image_size,
            ),
            radius=10,
            outline=(226, 229, 234),
            width=2,
        )

        text_x = image_x + image_size + 28
        text_width = row_x + row_width - text_x - 20
        product_label = _truncate_text(name, name_font, text_width)
        draw.text(
            (text_x, row_y + 60),
            product_label,
            font=name_font,
            fill=TEXT_COLOR,
        )
        draw.text(
            (text_x, row_y + 122),
            f"包装：{package_type}",
            font=detail_font,
            fill=(0, 105, 185),
        )
        draw.text(
            (text_x, row_y + 174),
            f"数量：{quantity}",
            font=detail_font,
            fill=(90, 96, 105),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        canvas.save(output_path, format="JPEG", quality=92)
    else:
        canvas.save(output_path, format="PNG")
    return len(loaded), skipped
