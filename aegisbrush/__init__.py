"""AegisBrush —— OC 作品防盗用与反 AI 训练水印工具。

分层防护：
  1. 可见水印（文字 / Logo）
  2. 隐形水印（LSB 隐写）
  3. 元数据（EXIF / XMP / PNG 文本块）
  4. 对抗扰动（人眼不可见的高频噪声，干扰训练信号）
"""

from .payload import (
    APP_NAME,
    APP_VERSION,
    build_payload,
    canonical_json,
    dhash,
    frame,
    hamming,
    pixel_sha256,
    sha256_file,
    unframe,
)
from .pipeline import match, protect, verify

__version__ = APP_VERSION
__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "__version__",
    "build_payload",
    "canonical_json",
    "dhash",
    "frame",
    "hamming",
    "match",
    "pixel_sha256",
    "protect",
    "sha256_file",
    "unframe",
    "verify",
]
