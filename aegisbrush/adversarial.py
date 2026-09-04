"""对抗扰动：叠加人眼不可见的高频噪声，干扰 AI 特征提取/训练信号。

说明：这是 Nightshade / Glaze 的简化启发式实现，并非等价的学术方案。
高频噪声人眼几乎不可察觉，却会改变频域系数与特征统计，降低图片作为
训练样本的价值；对已部署模型不构成绝对防护，也无法阻止截图重拍。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image, ImageFilter


def apply_protection(
    image: Image.Image,
    strength: float = 40.0,
    seed: Optional[int] = None,
) -> Image.Image:
    """给图片叠加高频对抗噪声。strength: 0~100，0 表示不处理。"""
    strength = float(strength)
    if strength <= 0:
        return image.convert("RGB")

    arr = np.array(image.convert("RGB")).astype(np.float32)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(arr.shape).astype(np.float32)

    # 用盒式模糊提取低频分量，残差即高频分量（人眼对高频不敏感）
    noise_uint8 = ((noise * 64.0) + 128.0).clip(0, 255).astype(np.uint8)
    low = np.array(
        Image.fromarray(noise_uint8, "RGB").filter(ImageFilter.BoxBlur(4)), dtype=np.float32
    ) - 128.0
    low /= 64.0
    high = noise - low

    std = high.std() + 1e-6
    high = high / std  # 归一化到单位标准差

    amp = (strength / 100.0) * 6.0  # 振幅 0~6 个像素级
    out = np.clip(arr + high * amp, 0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGB")
