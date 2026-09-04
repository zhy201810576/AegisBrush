"""底纹噪声层：给作品叠加半透明底纹/噪声。

作用（诚实定位）：
  1. 高频底纹干扰 AI 特征提取与训练信号（与对抗扰动同向，但这里强调可见/半可见纹理）；
  2. 视觉上标识"受保护"，增加盗图者去水印/二次编辑的难度；
  3. 底纹可作为一种纹理指纹。

局限：不能阻止已部署模型识别，也不能阻止截图重拍。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image

_TEXTURE_TYPES = ("noise", "hatch", "dots", "grid")


def _pattern(h: int, w: int, kind: str, seed: Optional[int]):
    """生成底纹图案（返回 float32 数组，形状 (h, w, 3)，值域约 0~255）。"""
    rng = np.random.default_rng(seed)
    if kind == "noise":
        # 灰度噪声：单通道扩展到 3 通道（三通道加相同值，只改亮度、不改色相）
        gray = rng.standard_normal((h, w, 1)).astype(np.float32)
        return np.repeat(gray, 3, axis=2)

    yy, xx = np.mgrid[0:h, 0:w]
    if kind == "hatch":
        period = 8
        p = ((xx + yy) % period) < (period // 4)
    elif kind == "dots":
        period = 10
        p = ((xx % period) < 2) & ((yy % period) < 2)
    elif kind == "grid":
        period = 24
        p = ((xx % period) < 1) | ((yy % period) < 1)
    else:
        raise ValueError(f"未知底纹类型: {kind!r}")
    # 0/1 布尔 -> float，扩展到 3 通道
    return np.repeat(p[..., None].astype(np.float32), 3, axis=2)


def add_texture(
    image: Image.Image,
    *,
    kind: str = "noise",
    opacity: float = 0.1,
    seed: Optional[int] = None,
    amp: float = 10.0,
) -> Image.Image:
    """给图片叠加底纹噪声。

    kind:    noise（随机噪声）/ hatch（斜纹）/ dots（点阵）/ grid（网格）
    opacity: 底纹强度 0~1，0 表示不叠加
    amp:     噪声底纹的最大幅度（灰度级），opacity=1 时达到该幅度
    """
    if kind not in _TEXTURE_TYPES:
        raise ValueError(f"未知底纹类型: {kind!r}，可选 {_TEXTURE_TYPES}")
    opacity = float(opacity)
    if opacity <= 0:
        return image.convert("RGB")

    arr = np.array(image.convert("RGB")).astype(np.float32)
    h, w = arr.shape[:2]
    pat = _pattern(h, w, kind, seed)

    if kind == "noise":
        # 标准化后乘幅度，叠加为加性噪声
        pat = pat / (pat.std() + 1e-6)
        out = arr + pat * amp * opacity
    else:
        # 结构底纹：黑白图案按透明度混合
        out = arr * (1 - opacity) + (pat * 255) * opacity

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")
