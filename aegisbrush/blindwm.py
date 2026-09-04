"""DWT/DCT 频域盲水印封装（基于 blind_watermark 库）。

与 LSB 隐写相比，频域盲水印对 JPEG 压缩、缩放、轻微裁剪更鲁棒，
但对"大幅改构图（裁剪换景别）"依然无能为力。

水印内容：固定 16 字节（128 bit）的紧凑标识 = 魔数 AB + 版本(1) + nonce(8) + 校验(5)。
完整载荷（owner 等）仍写入元数据，频域水印负责"存在性证明 + 关联标识"。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Optional

import numpy as np
from PIL import Image

_MAGIC = b"AB"
_CODE_BYTES = 16
_CODE_BITS = _CODE_BYTES * 8


def is_available() -> bool:
    """检查 blind_watermark 库是否可用。"""
    try:
        import blind_watermark  # noqa: F401
        return True
    except ImportError:
        return False


def _watermark_class():
    import blind_watermark

    blind_watermark.bw_notes.close()  # 关闭首次使用的欢迎信息

    try:
        import cv2

        cv2.setLogLevel(cv2.LOG_LEVEL_ERROR)  # 关闭 cv2 的 imwrite 深度告警
    except Exception:  # noqa: BLE001  # 不同 OpenCV 版本日志 API 有差异
        pass
    return blind_watermark.WaterMark


def build_code(payload: dict, key: Optional[bytes] = None) -> bytes:
    """构建固定 16 字节的频域水印标识：AB + ver(1) + nonce(8) + sha256(owner+key)前5。"""
    nonce = bytes.fromhex((payload.get("nonce") or "0" * 16)[:16])
    owner = payload.get("owner", "").encode("utf-8")
    digest = hashlib.sha256(owner + (key or b"")).digest()
    return _MAGIC + bytes([1]) + nonce + digest[:5]


def embed(
    image: Image.Image,
    code: bytes,
    *,
    password_img: int = 1,
    password_wm: int = 1,
) -> Image.Image:
    """把 16 字节 code 嵌入图片频域，返回新的 RGB 图片。"""
    if len(code) != _CODE_BYTES:
        raise ValueError(f"code 必须是 {_CODE_BYTES} 字节，实际 {len(code)}")
    WaterMark = _watermark_class()
    bits = np.unpackbits(np.frombuffer(code, dtype=np.uint8)).astype(np.uint8)
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        out = os.path.join(d, "out.png")
        image.convert("RGB").save(src)
        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        bwm.read_img(src)
        bwm.read_wm(bits, mode="bit")
        bwm.embed(out)
        return Image.open(out).convert("RGB")


def extract(
    image: Image.Image,
    *,
    password_img: int = 1,
    password_wm: int = 1,
    orig_size=None,
) -> Optional[bytes]:
    """提取频域水印标识；不是 AegisBrush 图或提取失败时返回 None。

    orig_size: 嵌入时的原始尺寸 (宽, 高)。盲水印的块划分依赖尺寸，
    若图片被整体缩放过，需先 resize 回原尺寸再提取才能对齐。
    """
    WaterMark = _watermark_class()
    if orig_size is not None:
        image = image.resize(tuple(orig_size), Image.Resampling.LANCZOS)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "query.png")
        image.convert("RGB").save(p)
        bwm = WaterMark(password_img=password_img, password_wm=password_wm)
        try:
            wm = np.asarray(bwm.extract(p, wm_shape=_CODE_BITS, mode="bit"))
        except Exception:
            return None
    bits = (wm >= 0.5).astype(np.uint8)
    code = np.packbits(bits).tobytes()
    if code[:2] != _MAGIC:
        return None
    return code
