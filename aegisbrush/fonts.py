"""中文字体定位与加载。

Windows / macOS / Linux 常见中文字体路径探测，找不到时回退到 PIL 内置字体。
"""

from __future__ import annotations

import os
from typing import Optional

from PIL import ImageFont

# 使用正斜杠路径，Windows 下同样有效
_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
    "C:/Windows/Fonts/simhei.ttf",    # 黑体
    "C:/Windows/Fonts/simsun.ttc",    # 宋体
    "C:/Windows/Fonts/simkai.ttf",    # 楷体
    "C:/Windows/Fonts/STKAITI.TTF",   # 华文楷体
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def find_font(preferred: Optional[str] = None) -> Optional[str]:
    """返回第一个存在的字体路径，优先使用 preferred。"""
    for path in ([preferred] if preferred else []) + _CANDIDATES:
        if path and os.path.exists(path):
            return path
    return None


def load_font(size: int, preferred: Optional[str] = None):
    """按字号加载字体；失败时回退到 PIL 内置字体（仅支持基本拉丁字符）。"""
    path = find_font(preferred)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()
