"""载荷构建、序列化与校验，以及内容指纹工具。

载荷是水印的核心信息载体：它既会被写入可见/元数据水印，也会被编码进像素（隐写）。
内容指纹用于事后校验图片内容是否被改动。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from PIL import Image

APP_NAME = "AegisBrush"
APP_VERSION = "1.0.0"
MAGIC = b"AEGIS"
PAYLOAD_VERSION = 1

# frame 布局: MAGIC(5) + ver(1) + len(4) + signed(1) + body + sig(0|32)
HEADER_SIZE = 11


def iso_now() -> str:
    """当前 UTC 时间，ISO 8601，精确到秒。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str) -> str:
    """计算文件内容的 SHA-256（流式，支持大文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_payload(
    owner: str,
    *,
    contact: Optional[str] = None,
    license: Optional[str] = None,
    no_ai: bool = True,
    image_sha256: Optional[str] = None,
    pixel_sha256: Optional[str] = None,
    dhash: Optional[int] = None,
    extra: Optional[dict] = None,
) -> dict:
    """构建规范载荷。None 字段会被剔除以保持紧凑。"""
    payload = {
        "app": APP_NAME,
        "version": PAYLOAD_VERSION,
        "owner": owner,
        "contact": contact,
        "license": license,
        "no_ai_training": bool(no_ai),
        "created_at": iso_now(),
        "image_sha256": image_sha256,
        "pixel_sha256": pixel_sha256,
        "dhash": ("%016x" % dhash) if dhash is not None else None,
        "nonce": secrets.token_hex(8),
    }
    if extra:
        payload["extra"] = extra
    return {k: v for k, v in payload.items() if v is not None}


def canonical_json(payload: dict) -> bytes:
    """规范化 JSON 序列化：键排序、紧凑分隔符、保留非 ASCII。"""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sign(data: bytes, key: Optional[bytes]) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest() if key else b""


def frame(payload: dict, key: Optional[bytes] = None) -> bytes:
    """把载荷封装成带魔数与可选 HMAC 签名的字节流，供隐写嵌入。"""
    body = canonical_json(payload)
    sig = _sign(body, key)
    header = (
        MAGIC
        + bytes([PAYLOAD_VERSION])
        + len(body).to_bytes(4, "big")
        + (b"\x01" if sig else b"\x00")
    )
    return header + body + sig


def unframe(data: bytes, key: Optional[bytes] = None):
    """从字节流中扫描魔数并解析载荷。

    返回 {"payload": dict, "signature_valid": bool|None, "version": int}，未找到返回 None。
    signature_valid: True=签名通过, False=签名不匹配, None=未签名或缺少密钥。
    """
    idx = data.find(MAGIC)
    if idx < 0 or len(data) - idx < HEADER_SIZE:
        return None
    ver = data[idx + 5]
    length = int.from_bytes(data[idx + 6 : idx + 10], "big")
    signed = data[idx + 10] == 1
    body_start = idx + HEADER_SIZE
    body_end = body_start + length
    if body_end > len(data):
        return None
    body = data[body_start:body_end]
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    valid = None
    if signed:
        sig = data[body_end : body_end + 32]
        if len(sig) != 32:
            valid = False
        elif key is None:
            valid = None
        else:
            valid = hmac.compare_digest(sig, _sign(body, key))
    return {"payload": payload, "signature_valid": valid, "version": ver}


def pixel_sha256(img: Image.Image, stego_channel: int = 2) -> str:
    """计算内容指纹，忽略隐写通道（默认蓝通道）的 LSB。

    这样指纹在水印嵌入前后保持一致，可用作"像素是否被篡改"的判定基准。
    """
    arr = np.array(img.convert("RGB")).copy()
    arr[:, :, stego_channel] &= 0xFE
    return sha256_bytes(arr.tobytes())


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    """64 位差异哈希（dHash），对重压缩/轻微缩放较鲁棒，用于内容相似度判断。"""
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = "".join("1" if b else "0" for row in diff for b in row)
    return int(bits, 2)


def hamming(a: int, b: int) -> int:
    """两个整数的汉明距离（不同位个数）。"""
    return (a ^ b).bit_count()
