"""组合流程：一键 protect（防护）、verify（校验）与 match（溯源）。"""

from __future__ import annotations

import hashlib
import json
import os
from glob import glob
from typing import Optional

from PIL import Image

from . import adversarial, blindwm, featurematch, metadata, stego, texture, visible
from .payload import (
    build_payload,
    dhash,
    frame,
    hamming,
    pixel_sha256,
    sha256_file,
    unframe,
)

STEGO_CHANNEL = 2  # 蓝通道，与 stego / payload 保持一致


def _key_bytes(key) -> Optional[bytes]:
    if key is None:
        return None
    if isinstance(key, str):
        return key.encode("utf-8")
    return bytes(key)


def _blindwm_passwords(key) -> tuple:
    """从密钥派生频域盲水印的两个随机种子；无密钥时用默认值。"""
    kb = _key_bytes(key)
    if kb is None:
        return 1, 1
    h1 = hashlib.sha256(kb + b"img").digest()
    h2 = hashlib.sha256(kb + b"wm").digest()
    return int.from_bytes(h1[:4], "big"), int.from_bytes(h2[:4], "big")


def _payload_from_metadata(meta: dict):
    """从元数据（EXIF ImageDescription / PNG Comment）解析 AegisBrush 载荷。"""
    candidates = []
    exif = meta.get("exif") or {}
    desc = exif.get("ImageDescription")
    if isinstance(desc, str):
        candidates.append(desc)
    png_text = meta.get("png_text") or {}
    comment = png_text.get("Comment")
    if isinstance(comment, str):
        candidates.append(comment)
    for c in candidates:
        try:
            p = json.loads(c)
            if isinstance(p, dict) and p.get("app") == "AegisBrush":
                return p
        except (ValueError, TypeError):
            continue
    return None


def protect(
    src: str,
    dst: str,
    *,
    owner: str,
    contact: Optional[str] = None,
    license: Optional[str] = None,
    no_ai: bool = True,
    text: Optional[str] = None,
    visible_mode: str = "tile",
    opacity: float = 0.35,
    font_size: Optional[int] = None,
    font_path: Optional[str] = None,
    top_text: Optional[str] = None,
    en_text: Optional[str] = None,
    tile_text: Optional[str] = None,
    logo: Optional[str] = None,
    logo_position: str = "bottom-right",
    logo_scale: float = 0.12,
    stego_method: str = "blindwm",
    adv_strength: float = 0.0,
    texture_kind: str = "none",
    texture_opacity: float = 0.1,
    texture_seed: Optional[int] = None,
    key=None,
    seed: Optional[int] = None,
    fmt: Optional[str] = None,
    quality: int = 95,
) -> dict:
    """对 src 施加分层防护并输出到 dst，返回处理摘要。

    stego_method: 隐形水印方式
      "blindwm"  频域盲水印（DWT/DCT，默认，抗压缩/缩放/轻微裁剪）
      "lsb"      LSB 隐写（可携带完整载荷，但对像素改动极脆弱）
      "both"     两者都嵌入
      "none"     不嵌入隐形水印
    texture_kind: 底纹噪声类型 none / noise / hatch / dots / grid（默认 none 关闭）
    """
    if stego_method not in ("blindwm", "lsb", "both", "none"):
        raise ValueError(f"未知的 stego_method: {stego_method!r}")

    warnings = []
    img = Image.open(src)
    src_fmt = img.format
    out_fmt = (fmt or src_fmt or "PNG").upper()
    orig_size = tuple(img.size)  # 盲水印嵌入时的原始尺寸，供 verify --orig-size 还原

    # 1. 对抗扰动
    if adv_strength and adv_strength > 0:
        img = adversarial.apply_protection(img, strength=adv_strength, seed=seed)

    # 1.5 底纹噪声（高频纹理，干扰 AI 特征提取 + 视觉防伪）
    if texture_kind != "none":
        img = texture.add_texture(
            img, kind=texture_kind, opacity=texture_opacity, seed=texture_seed
        )

    # 2. 可见水印
    img = img.convert("RGB")
    if visible_mode == "suite":
        img = visible.add_watermark_suite(
            img,
            top_text=(top_text if top_text is not None else "禁止盗用 · 禁止转载 · 禁止修改 · 禁止商用"),
            en_text=(en_text if en_text is not None else "Unauthorized use prohibited"),
            center_text=(text if text is not None else owner),
            side_text="未经授权 禁止使用 禁止二次贩卖",
            bottom_text=owner + ((" · " + contact) if contact else ""),
            tile_text=(tile_text if tile_text is not None else owner),
            opacity=opacity,
            font_path=font_path,
        )
    elif visible_mode != "none":
        label = text if text is not None else owner
        img = visible.add_text_watermark(
            img, label, mode=visible_mode, opacity=opacity, font_size=font_size,
            font_path=font_path,
        )
    if logo:
        img = visible.add_logo(img, logo, position=logo_position, scale=logo_scale)

    key_bytes = _key_bytes(key)

    # 3. 构建基础载荷（含 nonce，供频域盲水印引用）
    payload = build_payload(
        owner,
        contact=contact,
        license=license,
        no_ai=no_ai,
        image_sha256=sha256_file(src),
    )

    # 4. 频域盲水印（先于指纹，因为会改变像素）
    blindwm_embedded = False
    if stego_method in ("blindwm", "both"):
        if blindwm.is_available():
            p_img, p_wm = _blindwm_passwords(key)
            code = blindwm.build_code(payload, key_bytes)
            img = blindwm.embed(img, code, password_img=p_img, password_wm=p_wm)
            blindwm_embedded = True
        else:
            warnings.append("未安装 blind-watermark，频域盲水印不可用（pip install blind-watermark）")

    # 5. 内容指纹（所有像素操作之后计算；蓝 LSB 置零，LSB 嵌入不影响）
    payload["pixel_sha256"] = pixel_sha256(img, STEGO_CHANNEL)
    payload["dhash"] = "%016x" % dhash(img)

    # 6. LSB 隐写（携带含指纹的完整载荷）
    stego_embedded = False
    if stego_method in ("lsb", "both"):
        try:
            img = stego.embed_lsb(img, frame(payload, key_bytes), key=key_bytes)
            stego_embedded = True
        except ValueError:
            warnings.append("LSB 隐写容量不足，已跳过（其余防护仍生效）")

    if stego_embedded and out_fmt in ("JPEG", "JPG"):
        warnings.append("LSB 隐写经有损 JPEG 压缩后会丢失；频域盲水印不受影响")

    # 6. 保存 + 元数据
    if out_fmt == "PNG":
        metadata.write_png(img, dst, payload)
    elif out_fmt in ("JPEG", "JPG"):
        metadata.write_jpeg(img, dst, payload, quality=quality)
    else:
        img.save(dst, out_fmt)

    return {
        "src": src,
        "dst": dst,
        "format": out_fmt,
        "owner": owner,
        "no_ai_training": no_ai,
        "stego_method": stego_method,
        "blindwm_embedded": blindwm_embedded,
        "stego_embedded": stego_embedded,
        "adversarial_strength": adv_strength,
        "texture_kind": texture_kind,
        "texture_opacity": texture_opacity if texture_kind != "none" else 0.0,
        "visible_mode": visible_mode,
        "pixel_sha256": payload["pixel_sha256"],
        "dhash": payload["dhash"],
        "orig_size": list(orig_size),
        "warnings": warnings,
    }


def verify(
    path: str,
    *,
    key=None,
    check_blindwm: bool = True,
    orig_size=None,
    original: Optional[str] = None,
) -> dict:
    """校验图片：频域盲水印 + 元数据 + LSB 隐写 + 内容指纹比对。

    完整载荷来源优先级：LSB 隐写（stego）→ 元数据（EXIF / PNG Comment）。
    频域盲水印提供"存在性证明 + nonce 关联标识"，即使元数据被剥也能检出归属。

    orig_size: 嵌入时的原始尺寸 (宽, 高)，用于把被整体缩放的图还原后再提取盲水印。
    original:  原图文件路径；未显式给出 orig_size 时，自动读取该图尺寸作为原始尺寸。
    """
    if orig_size is None and original:
        try:
            with Image.open(original) as oim:
                orig_size = tuple(oim.size)
        except Exception:
            orig_size = None
    meta = metadata.read_metadata(path)
    result = {
        "path": path,
        "metadata": meta,
        "stego": None,
        "blindwm": None,
        "payload": None,
        "tamper": None,
    }
    key_bytes = _key_bytes(key)
    try:
        img = Image.open(path).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result

    # 1. 频域盲水印
    if check_blindwm and blindwm.is_available():
        p_img, p_wm = _blindwm_passwords(key)
        code = blindwm.extract(img, password_img=p_img, password_wm=p_wm, orig_size=orig_size)
        result["blindwm"] = (
            {"found": True, "code": code.hex(), "nonce": code[3:11].hex()}
            if code
            else {"found": False}
        )

    # 2. LSB 隐写
    found = unframe(stego.extract_lsb(img, key=key_bytes), key_bytes)
    payload = None
    payload_source = None
    if found:
        payload = found["payload"]
        payload_source = "stego"
        result["stego"] = {
            "found": True,
            "signature_valid": found["signature_valid"],
            "owner": payload.get("owner"),
            "contact": payload.get("contact"),
            "license": payload.get("license"),
            "no_ai_training": payload.get("no_ai_training"),
            "created_at": payload.get("created_at"),
            "image_sha256": payload.get("image_sha256"),
        }
    else:
        result["stego"] = {"found": False}
        meta_payload = _payload_from_metadata(meta)
        if meta_payload:
            payload = meta_payload
            payload_source = "metadata"

    # 3. 完整载荷 + 篡改检测
    if payload:
        result["payload"] = {
            "source": payload_source,
            "owner": payload.get("owner"),
            "contact": payload.get("contact"),
            "license": payload.get("license"),
            "no_ai_training": payload.get("no_ai_training"),
            "created_at": payload.get("created_at"),
            "image_sha256": payload.get("image_sha256"),
            "nonce": payload.get("nonce"),
        }
        cur_sha = pixel_sha256(img, STEGO_CHANNEL)
        stored_sha = payload.get("pixel_sha256")
        stored_dhash = payload.get("dhash")
        dhash_dist = None
        if stored_dhash is not None:
            try:
                stored_int = int(stored_dhash, 16)
            except (TypeError, ValueError):
                stored_int = int(stored_dhash)
            dhash_dist = hamming(stored_int, dhash(img))
        result["tamper"] = {
            "pixel_hash_match": stored_sha == cur_sha if stored_sha else None,
            "dhash_distance": dhash_dist,
        }

    # 4. 频域 nonce 与元数据载荷关联校验
    if result["blindwm"] and result["blindwm"]["found"] and payload:
        blindwm_nonce = result["blindwm"]["nonce"]
        payload_nonce = payload.get("nonce")
        result["blindwm"]["nonce_matches_metadata"] = bool(
            payload_nonce and payload_nonce.startswith(blindwm_nonce)
        )
    return result


def _collect_db_files(db: str) -> list:
    """收集图库文件：目录则递归收图片，单文件则原样返回。"""
    if os.path.isdir(db):
        files = []
        for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"):
            files.extend(glob(os.path.join(db, "**", pat), recursive=True))
    else:
        files = [db]
    return files


def _load_regions(regions) -> list:
    """加载「关键花纹区块」标注：支持 JSON 文件路径 / dict / 区块列表。

    每个区块为 {"name": str, "x": int, "y": int, "w": int, "h": int}，
    坐标相对于原图（图库文件）。无效项被静默跳过。
    """
    if regions is None:
        return []
    if isinstance(regions, str):
        if not os.path.isfile(regions):
            return []
        with open(regions, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = regions
    if isinstance(data, dict):
        data = data.get("regions") or []
    out = []
    for r in data or []:
        if not isinstance(r, dict):
            continue
        try:
            out.append({
                "name": str(r.get("name", "")),
                "x": int(r["x"]),
                "y": int(r["y"]),
                "w": int(r["w"]),
                "h": int(r["h"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def match(
    query: str,
    db: str,
    *,
    threshold: int = 10,
    top: int = 5,
    method: str = "dhash",
    min_inliers: int = 15,
    min_ratio: float = 0.3,
    min_color_consistency: float = 0.70,
    max_color_distance: float = 25.0,
    regions=None,
    min_region_match_rate: float = 0.5,
    visualize: Optional[str] = None,
    highlight: Optional[str] = None,
) -> dict:
    """在图片库中溯源：找出与 query 最相似的原图。

    method:
      "dhash"   全局差异哈希（默认）。适用：颜色滤镜、缩放、轻微编辑、无损搬运。
      "phash"   DCT 感知哈希。额外抗噪声、抗压缩、抗亮度。
      "feature" ORB + RANSAC 局部特征匹配。适用：裁剪换景别、旋转、贴图加字等改构图操作。
                额外做内点颜色一致性校验，区分「同线稿模板但不同上色」的图（不计盗用）。
    min_color_consistency / max_color_distance: feature 模式的颜色判定阈值（见 _match_feature）。
    regions: 关键花纹区块标注（JSON 路径 / dict / 列表），feature 模式下对每个区块做
             「局部图案 + 颜色」加强比较，输出 region_evidence（命中率见 min_region_match_rate）。
    visualize: 举证图输出路径；feature 模式下对最相似结果绘制内点连线图。
    highlight: 高亮图输出路径；feature 模式下在原图上标出"被盗区域"。
    """
    if method == "feature":
        return _match_feature(
            query, db, min_inliers=min_inliers, min_ratio=min_ratio,
            min_color_consistency=min_color_consistency,
            max_color_distance=max_color_distance,
            regions=regions, min_region_match_rate=min_region_match_rate,
            top=top, visualize=visualize, highlight=highlight,
        )
    if method == "phash":
        return _match_phash(query, db, threshold=threshold, top=top)

    files = _collect_db_files(db)
    with Image.open(query) as qimg:
        qh = dhash(qimg)

    results = []
    for f in files:
        if not os.path.isfile(f):
            continue
        try:
            with Image.open(f) as im:
                h = dhash(im)
        except Exception:
            continue
        d = hamming(qh, h)
        results.append({"path": f, "distance": d, "matched": d <= threshold})
    results.sort(key=lambda x: x["distance"])
    return {
        "query": query,
        "method": "dhash",
        "query_dhash": "%016x" % qh,
        "threshold": threshold,
        "results": results[:top],
    }


def _match_phash(query: str, db: str, *, threshold: int = 5, top: int = 5) -> dict:
    """用 pHash（DCT 感知哈希）溯源，对噪声 / 压缩 / 亮度鲁棒，按距离升序排列。"""
    files = _collect_db_files(db)
    results = []
    for f in files:
        if not os.path.isfile(f):
            continue
        try:
            d = featurematch.phash_distance(query, f)
        except Exception:
            continue
        results.append({"path": f, "distance": d, "matched": d <= threshold})
    results.sort(key=lambda x: x["distance"])
    return {
        "query": query,
        "method": "phash",
        "threshold": threshold,
        "results": results[:top],
    }


def _match_feature(
    query: str,
    db: str,
    *,
    min_inliers: int = 15,
    min_ratio: float = 0.3,
    min_color_consistency: float = 0.70,
    max_color_distance: float = 25.0,
    regions=None,
    min_region_match_rate: float = 0.5,
    top: int = 5,
    visualize: Optional[str] = None,
    highlight: Optional[str] = None,
) -> dict:
    """用 ORB + RANSAC 局部特征匹配溯源，按几何内点数降序排列。

    判定标准（结构 + 颜色双重校验）：
      1. 结构匹配：RANSAC 几何内点数 >= min_inliers 且内点率 >= min_ratio；
      2. 颜色匹配：内点局部颜色一致率 >= min_color_consistency
         且颜色距离中位数 <= max_color_distance。

    判定结果：
      - 结构 + 颜色都匹配  -> 「同源（盗图嫌疑）」
      - 结构匹配但颜色不符 -> 「同结构不同上色」（线稿模板相同，颜色/花纹不同，不计盗用）
      - 结构不匹配        -> 「不相关」

    regions: 关键花纹区块标注（坐标相对图库原图）。提供时对每个区块做
             「局部图案 + 颜色」加强比较，结果写入 region_evidence；
             命中率 >= min_region_match_rate 记为 region_matched=True。

    同时输出匹配区域覆盖率，并可选生成可视化举证图与"被盗区域"高亮图。
    """
    files = _collect_db_files(db)
    region_list = _load_regions(regions)
    results = []
    for f in files:
        if not os.path.isfile(f):
            continue
        try:
            ev = featurematch.match_features(query, f)
        except Exception:
            continue
        struct_matched = ev["inliers"] >= min_inliers and ev["inlier_ratio"] >= min_ratio
        coverage = featurematch.compute_coverage(ev) if ev["inliers"] > 0 else None
        color = None
        if ev["inliers"] > 0:
            try:
                color = featurematch.color_similarity(
                    query, f, ev["inlier_src_pts"], ev["inlier_dst_pts"]
                )
            except Exception:
                color = None
        consistency = (color or {}).get("consistency") or 0.0
        median_dist = (color or {}).get("median_distance", float("inf"))
        color_matched = consistency >= min_color_consistency and median_dist <= max_color_distance

        if not struct_matched:
            verdict, matched = "不相关", False
        elif color_matched:
            verdict, matched = "同源（盗图嫌疑）", True
        else:
            verdict, matched = "同结构不同上色（线稿模板相同，颜色/花纹不同，不计盗用）", False

        region_evidence = None
        if region_list:
            try:
                region_evidence = featurematch.compare_regions(f, query, region_list)
            except Exception:
                region_evidence = None
        region_matched = bool(
            region_evidence and region_evidence.get("match_rate", 0.0) >= min_region_match_rate
        )

        results.append({
            "path": f,
            "matches": ev["matches"],
            "inliers": ev["inliers"],
            "inlier_ratio": round(ev["inlier_ratio"], 4),
            "keypoints_a": ev["keypoints_a"],
            "keypoints_b": ev["keypoints_b"],
            "coverage": coverage,
            "color": color,
            "matched": matched,
            "verdict": verdict,
            "region_evidence": region_evidence,
            "region_matched": region_matched,
        })
    results.sort(key=lambda x: x["inliers"], reverse=True)
    results = results[:top]

    # 对最相似且判定的结果生成可视化举证图
    if visualize and results and results[0]["matched"]:
        try:
            featurematch.draw_match(query, results[0]["path"], visualize)
            results[0]["visualization"] = visualize
        except Exception:
            results[0]["visualization"] = None

    # 在原图上高亮"被盗区域"
    if highlight and results and results[0]["matched"]:
        try:
            featurematch.highlight_stolen_region(results[0]["path"], query, highlight)
            results[0]["highlight"] = highlight
        except Exception:
            results[0]["highlight"] = None

    # 对最相似结果报告噪声水平（检测"加噪伪装"）
    if results:
        try:
            results[0]["noise"] = {
                "query_noise": round(featurematch.noise_level(query), 1),
                "db_noise": round(featurematch.noise_level(results[0]["path"]), 1),
            }
        except Exception:
            results[0]["noise"] = None

    return {
        "query": query,
        "method": "feature",
        "min_inliers": min_inliers,
        "min_ratio": min_ratio,
        "min_color_consistency": min_color_consistency,
        "max_color_distance": max_color_distance,
        "min_region_match_rate": min_region_match_rate,
        "results": results,
    }
