"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys

from PIL import Image

from . import __version__, match, protect, verify
from . import stego
from .payload import unframe


def _parse_size(s: str):
    """解析尺寸字符串，如 "3300x2400"、"3300,2400"。"""
    s = s.strip().lower().replace("*", "x").replace(",", "x")
    try:
        w, h = s.split("x")
        return (int(w), int(h))
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(f"无法解析尺寸: {s!r}，应为 宽x高，如 3300x2400")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aegisbrush", description="OC 作品防盗用 + 反 AI 训练水印工具"
    )
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("protect", help="给图片施加分层防护")
    pr.add_argument("-i", "--input", required=True, help="输入图片路径")
    pr.add_argument("-o", "--output", required=True, help="输出图片路径")
    pr.add_argument("--owner", required=True, help="作者 / 版权人")
    pr.add_argument("--contact", help="联系方式（可选）")
    pr.add_argument("--license", dest="license", help="授权说明（可选）")
    pr.add_argument(
        "--no-ai", dest="no_ai", action="store_true", default=True,
        help="标记禁止 AI 训练（默认开启）",
    )
    pr.add_argument("--allow-ai", dest="no_ai", action="store_false", help="不标记禁止 AI 训练")
    pr.add_argument("--text", help="可见水印文字（默认取 --owner）")
    pr.add_argument(
        "--visible", dest="visible_mode",
        choices=["none", "tile", "single", "corner", "suite"],
        default="tile", help="可见水印模式（suite = 多层防盗水印套件）",
    )
    pr.add_argument("--opacity", type=float, default=0.35, help="可见水印透明度 0~1")
    pr.add_argument("--font-size", dest="font_size", type=int, help="可见水印字号")
    pr.add_argument("--font-path", dest="font_path", help="自定义水印字体文件路径")
    pr.add_argument("--top-text", dest="top_text", help="suite 模式顶部声明文字")
    pr.add_argument("--en-text", dest="en_text", help="suite 模式英文声明文字")
    pr.add_argument("--tile-text", dest="tile_text", help="suite 模式底层斜向平铺文字")
    pr.add_argument("--logo", help="Logo 图片路径（可选）")
    pr.add_argument(
        "--logo-position", dest="logo_position", default="bottom-right",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
    )
    pr.add_argument(
        "--stego", dest="stego_method", choices=["blindwm", "lsb", "both", "none"],
        default="blindwm", help="隐形水印方式（默认 blindwm 频域盲水印）",
    )
    pr.add_argument("--no-stego", dest="stego_method", action="store_const", const="none",
                    help="关闭隐形水印（等价 --stego none）")
    pr.add_argument("--adv", dest="adv_strength", type=float, default=0.0,
                    help="对抗扰动强度 0~100（默认 0 关闭）")
    pr.add_argument("--texture", dest="texture_kind", choices=["none", "noise", "hatch", "dots", "grid"],
                    default="none", help="底纹噪声类型（默认 none 关闭）")
    pr.add_argument("--texture-opacity", dest="texture_opacity", type=float, default=0.1,
                    help="底纹噪声强度 0~1（默认 0.1）")
    pr.add_argument("--texture-seed", dest="texture_seed", type=int, help="底纹噪声随机种子")
    pr.add_argument("--key", help="隐写 / HMAC 密钥（可选）")
    pr.add_argument("--seed", type=int, help="对抗噪声随机种子（可选，便于复现）")
    pr.add_argument("--format", dest="fmt", choices=["PNG", "JPEG", "JPG", "WEBP"],
                    help="输出格式（默认沿用原图格式）")
    pr.add_argument("--quality", type=int, default=95, help="JPEG 质量（默认 95）")
    pr.set_defaults(func=_cmd_protect)

    vf = sub.add_parser("verify", help="校验图片的元数据与隐写水印")
    vf.add_argument("-i", "--input", required=True)
    vf.add_argument("--key", help="签名密钥")
    vf.add_argument("--original", help="原图文件路径（自动读取其尺寸，用于还原被缩放的图）")
    vf.add_argument("--orig-size", dest="orig_size", type=_parse_size,
                    help="嵌入时的原始尺寸（如 3300x2400），手动指定原始尺寸")
    vf.set_defaults(func=_cmd_verify)

    mt = sub.add_parser("match", help="用内容指纹在图库中溯源疑似盗图")
    mt.add_argument("-i", "--input", required=True, help="疑似盗图路径")
    mt.add_argument("-d", "--db", required=True, help="原图库目录（或单个原图文件）")
    mt.add_argument("--method", choices=["dhash", "phash", "feature"], default="dhash",
                    help="比对方式：dhash 全局哈希 / phash DCT感知哈希（抗噪声）/ feature ORB+RANSAC（裁剪/旋转/改构图）")
    mt.add_argument("--threshold", type=int, default=10, help="dHash 汉明距离阈值（默认 10，越小越严）")
    mt.add_argument("--min-inliers", dest="min_inliers", type=int, default=15,
                    help="feature 模式判同源的 RANSAC 几何内点下限（默认 15）")
    mt.add_argument("--min-ratio", dest="min_ratio", type=float, default=0.3,
                    help="feature 模式判同源的几何内点率下限（默认 0.3）")
    mt.add_argument("--min-color-consistency", dest="min_color_consistency", type=float, default=0.70,
                    help="feature 模式判「颜色/花纹一致」的内点颜色一致率下限（默认 0.70）")
    mt.add_argument("--max-color-distance", dest="max_color_distance", type=float, default=25.0,
                    help="feature 模式判「颜色/花纹一致」的 Lab 颜色距离中位数上限（默认 25）")
    mt.add_argument("--regions", help="关键花纹区块标注 JSON（feature 模式做逐块图案加强比较）")
    mt.add_argument("--min-region-match-rate", dest="min_region_match_rate", type=float, default=0.5,
                    help="关键花纹区块命中率下限（默认 0.5）")
    mt.add_argument("--visualize", help="举证图输出路径（feature 模式，绘制内点连线图）")
    mt.add_argument("--highlight", help="高亮图输出路径（feature 模式，在原图上标出被盗区域）")
    mt.add_argument("--top", type=int, default=5, help="输出最相似的条数（默认 5）")
    mt.set_defaults(func=_cmd_match)

    dc = sub.add_parser("decode", help="提取并打印完整隐写载荷")
    dc.add_argument("-i", "--input", required=True)
    dc.add_argument("--key", help="签名密钥")
    dc.set_defaults(func=_cmd_decode)

    return p


def _cmd_protect(args: argparse.Namespace) -> None:
    summary = protect(
        args.input,
        args.output,
        owner=args.owner,
        contact=args.contact,
        license=args.license,
        no_ai=args.no_ai,
        text=args.text,
        visible_mode=args.visible_mode,
        opacity=args.opacity,
        font_size=args.font_size,
        font_path=args.font_path,
        top_text=args.top_text,
        en_text=args.en_text,
        tile_text=args.tile_text,
        logo=args.logo,
        logo_position=args.logo_position,
        stego_method=args.stego_method,
        adv_strength=args.adv_strength,
        texture_kind=args.texture_kind,
        texture_opacity=args.texture_opacity,
        texture_seed=args.texture_seed,
        key=args.key,
        seed=args.seed,
        fmt=args.fmt,
        quality=args.quality,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _cmd_verify(args: argparse.Namespace) -> None:
    result = verify(args.input, key=args.key, orig_size=args.orig_size, original=args.original)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _cmd_match(args: argparse.Namespace) -> None:
    result = match(
        args.input, args.db, threshold=args.threshold, top=args.top,
        method=args.method, min_inliers=args.min_inliers, min_ratio=args.min_ratio,
        min_color_consistency=args.min_color_consistency,
        max_color_distance=args.max_color_distance,
        regions=args.regions, min_region_match_rate=args.min_region_match_rate,
        visualize=args.visualize, highlight=args.highlight,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _cmd_decode(args: argparse.Namespace) -> None:
    img = Image.open(args.input).convert("RGB")
    key = args.key.encode("utf-8") if args.key else None
    found = unframe(stego.extract_lsb(img, key=key), key)
    if not found:
        print("未找到隐写水印。", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(found["payload"], ensure_ascii=False, indent=2))
    if found["signature_valid"] is not None:
        print("# signature_valid:", found["signature_valid"])


def main(argv=None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
