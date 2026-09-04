"""LSB 隐形水印：把字节载荷编码进像素最低位，并支持提取。"""

from __future__ import annotations

import hashlib
from typing import Optional

import numpy as np
from PIL import Image

_CHANNELS = {"red": 0, "green": 1, "blue": 2}
_DEFAULT_CHANNEL = "blue"
_MAX_BITS = 2_000_000


def _seed_from_key(key: Optional[bytes]) -> int:
    if key:
        return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return 0xA3E6B1F5C0DE  # 固定默认种子


def embed_lsb(
    image: Image.Image,
    data: bytes,
    *,
    key: Optional[bytes] = None,
    copies: int = 2,
) -> Image.Image:
    """把 data 编码进图片蓝通道 LSB，copies 份冗余提高抗破坏能力。

    注意：LSB 隐写仅在有损压缩（JPEG）前可靠；输出建议使用 PNG 等无损格式。
    """
    arr = np.array(image.convert("RGB"))
    h, w, _ = arr.shape
    n_pixels = h * w
    n_bits = len(data) * 8
    total_bits = n_bits * copies
    if total_bits > n_pixels:
        raise ValueError(f"容量不足：需要 {total_bits} 个像素位，图片仅有 {n_pixels} 个像素")
    rng = np.random.default_rng(_seed_from_key(key))
    positions = rng.permutation(n_pixels)[:total_bits]
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    rep = np.tile(bits, copies)
    ch = _CHANNELS[_DEFAULT_CHANNEL]
    flat = arr.reshape(-1, 3)
    flat[positions, ch] = (flat[positions, ch] & 0xFE) | rep
    return Image.fromarray(arr, "RGB")


def extract_lsb(
    image: Image.Image,
    *,
    key: Optional[bytes] = None,
    max_bits: int = _MAX_BITS,
) -> bytes:
    """从图片蓝通道 LSB 提取字节流（含冗余副本，供 unframe 扫描魔数）。"""
    arr = np.array(image.convert("RGB"))
    h, w, _ = arr.shape
    n_pixels = h * w
    n_bits = min(max_bits, n_pixels)
    rng = np.random.default_rng(_seed_from_key(key))
    positions = rng.permutation(n_pixels)[:n_bits]
    ch = _CHANNELS[_DEFAULT_CHANNEL]
    flat = arr.reshape(-1, 3)
    bits = (flat[positions, ch] & 1).astype(np.uint8)
    n_bytes = n_bits // 8
    return np.packbits(bits[: n_bytes * 8]).tobytes()
