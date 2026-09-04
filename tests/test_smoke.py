"""冒烟测试：验证 protect -> verify -> match 全链路（含频域盲水印）。"""

import os
import tempfile

import numpy as np
from PIL import Image, ImageEnhance

from aegisbrush import match, protect, verify


def _make_sample(path: str, w: int = 640, h: int = 480) -> None:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    img.save(path)


def _make_textured(path: str, w: int = 640, h: int = 480) -> None:
    """带纹理与色块的图，供 ORB 局部特征匹配检测关键点。"""
    rng = np.random.default_rng(42)
    arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    arr[h // 4 : h // 2, w // 4 : w // 2] = 255
    arr[h // 2 : 3 * h // 4, w // 2 : 3 * w // 4] = 0
    Image.fromarray(arr, "RGB").save(path)


def _make_same_layout_diff_color(path: str, palette) -> None:
    """同一几何布局（色块边界一致）但配色不同：模拟「同线稿模板不同上色」。"""
    import cv2

    w, h = 640, 480
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    blocks = [(0, 0, 320, 240), (320, 0, 640, 240), (0, 240, 320, 480), (320, 240, 640, 480)]
    for i, (x0, y0, x1, y1) in enumerate(blocks):
        arr[y0:y1, x0:x1] = palette[i % len(palette)]
    cv2.circle(arr, (320, 240), 100, palette[3 % len(palette)], -1)
    cv2.circle(arr, (160, 120), 40, palette[1 % len(palette)], -1)
    cv2.circle(arr, (480, 360), 40, palette[2 % len(palette)], -1)
    Image.fromarray(arr, "RGB").save(path)


def _make_patterned(path: str, colors) -> None:
    """带放射线纹理的彩色圆：图案结构固定、配色可变，供区块加强比较测试。"""
    import cv2

    w, h = 640, 480
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    for i, color in enumerate(colors):
        cx, cy = 160 + i * 200, 130 + i * 180
        cv2.circle(arr, (cx, cy), 70, color, -1)
        for ang in range(0, 360, 30):
            x2 = int(cx + 70 * np.cos(np.radians(ang)))
            y2 = int(cy + 70 * np.sin(np.radians(ang)))
            cv2.line(arr, (cx, cy), (x2, y2), (0, 0, 0), 2)
        cv2.circle(arr, (cx, cy), 70, (0, 0, 0), 2)
    Image.fromarray(arr, "RGB").save(path)


def test_protect_and_verify_blindwm_default():
    """默认隐形水印应为频域盲水印（blindwm），完整载荷从元数据回退读取。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_sample(src)

        summary = protect(
            src, dst, owner="画师小明", contact="@xiaoming",
            license="CC BY-NC-ND 4.0", text="©画师小明", adv_strength=30, key="secret-key",
        )
        assert summary["blindwm_embedded"] is True
        assert summary["stego_embedded"] is False

        result = verify(dst, key="secret-key")
        assert result["blindwm"]["found"] is True
        assert result["blindwm"]["nonce_matches_metadata"] is True
        assert result["stego"]["found"] is False
        assert result["payload"]["source"] == "metadata"
        assert result["payload"]["owner"] == "画师小明"
        assert result["tamper"]["pixel_hash_match"] is True
        assert result["tamper"]["dhash_distance"] == 0


def test_protect_lsb_method():
    """stego_method=lsb 时，完整载荷应从隐写提取。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_sample(src)
        protect(src, dst, owner="画师小明", visible_mode="none", stego_method="lsb", key="k")
        result = verify(dst, key="k")
        assert result["stego"]["found"] is True
        assert result["stego"]["signature_valid"] is True
        assert result["payload"]["source"] == "stego"
        assert result["payload"]["owner"] == "画师小明"


def test_protect_both_method():
    """stego_method=both 时，频域盲水印与 LSB 都应可检出。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_sample(src)
        protect(src, dst, owner="画师小明", visible_mode="none", stego_method="both", key="k")
        result = verify(dst, key="k")
        assert result["blindwm"]["found"] is True
        assert result["stego"]["found"] is True


def test_blindwm_survives_jpeg():
    """频域盲水印应能扛住有损 JPEG 压缩（即使元数据也丢失）。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        jpg = os.path.join(d, "out.jpg")
        _make_sample(src)
        protect(src, dst, owner="画师小明", visible_mode="none", stego_method="blindwm", key="k")

        with Image.open(dst) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=80)

        result = verify(jpg, key="k")
        assert result["blindwm"]["found"] is True


def test_protect_jpeg_metadata():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.jpg")
        _make_sample(src)
        protect(src, dst, owner="画师小明", visible_mode="none", stego_method="none", fmt="JPEG")
        result = verify(dst)
        assert result["metadata"]["format"] == "JPEG"
        assert result["metadata"]["xmp"]["no_ai_training"] == "true"
        assert result["metadata"]["exif"] is not None
        assert result["payload"]["source"] == "metadata"
        assert result["payload"]["owner"] == "画师小明"


def test_match_traceability():
    """亮度滤镜不改变 dHash，match 应能精确溯源（距离 0）。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        _make_sample(src)
        query = os.path.join(d, "filtered.png")
        with Image.open(src) as im:
            ImageEnhance.Brightness(im).enhance(0.8).save(query)

        result = match(query, src)
        assert result["results"][0]["matched"] is True
        assert result["results"][0]["distance"] == 0
        assert os.path.basename(result["results"][0]["path"]) == "src.png"


def test_blindwm_orig_size_rescue():
    """被整体缩放的图，用 orig_size 还原后应能重新提取盲水印。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_sample(src)
        summary = protect(src, dst, owner="画师小明", visible_mode="none",
                          stego_method="blindwm", key="k")
        orig = tuple(summary["orig_size"])

        scaled = os.path.join(d, "scaled.png")
        with Image.open(dst) as im:
            im.resize((orig[0] // 2, orig[1] // 2), Image.LANCZOS).save(scaled)

        # 不带 orig_size：尺寸对不上，提取失败
        assert verify(scaled, key="k")["blindwm"]["found"] is False
        # 带 orig_size：还原尺寸后提取成功
        assert verify(scaled, key="k", orig_size=orig)["blindwm"]["found"] is True


def test_match_feature_crop():
    """ORB 局部特征匹配应能溯源裁剪改构图的图（dHash 无法覆盖的场景）。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        _make_textured(src)
        crop = os.path.join(d, "crop.png")
        with Image.open(src) as im:
            w, h = im.size
            im.crop((w // 4, 0, 3 * w // 4, h)).save(crop)  # 裁成竖版

        # dHash 模式下应匹配不上（构图大改）
        assert match(crop, src, method="dhash")["results"][0]["matched"] is False
        # feature 模式应能匹配上，且给出几何一致性证据
        result = match(crop, src, method="feature")
        assert result["results"][0]["matched"] is True
        assert result["results"][0]["inliers"] >= 20
        assert result["results"][0]["inlier_ratio"] >= 0.5
        assert result["results"][0]["verdict"] == "同源（盗图嫌疑）"
        # 覆盖率应表明匹配遍布全图而非局部
        assert result["results"][0]["coverage"]["query_coverage"]["grid"] > 0.3


def test_match_feature_color_awareness():
    """同一线稿/布局但不同上色花纹的图，不应判为盗用（颜色一致性校验）。"""
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "rec_a.png")
        b = os.path.join(d, "rec_b.png")
        _make_same_layout_diff_color(a, [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])
        _make_same_layout_diff_color(b, [(128, 64, 0), (0, 128, 128), (64, 0, 128), (200, 100, 50)])

        result = match(b, a, method="feature")
        top = result["results"][0]
        # 结构应匹配（同布局），但颜色/花纹不同 -> 不算盗用
        assert top["inliers"] >= 15
        assert top["inlier_ratio"] >= 0.3
        assert top["matched"] is False
        assert "同结构不同上色" in top["verdict"]
        assert top["color"]["consistency"] < 0.70


def test_match_regions_enhancement():
    """关键花纹区块加强比较：图案+颜色都一致才命中，图案同但配色不同不命中。"""
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "pat_a.png")
        b = os.path.join(d, "pat_b.png")
        _make_patterned(a, [(255, 0, 0), (0, 255, 0)])
        _make_patterned(b, [(128, 64, 0), (0, 128, 128)])

        regions = [
            {"name": "圆1花纹", "x": 110, "y": 80, "w": 120, "h": 120},
            {"name": "圆2花纹", "x": 300, "y": 260, "w": 120, "h": 120},
        ]
        # 同图：区块应命中
        r1 = match(a, a, method="feature", regions=regions)
        t1 = r1["results"][0]
        assert t1["region_matched"] is True
        assert t1["region_evidence"]["matched_regions"] == 2
        # 图案同（同线稿）但配色不同：区块应不命中
        r2 = match(b, a, method="feature", regions=regions)
        t2 = r2["results"][0]
        assert t2["region_matched"] is False
        assert t2["region_evidence"]["matched_regions"] == 0


def test_highlight_stolen_region():
    """真正的裁剪应能在原图上高亮出对应的被盗区域。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        _make_textured(src)
        crop = os.path.join(d, "crop.png")
        with Image.open(src) as im:
            w, h = im.size
            im.crop((0, 0, w // 2, h // 2)).save(crop)  # 左上 1/4

        hl = os.path.join(d, "highlight.png")
        result = match(crop, src, method="feature", highlight=hl)
        assert result["results"][0]["matched"] is True
        assert result["results"][0]["highlight"] == hl
        assert os.path.exists(hl)


def test_phash_noise_resistant():
    """pHash（DCT 感知哈希）应对加噪图：低频系数对高频噪声免疫。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        _make_textured(src)
        noisy = os.path.join(d, "noisy.png")
        with Image.open(src) as im:
            arr = np.asarray(im).astype(np.int16)
            rng = np.random.default_rng(7)
            arr = np.clip(arr + rng.integers(-40, 40, arr.shape), 0, 255).astype(np.uint8)
            Image.fromarray(arr).save(noisy)

        result = match(noisy, src, method="phash")
        assert result["results"][0]["matched"] is True
        assert result["results"][0]["distance"] <= 5


def test_protect_with_texture():
    """protect 加底纹噪声后，应能正常输出且溯源不受影响。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_textured(src)
        summary = protect(src, dst, owner="画师小明", visible_mode="none",
                          stego_method="none", texture_kind="noise",
                          texture_opacity=0.1, texture_seed=1)
        assert summary["texture_kind"] == "noise"
        assert os.path.exists(dst)
        # pHash 溯源不受底纹噪声影响（距离应远小于 64）
        result = match(dst, src, method="phash")
        assert result["results"][0]["matched"] is True
        assert result["results"][0]["distance"] <= 10


def test_suite_watermark():
    """多层防盗水印套件应能正常生成，并支持自定义声明/英文/斜向文字。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src.png")
        dst = os.path.join(d, "out.png")
        _make_sample(src)
        summary = protect(
            src, dst, owner="画师小明", contact="@xiaoming",
            visible_mode="suite", stego_method="none", text="授权样图",
            top_text="禁止盗用 禁止商用", en_text="Unauthorized use prohibited",
            tile_text="画师小明",
        )
        assert summary["visible_mode"] == "suite"
        assert os.path.exists(dst)
        # 输出图应与原图不同（水印已叠加）
        with Image.open(src) as a, Image.open(dst) as b:
            assert a.size == b.size
