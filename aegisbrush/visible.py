"""可见水印：文字平铺 / 单点水印与 Logo 叠加。"""

from __future__ import annotations

from typing import Optional, Tuple, Union

from PIL import Image, ImageDraw

from .fonts import load_font

_OPACITY_DEFAULT = 0.35
_ANGLE_DEFAULT = 30


def _text_sprite(
    text: str,
    font,
    color: Tuple[int, int, int],
    angle: float,
    outline: Optional[Tuple[int, int, int]],
    outline_width: int,
) -> Image.Image:
    """渲染带旋转的透明文字贴片。"""
    tmp = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    stroke_width = outline_width if outline else 0
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    x0, y0, x1, y1 = bbox
    pad = max(2, int(max(x1 - x0, y1 - y0) * 0.1))
    w, h = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    sprite = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    d.text(
        (pad - x0, pad - y0),
        text,
        font=font,
        fill=color,
        stroke_width=stroke_width,
        stroke_fill=outline,
    )
    if angle:
        sprite = sprite.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    return sprite


def _vertical_sprite(
    text: str,
    font,
    color: Tuple[int, int, int],
    outline: Optional[Tuple[int, int, int]],
    outline_width: int,
) -> Image.Image:
    """渲染竖排文字（逐字从上到下，水平居中）。"""
    tmp = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    stroke_width = outline_width if outline else 0
    max_w = max_h = 0
    for ch in text:
        bb = d.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)
        max_w = max(max_w, bb[2] - bb[0])
        max_h = max(max_h, bb[3] - bb[1])
    step = int(max_h * 1.05) + 1
    pad = max(2, int(max_w * 0.15))
    w = max_w + 2 * pad
    h = step * len(text) + 2 * pad
    sprite = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    for i, ch in enumerate(text):
        bb = d.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)
        cw = bb[2] - bb[0]
        x = pad + (max_w - cw) // 2
        y = pad + i * step - bb[1]
        d.text((x, y), ch, font=font, fill=color, stroke_width=stroke_width, stroke_fill=outline)
    return sprite


def _apply_opacity(img: Image.Image, opacity: float) -> Image.Image:
    alpha = img.getchannel("A").point(lambda a: int(a * opacity))
    img.putalpha(alpha)
    return img


def add_text_watermark(
    image: Image.Image,
    text: str,
    *,
    mode: str = "tile",
    font_size: Optional[int] = None,
    opacity: float = _OPACITY_DEFAULT,
    color: Tuple[int, int, int] = (255, 255, 255),
    angle: float = _ANGLE_DEFAULT,
    font_path: Optional[str] = None,
    spacing: float = 1.0,
    outline: Optional[Tuple[int, int, int]] = None,
    outline_width: int = 1,
    direction: str = "horizontal",
) -> Image.Image:
    """给图片叠加文字水印。

    mode:
      "tile"   平铺（默认）
      "single" 居中
      "corner" 右下角
    direction: "horizontal"（横排，默认）/ "vertical"（竖排，逐字纵向）
    """
    base = image.convert("RGBA")
    w, h = base.size
    if font_size is None:
        font_size = max(14, min(w, h) // 24)
    font = load_font(font_size, font_path)
    if direction == "vertical":
        sprite = _vertical_sprite(text, font, color, outline, outline_width)
    else:
        sprite = _text_sprite(text, font, color, angle if mode == "tile" else 0, outline, outline_width)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sw, sh = sprite.size
    if direction == "vertical":
        overlay.alpha_composite(sprite, ((w - sw) // 2, (h - sh) // 2))
    elif mode == "tile":
        step_x = max(1, int(sw * spacing))
        step_y = max(1, int(sh * spacing))
        x = -sw // 2
        while x < w:
            y = -sh // 2
            while y < h:
                overlay.alpha_composite(sprite, (x, y))
                y += step_y
            x += step_x
    elif mode in ("single", "center"):
        overlay.alpha_composite(sprite, ((w - sw) // 2, (h - sh) // 2))
    elif mode in ("corner", "single-corner"):
        overlay.alpha_composite(sprite, (w - sw - 20, h - sh - 20))
    else:
        raise ValueError(f"未知的可见水印模式: {mode!r}")

    overlay = _apply_opacity(overlay, opacity)
    base.alpha_composite(overlay)
    return base.convert("RGB")


def add_logo(
    image: Image.Image,
    logo: Union[str, Image.Image],
    *,
    position: str = "bottom-right",
    scale: float = 0.12,
    opacity: float = 0.85,
    margin: Optional[int] = None,
) -> Image.Image:
    """在指定角落叠加 Logo。position: top-left/top-right/bottom-left/bottom-right。"""
    base = image.convert("RGBA")
    w, h = base.size
    if isinstance(logo, str):
        logo = Image.open(logo).convert("RGBA")
    else:
        logo = logo.convert("RGBA")

    target_w = max(8, int(w * scale))
    ratio = target_w / max(1, logo.width)
    target_h = max(1, int(logo.height * ratio))
    logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    if margin is None:
        margin = max(4, int(min(w, h) * 0.02))
    positions = {
        "top-left": (margin, margin),
        "top-right": (w - target_w - margin, margin),
        "bottom-left": (margin, h - target_h - margin),
        "bottom-right": (w - target_w - margin, h - target_h - margin),
    }
    if position not in positions:
        raise ValueError(f"未知的 Logo 位置: {position!r}")

    logo = _apply_opacity(logo, opacity)
    base.alpha_composite(logo, positions[position])
    return base.convert("RGB")


def add_watermark_suite(
    image: Image.Image,
    *,
    top_text: Optional[str] = None,
    en_text: Optional[str] = None,
    center_text: Optional[str] = None,
    side_text: Optional[str] = None,
    bottom_text: Optional[str] = None,
    tile_text: Optional[str] = None,
    opacity: float = 0.30,
    tile_opacity: float = 0.08,
    color: Tuple[int, int, int] = (255, 255, 255),
    outline: Tuple[int, int, int] = (0, 0, 0),
    outline_width: int = 1,
    font_path: Optional[str] = None,
) -> Image.Image:
    """生成多层防盗水印套件（参考专业画师水印布局）。

    布局（六层）：
      tile_text   底层斜向平铺密集水印
      top_text    顶部横排声明
      en_text     英文声明
      center_text 中央大字（如"授权样图"/作者名）
      side_text   右侧竖排声明
      bottom_text 底部署名 / 联系方式
    font_path: 自定义字体文件路径（默认自动定位中文字体）
    """
    base = image.convert("RGBA")
    w, h = base.size
    base_len = min(w, h)

    def place(sprite, cx, cy):
        sw, sh = sprite.size
        base.alpha_composite(sprite, (int(cx - sw / 2), int(cy - sh / 2)))

    # 0. 底层斜向平铺密集水印
    if tile_text:
        base = add_text_watermark(
            base, tile_text, mode="tile", opacity=tile_opacity,
            font_size=max(14, int(base_len * 0.03)), angle=30,
            color=color, outline=outline, outline_width=outline_width,
            font_path=font_path,
        )
        base = base.convert("RGBA")  # add_text_watermark 返回 RGB，转回 RGBA 供后续 alpha 合成

    # 1. 顶部横排声明
    if top_text:
        font = load_font(max(14, int(base_len * 0.035)), font_path)
        sp = _apply_opacity(_text_sprite(top_text, font, color, 0, outline, outline_width), opacity)
        place(sp, w / 2, h * 0.05)

    # 2. 英文声明
    if en_text:
        font = load_font(max(12, int(base_len * 0.022)), font_path)
        sp = _apply_opacity(_text_sprite(en_text, font, color, 0, outline, outline_width), opacity)
        place(sp, w / 2, h * 0.10)

    # 3. 中央大字
    if center_text:
        font = load_font(max(14, int(base_len * 0.08)), font_path)
        sp = _apply_opacity(_text_sprite(center_text, font, color, 0, outline, outline_width), opacity)
        place(sp, w / 2, h / 2)

    # 4. 右侧竖排
    if side_text:
        font = load_font(max(12, int(base_len * 0.03)), font_path)
        sp = _apply_opacity(_vertical_sprite(side_text, font, color, outline, outline_width), opacity)
        place(sp, w * 0.96, h / 2)

    # 5. 底部署名
    if bottom_text:
        font = load_font(max(12, int(base_len * 0.025)), font_path)
        sp = _apply_opacity(_text_sprite(bottom_text, font, color, 0, outline, outline_width), opacity)
        place(sp, w / 2, h * 0.94)

    return base.convert("RGB")
