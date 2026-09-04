"""ORB + RANSAC 局部特征匹配：检测裁剪/旋转/缩放/改构图后的盗图溯源。

借鉴 GitHub duplicate_img_finder（SIFT + RANSAC 几何验证）等项目的理念：
粗匹配（描述子距离）得到候选匹配对，再用 RANSAC 估计单应矩阵验证几何一致性。

为什么这能"表示盗图"：
  - 同源图之间，成百上千个匹配点满足同一个几何变换（单应矩阵），
    RANSAC 内点率接近 100%；
  - 无关图之间的匹配是随机噪声，无法形成一致单应，内点率极低。

提供三种输出：
  1. match_features  证据字典（匹配点/内点/内点率 + 内点坐标）
  2. compute_coverage 匹配区域覆盖率（网格 + 凸包），证明匹配遍布全图而非局部
  3. draw_match      可视化举证图（并排 + 内点连线），输出 PNG
"""

from __future__ import annotations

import numpy as np

_MAX_SIDE = 1000


def _read_gray(img):
    """读图片为灰度 numpy 数组，支持中文路径与 PIL Image。"""
    if isinstance(img, str):
        import cv2

        return cv2.imdecode(np.fromfile(img, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    return np.asarray(img.convert("L"))


def _shrink(im, max_side=_MAX_SIDE):
    import cv2

    h, w = im.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        return cv2.resize(im, (int(w * s), int(h * s)))
    return im


def _match(img1, img2, *, nfeatures=5000, dist_thresh=50, ransac_thresh=5.0):
    """执行完整匹配，返回内部结果（含关键点、匹配、内点掩码与图像）。"""
    import cv2

    a = _read_gray(img1)
    b = _read_gray(img2)
    if a is None or b is None:
        return None
    a, b = _shrink(a), _shrink(b)

    orb = cv2.ORB_create(nfeatures=nfeatures)
    kp1, d1 = orb.detectAndCompute(a, None)
    kp2, d2 = orb.detectAndCompute(b, None)
    if d1 is None or d2 is None:
        return None

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(d1, d2)
    good = [m for m in matches if m.distance < dist_thresh]

    mask = None
    if len(good) >= 4:
        src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransac_thresh)

    return {
        "img_a": a,
        "img_b": b,
        "kp_a": kp1,
        "kp_b": kp2,
        "good": good,
        "inlier_mask": mask,
    }


def match_features(
    img1,
    img2,
    *,
    nfeatures: int = 5000,
    dist_thresh: int = 50,
    ransac_thresh: float = 5.0,
) -> dict:
    """返回两张图的匹配证据字典（见模块 docstring）。

    除轻量统计外，还含内点坐标（缩放后坐标系），供覆盖率与可视化使用。
    """
    r = _match(img1, img2, nfeatures=nfeatures, dist_thresh=dist_thresh, ransac_thresh=ransac_thresh)
    empty = {
        "matches": 0,
        "inliers": 0,
        "inlier_ratio": 0.0,
        "keypoints_a": 0,
        "keypoints_b": 0,
        "inlier_src_pts": [],
        "inlier_dst_pts": [],
        "shape_a": [0, 0],
        "shape_b": [0, 0],
    }
    if r is None:
        return empty

    good = r["good"]
    mask = r["inlier_mask"]
    mask_arr = mask.ravel() if mask is not None else np.zeros(len(good), dtype=np.uint8)
    inliers = int(mask_arr.sum())

    src_pts = np.float32([r["kp_a"][m.queryIdx].pt for m in good])
    dst_pts = np.float32([r["kp_b"][m.trainIdx].pt for m in good])
    inlier_src = src_pts[mask_arr == 1]
    inlier_dst = dst_pts[mask_arr == 1]

    return {
        "matches": len(good),
        "inliers": inliers,
        "inlier_ratio": (inliers / len(good)) if good else 0.0,
        "keypoints_a": len(r["kp_a"]),
        "keypoints_b": len(r["kp_b"]),
        "inlier_src_pts": inlier_src.tolist(),
        "inlier_dst_pts": inlier_dst.tolist(),
        "shape_a": list(r["img_a"].shape[:2]),
        "shape_b": list(r["img_b"].shape[:2]),
    }


def _grid_coverage(pts, shape, grid=8) -> float:
    """网格覆盖率：内点覆盖的网格比例（0~1）。"""
    if len(pts) == 0:
        return 0.0
    h, w = shape
    if h <= 0 or w <= 0:
        return 0.0
    xs = np.clip(pts[:, 0], 0, w - 1).astype(np.float64)
    ys = np.clip(pts[:, 1], 0, h - 1).astype(np.float64)
    cells = set()
    for x, y in zip(xs, ys):
        cells.add((int(x * grid / w), int(y * grid / h)))
    return len(cells) / (grid * grid)


def _hull_coverage(pts, shape) -> float:
    """凸包覆盖率：内点凸包面积占图像面积的比例（0~1）。"""
    import cv2

    if len(pts) < 3:
        return 0.0
    h, w = shape
    hull = cv2.convexHull(pts.astype(np.float32))
    area = cv2.contourArea(hull)
    return min(1.0, area / (h * w))


def compute_coverage(ev: dict, grid: int = 8) -> dict:
    """基于证据字典计算匹配区域覆盖率。

    返回：
      query_coverage  内点在查询图（疑似盗图）上的覆盖率
      db_coverage     内点在原图（库图）上的覆盖率
    """
    src = np.array(ev.get("inlier_src_pts") or [], dtype=np.float32)
    dst = np.array(ev.get("inlier_dst_pts") or [], dtype=np.float32)
    shape_a = tuple(ev.get("shape_a") or [0, 0])
    shape_b = tuple(ev.get("shape_b") or [0, 0])
    return {
        "query_coverage": {
            "grid": round(_grid_coverage(dst, shape_b, grid), 4),
            "hull": round(_hull_coverage(dst, shape_b), 4),
        },
        "db_coverage": {
            "grid": round(_grid_coverage(src, shape_a, grid), 4),
            "hull": round(_hull_coverage(src, shape_a), 4),
        },
    }


def draw_match(
    img1,
    img2,
    out_path: str,
    *,
    nfeatures: int = 5000,
    dist_thresh: int = 50,
    ransac_thresh: float = 5.0,
    max_inliers: int = 200,
) -> str:
    """绘制可视化举证图：并排两张图，绿色连线 RANSAC 内点，输出 PNG。

    支持中文输出路径（用 imencode + tofile）。返回输出路径。
    """
    import cv2

    r = _match(img1, img2, nfeatures=nfeatures, dist_thresh=dist_thresh, ransac_thresh=ransac_thresh)
    if r is None:
        raise ValueError("无法读取图片或提取特征")

    good = r["good"]
    mask = r["inlier_mask"]
    mask_arr = mask.ravel() if mask is not None else np.zeros(len(good), dtype=np.uint8)
    # 只取内点，且限制数量避免连线过密
    inlier_dms = [m for i, m in enumerate(good) if mask_arr[i] == 1]
    if len(inlier_dms) > max_inliers:
        step = len(inlier_dms) // max_inliers
        inlier_dms = inlier_dms[:: max(1, step)][:max_inliers]

    canvas = cv2.drawMatches(
        r["img_a"], r["kp_a"], r["img_b"], r["kp_b"], inlier_dms, None,
        matchColor=(0, 255, 0), singlePointColor=(255, 0, 0),
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    ok, buf = cv2.imencode(".png", canvas)
    if not ok:
        raise RuntimeError("举证图编码失败")
    buf.tofile(out_path)
    return out_path


def highlight_stolen_region(
    original,
    query,
    out_path: str,
    *,
    nfeatures: int = 5000,
    dist_thresh: int = 50,
    ransac_thresh: float = 5.0,
) -> str:
    """在原图上高亮"被盗区域"（疑似盗图对应原图的那块区域）。

    原理：用 RANSAC 估计的单应矩阵 H（原图 -> 疑似盗图），
    把疑似盗图的边界四角逆投影回原图坐标，得到一个四边形，
    即"疑似盗图取自原图的哪块区域"，用红色半透明填充 + 描边高亮。
    """
    import cv2

    r = _match(original, query, nfeatures=nfeatures, dist_thresh=dist_thresh, ransac_thresh=ransac_thresh)
    if r is None:
        raise ValueError("无法读取图片或提取特征")

    good = r["good"]
    mask = r["inlier_mask"]
    mask_arr = mask.ravel() if mask is not None else np.zeros(len(good), dtype=np.uint8)
    if mask_arr.sum() < 4:
        raise ValueError("几何内点不足，无法估计单应矩阵")

    src = np.float32([r["kp_a"][m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([r["kp_b"][m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, ransac_thresh)
    if H is None:
        raise ValueError("无法估计单应矩阵")

    # H 是 原图(img_a) -> 疑似盗图(img_b) 的映射
    a_h, a_w = r["img_a"].shape[:2]
    b_h, b_w = r["img_b"].shape[:2]
    corners_q = np.float32([[0, 0], [b_w, 0], [b_w, b_h], [0, b_h]]).reshape(-1, 1, 2)
    H_inv = np.linalg.inv(H)
    corners_a = cv2.perspectiveTransform(corners_q, H_inv).reshape(-1, 2)

    color = cv2.cvtColor(r["img_a"], cv2.COLOR_GRAY2BGR)
    overlay = color.copy()
    cv2.fillPoly(overlay, [corners_a.astype(np.int32)], (0, 0, 255))
    cv2.addWeighted(overlay, 0.35, color, 0.65, 0, color)
    cv2.polylines(color, [corners_a.astype(np.int32)], True, (0, 0, 255), 3)

    ok, buf = cv2.imencode(".png", color)
    if not ok:
        raise RuntimeError("高亮图编码失败")
    buf.tofile(out_path)
    return out_path


def noise_level(img) -> float:
    """用拉普拉斯方差估算噪声水平（数值越大，高频噪声越多）。"""
    import cv2

    g = _read_gray(img)
    if g is None:
        return 0.0
    lap = cv2.Laplacian(g, cv2.CV_32F)
    return float(lap.var())


def phash(img, hash_size: int = 8) -> int:
    """DCT 感知哈希（pHash）：取 DCT 低频系数，对噪声/压缩/亮度鲁棒。"""
    import cv2

    g = _read_gray(img)
    if g is None:
        return 0
    g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(g))
    low = dct[:hash_size, :hash_size]
    med = np.median(low)
    bits = "".join("1" if b else "0" for b in (low > med).flatten())
    return int(bits, 2)


def phash_distance(img1, img2) -> int:
    """两张图的 pHash 汉明距离（越小越相似，对噪声鲁棒）。"""
    return (phash(img1) ^ phash(img2)).bit_count()


def _read_color(img):
    """读图片为 BGR 彩色 numpy 数组，支持中文路径与 PIL Image。"""
    if isinstance(img, str):
        import cv2

        return cv2.imdecode(np.fromfile(img, dtype=np.uint8), cv2.IMREAD_COLOR)
    import cv2

    arr = np.asarray(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def color_similarity(
    img1,
    img2,
    inlier_src_pts,
    inlier_dst_pts,
    *,
    patch: int = 5,
    dist_thresh: float = 30.0,
    max_samples: int = 500,
) -> dict:
    """基于 RANSAC 内点的局部颜色一致性，判断两图「上色 / 花纹」是否一致。

    背景：ORB 是灰度特征，只看线稿轮廓，会把「同一线稿模板但不同上色」的两张图
    误判为同源。本函数补齐颜色维度：

      - ORB 内点大多落在轮廓 / 花纹边界处；
      - 真盗图连颜色花纹都照抄，内点处局部颜色高度一致；
      - 同线稿不同上色：轮廓位置相同，但两侧颜色 / 花纹不同，一致率明显下降。

    用 Lab 颜色距离（贴近人眼感知）度量，取 patch 中位数以抗噪声 / 压缩。

    返回：
      consistency      内点颜色一致率（0~1，越高颜色越像）
      median_distance  内点 Lab 距离中位数
      mean_distance    内点 Lab 距离均值
      sampled          实际采样内点数
    """
    import cv2

    empty = {
        "consistency": 0.0,
        "median_distance": float("inf"),
        "mean_distance": float("inf"),
        "sampled": 0,
    }
    src_pts = inlier_src_pts or []
    dst_pts = inlier_dst_pts or []
    if not src_pts or not dst_pts or len(src_pts) != len(dst_pts):
        return empty

    a = _read_color(img1)
    b = _read_color(img2)
    if a is None or b is None:
        return empty
    a, b = _shrink(a), _shrink(b)

    src = np.asarray(src_pts, dtype=np.float32)
    dst = np.asarray(dst_pts, dtype=np.float32)
    n = len(src)
    if n > max_samples:  # 均匀抽样，控制耗时（500 点已足够统计一致率）
        idx = np.linspace(0, n - 1, max_samples).astype(int)
        src, dst = src[idx], dst[idx]

    half = patch // 2
    dists = []
    for (x1, y1), (x2, y2) in zip(src, dst):
        x1i, y1i = int(round(x1)), int(round(y1))
        x2i, y2i = int(round(x2)), int(round(y2))
        p1 = a[max(0, y1i - half): y1i + half + 1, max(0, x1i - half): x1i + half + 1]
        p2 = b[max(0, y2i - half): y2i + half + 1, max(0, x2i - half): x2i + half + 1]
        if p1.size == 0 or p2.size == 0:
            continue
        m1 = np.median(p1.reshape(-1, 3), axis=0).astype(np.float32)
        m2 = np.median(p2.reshape(-1, 3), axis=0).astype(np.float32)
        l1 = cv2.cvtColor(np.uint8([[m1]]), cv2.COLOR_BGR2LAB)[0, 0]
        l2 = cv2.cvtColor(np.uint8([[m2]]), cv2.COLOR_BGR2LAB)[0, 0]
        dists.append(float(np.linalg.norm(l1.astype(np.float32) - l2.astype(np.float32))))

    if not dists:
        return empty
    arr = np.array(dists, dtype=np.float64)
    return {
        "consistency": round(float((arr < dist_thresh).mean()), 4),
        "median_distance": round(float(np.median(arr)), 1),
        "mean_distance": round(float(arr.mean()), 1),
        "sampled": len(arr),
    }


def _scale_for_match(im, max_side=_MAX_SIDE):
    """把图像缩放到 max_side 以内，返回 (缩放图, 缩放系数)。"""
    import cv2

    h, w = im.shape[:2]
    if max(h, w) <= max_side:
        return im, 1.0
    s = max_side / max(h, w)
    return cv2.resize(im, (int(w * s), int(h * s))), s


def estimate_homography(
    img1,
    img2,
    *,
    nfeatures: int = 5000,
    dist_thresh: int = 50,
    ransac_thresh: float = 5.0,
):
    """估计 img1(原图) -> img2(疑似图) 的单应矩阵（原始像素坐标）。

    用缩放后匹配 + 坐标换算，避免大图直接跑 ORB 的性能与内存问题。
    返回 (H, ok)；失败时返回 (None, False)。
    """
    import cv2

    a = _read_gray(img1)
    b = _read_gray(img2)
    if a is None or b is None:
        return None, False
    a_small, sa = _scale_for_match(a)
    b_small, sb = _scale_for_match(b)

    orb = cv2.ORB_create(nfeatures=nfeatures)
    kp1, d1 = orb.detectAndCompute(a_small, None)
    kp2, d2 = orb.detectAndCompute(b_small, None)
    if d1 is None or d2 is None:
        return None, False

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    good = [m for m in bf.match(d1, d2) if m.distance < dist_thresh]
    if len(good) < 4:
        return None, False

    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    h_small, _ = cv2.findHomography(src, dst, cv2.RANSAC, ransac_thresh)
    if h_small is None:
        return None, False

    # 坐标换算：orig1 --*sa--> small1 --H_small--> small2 --/sb--> orig2
    s1 = np.diag([sa, sa, 1.0])
    s2inv = np.diag([1.0 / sb, 1.0 / sb, 1.0])
    return s2inv @ h_small @ s1, True


def _patch_color_sim(pa, pb) -> float:
    """抗噪的颜色相似度（0~1，越接近 1 越像）。

    用 patch 的 25/50/75 分位颜色（Lab 空间）距离映射，而非颜色直方图：
    分位颜色对加噪/压缩鲁棒（噪声被统计平均抵消），且能保留花纹的颜色分布。
    """
    import cv2

    if pa.size == 0 or pb.size == 0:
        return 0.0

    def lab_profile(p):
        arr = p.reshape(-1, 3).astype(np.float32)
        q = np.percentile(arr, [25, 50, 75], axis=0).astype(np.uint8)
        return cv2.cvtColor(q.reshape(1, -1, 3), cv2.COLOR_BGR2LAB)[0].astype(np.float32)

    la = lab_profile(pa)
    lb = lab_profile(pb)
    d = float(np.linalg.norm(la - lb))
    return max(0.0, 1.0 - d / 60.0)


def _patch_pattern(pa, pb, nfeatures: int = 1000):
    """两个对齐 patch 的局部 ORB 图案匹配，返回 (内点数, 内点率)。"""
    import cv2

    ga = cv2.cvtColor(pa, cv2.COLOR_BGR2GRAY) if pa.ndim == 3 else pa
    gb = cv2.cvtColor(pb, cv2.COLOR_BGR2GRAY) if pb.ndim == 3 else pb
    orb = cv2.ORB_create(nfeatures=nfeatures)
    kp1, d1 = orb.detectAndCompute(ga, None)
    kp2, d2 = orb.detectAndCompute(gb, None)
    if d1 is None or d2 is None or len(d1) < 4 or len(d2) < 4:
        return 0, 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    good = [m for m in bf.match(d1, d2) if m.distance < 50]
    if len(good) < 4:
        return 0, 0.0
    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(mask.sum()) if mask is not None else 0
    ratio = inliers / len(good) if good else 0.0
    return inliers, ratio


def compare_regions(
    img1,
    img2,
    regions,
    *,
    nfeatures: int = 3000,
    color_thresh: float = 0.5,
    pattern_ratio: float = 0.85,
) -> dict:
    """关键花纹区块加强比较：把用户标注的原图区块逐一与疑似盗图比对。

    img1: 原图（区块坐标所在图）；img2: 疑似盗图。
    regions: 区块列表，每项 {"name": str, "x": int, "y": int, "w": int, "h": int}。

    做法：估计 img1 -> img2 单应矩阵，把原图 warp 到疑似图视角，再在同一
    坐标下裁每个区块的 patch，比较「局部颜色直方图 + 局部 ORB 图案」。

    返回：
      regions          每个区块的证据（color_sim / pattern_inliers / pattern_ratio / matched）
      matched_regions  颜色与图案都命中的区块数
      total_regions    有效区块数
      match_rate       命中率（0~1）
    """
    import cv2

    base = {
        "regions": [],
        "matched_regions": 0,
        "total_regions": 0,
        "match_rate": 0.0,
    }
    h, ok = estimate_homography(img1, img2, nfeatures=nfeatures)
    if not ok:
        base["error"] = "无法估计单应矩阵（区块对齐失败）"
        return base

    a = _read_color(img1)
    b = _read_color(img2)
    if a is None or b is None:
        base["error"] = "无法读取图片"
        return base
    bh, bw = b.shape[:2]
    warped = cv2.warpPerspective(a, h, (bw, bh))

    out = []
    matched = 0
    for r in regions:
        try:
            x, y, w, hh = int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])
        except (KeyError, TypeError, ValueError):
            continue
        pa = warped[max(0, y):y + hh, max(0, x):x + w]
        pb = b[max(0, y):y + hh, max(0, x):x + w]
        if pa.size == 0 or pb.size == 0:
            continue
        color_sim = _patch_color_sim(pa, pb)
        inliers, ratio = _patch_pattern(pa, pb)
        hit = color_sim >= color_thresh and ratio >= pattern_ratio
        if hit:
            matched += 1
        out.append({
            "name": str(r.get("name", "")),
            "rect": [x, y, w, hh],
            "color_sim": round(color_sim, 4),
            "pattern_inliers": inliers,
            "pattern_ratio": round(ratio, 4),
            "matched": hit,
        })
    total = len(out)
    base["regions"] = out
    base["matched_regions"] = matched
    base["total_regions"] = total
    base["match_rate"] = round(matched / total, 4) if total else 0.0
    return base
