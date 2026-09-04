"""元数据写入与读取：EXIF / XMP（JPEG APP1）/ PNG 文本块与 eXIf。"""

from __future__ import annotations

import json
import re
import struct
import zlib
from typing import Optional

from PIL import Image, ExifTags

from .payload import APP_NAME, APP_VERSION

_XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_exif_bytes(payload: dict) -> bytes:
    """构建 EXIF（纯 TIFF 字节，不含 "Exif\0\0" 前缀）。"""
    owner = payload.get("owner", "")
    license_ = payload.get("license") or "All rights reserved"
    comment = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    import piexif

    zeroth = {
        piexif.ImageIFD.Artist: owner.encode("utf-8"),
        piexif.ImageIFD.Copyright: ("(c) %s - %s" % (owner, license_)).encode("utf-8"),
        piexif.ImageIFD.ImageDescription: comment.encode("utf-8"),
        piexif.ImageIFD.Software: ("%s/%s" % (APP_NAME, APP_VERSION)).encode("utf-8"),
    }
    # 注：完整 JSON 载荷已写入 ImageDescription，结构化版权写入 XMP，
    # 故不再额外写 Exif 子 IFD（UserComment），避免部分读取器解析不完整。
    d = {"0th": zeroth, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    raw = piexif.dump(d)
    if raw.startswith(b"Exif\x00\x00"):
        raw = raw[6:]
    return raw


def build_xmp(payload: dict) -> bytes:
    """构建 XMP 数据包（UTF-8）。包含 dc 版权与自定义 aegis 命名空间的禁 AI 标记。"""
    owner = _xml_escape(payload.get("owner", ""))
    contact = _xml_escape(payload.get("contact") or "")
    license_ = _xml_escape(payload.get("license") or "All rights reserved")
    no_ai = "true" if payload.get("no_ai_training") else "false"
    created = _xml_escape(payload.get("created_at", ""))
    packet = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '      xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/"\n'
        '      xmlns:aegis="https://aegisbrush.app/ns/1.0/">\n'
        '   <dc:creator><rdf:Seq><rdf:li>%s</rdf:li></rdf:Seq></dc:creator>\n'
        '   <dc:rights><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></dc:rights>\n'
        '   <xmpRights:Marked>True</xmpRights:Marked>\n'
        '   <xmpRights:Owner><rdf:Bag><rdf:li>%s</rdf:li></rdf:Bag></xmpRights:Owner>\n'
        '   <aegis:noAITraining>%s</aegis:noAITraining>\n'
        '   <aegis:owner>%s</aegis:owner>\n'
        '   <aegis:contact>%s</aegis:contact>\n'
        '   <aegis:createdAt>%s</aegis:createdAt>\n'
        '  </rdf:Description>\n'
        ' </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>'
    ) % (owner, license_, owner, no_ai, owner, contact, created)
    return packet.encode("utf-8")


def _jpeg_insert_segment(data: bytes, marker_payload: bytes) -> bytes:
    # JPEG APP1 段长度字段 = 载荷长度 + 2（含长度字段自身两个字节）
    segment = b"\xff\xe1" + (2 + len(marker_payload)).to_bytes(2, "big") + marker_payload
    return data[:2] + segment + data[2:]


def write_jpeg(img: Image.Image, path: str, payload: dict, quality: int = 95) -> None:
    img.save(path, "JPEG", quality=quality, subsampling=0, optimize=False)
    with open(path, "rb") as f:
        data = f.read()
    data = _jpeg_insert_segment(data, b"Exif\x00\x00" + build_exif_bytes(payload))
    data = _jpeg_insert_segment(data, _XMP_NS + build_xmp(payload))
    with open(path, "wb") as f:
        f.write(data)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _png_itext(keyword: str, text: str) -> bytes:
    kb = keyword.encode("latin-1")
    tb = text.encode("utf-8")
    # iTXt: keyword \0 flag(0) method(0) lang \0 translated \0 text
    data = kb + b"\x00\x00\x00\x00\x00" + tb
    return _png_chunk(b"iTXt", data)


def write_png(img: Image.Image, path: str, payload: dict) -> None:
    img.save(path, "PNG")
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(_PNG_SIG):
        raise ValueError("不是合法的 PNG 文件")

    pos = 8
    length = struct.unpack(">I", data[pos : pos + 4])[0]
    end = pos + 4 + 4 + length + 4

    owner = payload.get("owner", "")
    comment = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    chunks = [
        _png_itext("Copyright", "(c) %s" % owner),
        _png_itext("Author", owner),
        _png_itext("Comment", comment),
        _png_itext("XML:com.adobe.xmp", build_xmp(payload).decode("utf-8")),
        _png_chunk(b"eXIf", build_exif_bytes(payload)),
    ]
    out = data[:end] + b"".join(chunks) + data[end:]
    with open(path, "wb") as f:
        f.write(out)


def _decode(v):
    if isinstance(v, bytes):
        raw = v
    elif isinstance(v, str):
        # PIL 对 ASCII 型字段按 latin-1 解码；若原值实为 UTF-8，先无损还原字节
        if v.startswith("\x00" * 8):
            return v[8:]
        try:
            raw = v.encode("latin-1")
        except UnicodeEncodeError:
            return v  # 已是正确解码的中文等字符
    else:
        return v
    # UserComment 常带 8 字节字符集码前缀（全零 = 未定义 / UTF-8）
    if raw.startswith(b"\x00\x00\x00\x00\x00\x00\x00\x00"):
        raw = raw[8:]
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.hex()


def _read_exif(path: str):
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            out = {}
            for k, v in ex.items():
                name = ExifTags.TAGS.get(k, str(k))
                out[name] = _decode(v)
            ifd = ex.get_ifd(0x8769)
            for k, v in ifd.items():
                name = ExifTags.TAGS.get(k, str(k))
                out[name] = _decode(v)
            return out or None
    except Exception:
        return None


def parse_xmp(xmp: Optional[bytes]) -> Optional[dict]:
    if not xmp:
        return None
    try:
        text = xmp.decode("utf-8", errors="replace")
    except Exception:
        return None

    def grab(tag: str):
        m = re.search(r"<%s[^>]*>(.*?)</%s>" % (re.escape(tag), re.escape(tag)), text, re.S)
        return m.group(1).strip() if m else None

    def first_li(fragment: Optional[str]):
        if not fragment:
            return None
        m = re.search(r"<rdf:li[^>]*>(.*?)</rdf:li>", fragment, re.S)
        return m.group(1).strip() if m else fragment.strip()

    out = {
        "owner": grab("aegis:owner") or first_li(grab("dc:creator")),
        "rights": first_li(grab("dc:rights")),
        "no_ai_training": grab("aegis:noAITraining"),
        "contact": grab("aegis:contact"),
        "created_at": grab("aegis:createdAt"),
        "marked": grab("xmpRights:Marked"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _read_jpeg(path: str):
    with open(path, "rb") as f:
        data = f.read()
    xmp = None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker == 0xD9 or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            pos += 2
            continue
        seg_len = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if seg_len < 2:
            break
        payload = data[pos + 4 : pos + 2 + seg_len]
        if marker == 0xE1 and payload.startswith(_XMP_NS):
            xmp = payload[len(_XMP_NS) :]
        pos += 2 + seg_len
    return {"xmp": parse_xmp(xmp)}


def _read_png(path: str):
    with open(path, "rb") as f:
        data = f.read()
    png_text = {}
    xmp = None
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        if ctype == b"iTXt":
            parts = chunk_data.split(b"\x00", 4)
            if len(parts) >= 5:
                keyword = parts[0].decode("latin-1", errors="replace")
                text = parts[4].decode("utf-8", errors="replace")
                png_text[keyword] = text
                if keyword == "XML:com.adobe.xmp":
                    xmp = parts[4]
        elif ctype == b"tEXt":
            keyword, _, text = chunk_data.partition(b"\x00")
            png_text[keyword.decode("latin-1", errors="replace")] = text.decode(
                "latin-1", errors="replace"
            )
        pos += 12 + length
        if ctype == b"IEND":
            break
    return {"png_text": png_text or None, "xmp": parse_xmp(xmp)}


def read_metadata(path: str) -> dict:
    try:
        with Image.open(path) as im:
            fmt = im.format
    except Exception:
        fmt = None
    result = {"path": path, "format": fmt, "exif": _read_exif(path)}
    if fmt == "JPEG":
        result.update(_read_jpeg(path))
    elif fmt == "PNG":
        result.update(_read_png(path))
    else:
        result["xmp"] = None
    return result
