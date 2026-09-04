# -*- coding: utf-8 -*-
"""AegisBrush 桌面图形界面（CustomTkinter）。

提供可视化人机交互：
- 作品防护：选择原图 -> 配置分层防护参数 -> 一键防护 -> 原图/成图对比 + 处理摘要
- 盗图溯源：选择疑似图与原图 -> 一键溯源 -> 证据链指标 + 举证图 + 被盗区域高亮图
- 外观：浅色 / 深色 / 跟随系统，主题色切换

运行：python -m aegisbrush.gui
"""

from __future__ import annotations

import json
import os
import random
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

try:
    from . import pipeline
except ImportError:  # 直接以脚本方式运行本文件时
    import pipeline

APP_TITLE = "AegisBrush · OC 作品防护与盗图溯源"
FONT_FAMILY = "Microsoft YaHei UI"

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_ICON_ICO = os.path.join(_ASSET_DIR, "icon.ico")
_ICON_PNG = os.path.join(_ASSET_DIR, "icon_256.png")

THEMES = ["blue", "green", "dark-blue"]
APPEARANCES = {"跟随系统": "system", "浅色": "light", "深色": "dark"}
VISIBLE_MODES = ["套件水印", "平铺", "居中", "右下角", "关闭"]
VISIBLE_MODE_MAP = {"套件水印": "suite", "平铺": "tile", "居中": "single", "右下角": "corner", "关闭": "none"}
STEGO_METHODS = ["盲水印(频域)", "LSB 隐写", "两者都要", "关闭"]
STEGO_MAP = {"盲水印(频域)": "blindwm", "LSB 隐写": "lsb", "两者都要": "both", "关闭": "none"}
TEXTURE_KINDS = ["关闭", "噪点", "斜线", "圆点", "网格"]
TEXTURE_MAP = {"关闭": "none", "噪点": "noise", "斜线": "hatch", "圆点": "dots", "网格": "grid"}
OUT_FORMATS = ["PNG", "JPEG", "WEBP"]

# 常用中文字体（名称 -> 字体文件路径），按存在性动态收录
FONT_PRESETS = [
    ("微软雅黑", "C:/Windows/Fonts/msyh.ttc"),
    ("微软雅黑粗体", "C:/Windows/Fonts/msyhbd.ttc"),
    ("黑体", "C:/Windows/Fonts/simhei.ttf"),
    ("宋体", "C:/Windows/Fonts/simsun.ttc"),
    ("楷体", "C:/Windows/Fonts/simkai.ttf"),
    ("华文楷体", "C:/Windows/Fonts/STKAITI.TTF"),
]

DEFAULT_LICENSE = "保留所有权利，未经授权禁止使用、转载、商用"
DEFAULT_TILE_TEXT = "禁止盗用"

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".aegisbrush")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def _int_or_none(text: str) -> Optional[int]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _blank(text: str) -> Optional[str]:
    text = (text or "").strip()
    return text or None


class ToolTip:
    """轻量悬停提示：鼠标悬停时在控件下方显示一段说明文字。"""

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip, text=self.text, justify="left", wraplength=340,
            background="#ffffe0", foreground="#333333", relief="solid",
            borderwidth=1, font=(FONT_FAMILY, 10), padx=8, pady=6,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _cancel(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:  # noqa: BLE001
                pass
            self.after_id = None


class Lightbox(ctk.CTkToplevel):
    """全图预览灯箱：滚轮缩放、Ctrl+左键拖动平移、Esc/按钮关闭。"""

    def __init__(self, master, path: str, title: str = "全图预览"):
        super().__init__(master)
        self.title(title)
        self.attributes("-topmost", True)
        self.configure(fg_color=("#14171a", "#0b0e11"))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        max_w, max_h = int(sw * 0.90), int(sh * 0.80)

        self._orig = None
        self._scale = 1.0
        self._scale_min = 0.02
        self._scale_max = 12.0
        self._offset = [0, 0]
        self._drag = None
        self._photo = None
        self._img_id = None

        err = None
        try:
            self._orig = Image.open(path).convert("RGB")
            ow, oh = self._orig.size
            self._scale = min(max_w / ow, max_h / oh, 1.0)  # 初始适配屏幕，不放大
            self._scale_max = min(12.0, 4800.0 / max(ow, oh))  # 限制渲染边长，防内存爆炸
            view_w, view_h = max(int(ow * self._scale), 1), max(int(oh * self._scale), 1)
            info = f"{os.path.basename(path)}  ·  {ow} × {oh}"
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            view_w, view_h = 480, 160
            info = f"无法打开图片：{exc}"

        ctk.CTkLabel(self, text=info, font=(FONT_FAMILY, 12),
                     text_color=("gray40", "gray70")).pack(pady=(8, 4))

        if err is None:
            self._canvas = tk.Canvas(self, width=view_w, height=view_h,
                                     bg="#0b0e11", highlightthickness=0, cursor="crosshair")
            self._canvas.pack(padx=12, pady=(0, 4))
            self._render()
            self._canvas.bind("<MouseWheel>", self._on_wheel)
            self._canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
            self._canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))
            self._canvas.bind("<ButtonPress-1>", self._on_press)
            self._canvas.bind("<B1-Motion>", self._on_drag)
            self._canvas.bind("<ButtonRelease-1>", self._on_release)
        else:
            ctk.CTkLabel(self, text=info, font=(FONT_FAMILY, 14)).pack(padx=40, pady=40)

        ctk.CTkLabel(self, text=path, font=(FONT_FAMILY, 10), text_color=("gray40", "gray70"),
                     wraplength=int(sw * 0.7), justify="center").pack(padx=20, pady=(0, 2))
        self._hint = ctk.CTkLabel(self, text="滚轮缩放  |  Ctrl+左键拖动  |  Esc 关闭",
                                  font=(FONT_FAMILY, 10), text_color=("gray40", "gray70"))
        self._hint.pack(pady=(0, 6))
        ctk.CTkButton(self, text="关闭", width=90, height=28, font=(FONT_FAMILY, 12),
                      command=self.destroy).pack(pady=(0, 10))

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        rw = max(self.winfo_reqwidth(), 320)
        rh = max(self.winfo_reqheight(), 160)
        x = max((sw - rw) // 2, 0)
        y = max((sh - rh) // 2, 0)
        self.geometry(f"{rw}x{rh}+{x}+{y}")

    # ------------------------------------------------------ 缩放 / 平移
    def _render(self):
        if self._orig is None:
            return
        w = max(int(self._orig.width * self._scale), 1)
        h = max(int(self._orig.height * self._scale), 1)
        img = self._orig.resize((w, h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        if self._img_id is None:
            self._img_id = self._canvas.create_image(
                self._offset[0], self._offset[1], image=self._photo, anchor="nw")
        else:
            self._canvas.itemconfigure(self._img_id, image=self._photo)
            self._canvas.coords(self._img_id, self._offset[0], self._offset[1])
        if hasattr(self, "_hint"):
            self._hint.configure(text=f"缩放 {self._scale * 100:.0f}%  |  滚轮缩放  Ctrl+左键拖动  Esc 关闭")

    def _on_wheel(self, event):
        factor = 1.15 if getattr(event, "delta", 0) > 0 else (1 / 1.15)
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, x, y, factor):
        if self._orig is None:
            return
        new_scale = max(self._scale_min, min(self._scale * factor, self._scale_max))
        if abs(new_scale - self._scale) < 1e-9:
            return
        # 以鼠标位置为锚点缩放，保持鼠标下的点不动
        mx = x - self._offset[0]
        my = y - self._offset[1]
        self._offset[0] = x - mx * (new_scale / self._scale)
        self._offset[1] = y - my * (new_scale / self._scale)
        self._scale = new_scale
        self._render()

    def _on_press(self, event):
        if self._orig is None:
            return
        if event.state & 0x0004:  # Ctrl 按下才允许拖动
            self._drag = (event.x, event.y, self._offset[0], self._offset[1])

    def _on_drag(self, event):
        if self._drag is None:
            return
        sx, sy, ox, oy = self._drag
        self._offset[0] = ox + (event.x - sx)
        self._offset[1] = oy + (event.y - sy)
        if self._img_id is not None:
            self._canvas.coords(self._img_id, self._offset[0], self._offset[1])

    def _on_release(self, _event):
        self._drag = None


class RegionAnnotator(ctk.CTkToplevel):
    """关键花纹区块标注窗口：在原图上拖拽框选 + 命名，输出区块列表。

    - 滚轮缩放、Ctrl+左键拖拽平移（与灯箱一致）
    - 区块用表格展示，坐标保存为原始像素坐标（相对原图）
    - 重新打开时载入上一次的标注
    """

    def __init__(self, master, image_path: str, on_done: Callable[[list], None],
                 initial_regions: Optional[list] = None):
        super().__init__(master)
        self.title("标注关键花纹区块")
        self.geometry("1060x720")
        self.after(120, self.lift)
        self.image_path = image_path
        self.on_done = on_done
        # 载入上一次的标注（深拷贝，避免影响主窗口状态）
        self.regions: list = [dict(r) for r in (initial_regions or [])]

        self._orig = None
        self._photo = None
        self._img_id = None
        self._scale = 1.0
        self._scale_min = 0.05
        self._scale_max = 8.0
        self._offset = [0, 0]
        self._drag = None       # Ctrl 平移状态
        self._start = None      # 画框起始点
        self._rubber = None     # 画框临时矩形
        self._box_ids: dict = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(left, bg="#202124", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.15))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.15))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._zoom_label = ctk.CTkLabel(left, text="缩放 100%", font=ctk.CTkFont(FONT_FAMILY, 11),
                                        text_color=("gray40", "gray70"))
        self._zoom_label.grid(row=1, column=0, padx=4, pady=(0, 2), sticky="w")

        side = ctk.CTkFrame(self, width=370)
        side.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ns")
        side.grid_propagate(False)
        side.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(side, text="已标注区块", font=ctk.CTkFont(FONT_FAMILY, 15, "bold")).grid(
            row=0, column=0, padx=10, pady=(12, 4), sticky="w")

        table_frame = ctk.CTkFrame(side, fg_color="transparent")
        table_frame.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        cols = ("name", "x", "y", "w", "h")
        self.table = ttk.Treeview(table_frame, columns=cols, show="headings", height=16, selectmode="browse")
        for c, (title, width) in {
            "name": ("名称", 150), "x": ("X", 45), "y": ("Y", 45), "w": ("宽", 45), "h": ("高", 45),
        }.items():
            self.table.heading(c, text=title)
            self.table.column(c, width=width, anchor="w" if c == "name" else "center", stretch=(c == "name"))
        self.table.grid(row=0, column=0, sticky="nsew")
        self._style_tree()
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)

        btn_row = ctk.CTkFrame(side, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=10, pady=2, sticky="ew")
        ctk.CTkButton(btn_row, text="删除选中", width=110, command=self._delete_selected).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="完成并保存", width=110, command=self._finish).pack(side="left")
        ctk.CTkLabel(side, text="滚轮缩放 · Ctrl+左键拖拽平移 · 左键拖拽框选花纹，松开后命名",
                     font=ctk.CTkFont(FONT_FAMILY, 11), text_color=("gray40", "gray70"),
                     justify="left", wraplength=330).grid(
            row=3, column=0, padx=10, pady=(12, 12), sticky="w")

        self._load_image()

    def _style_tree(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background="#2b2b2b", fieldbackground="#2b2b2b",
                        foreground="#e8e8e8", rowheight=26, font=(FONT_FAMILY, 11))
        style.configure("Treeview.Heading", background="#1f1f1f", foreground="#d0d0d0",
                        font=(FONT_FAMILY, 11, "bold"))
        style.map("Treeview", background=[("selected", "#3b6ea5")], foreground=[("selected", "#ffffff")])

    def _load_image(self):
        try:
            self._orig = Image.open(self.image_path).convert("RGB")
            ow, oh = self._orig.size
            self._scale = min(1.0, 620 / ow, 560 / oh)
            self._scale_max = min(8.0, 4800.0 / max(ow, oh))
        except Exception as exc:  # noqa: BLE001
            self.canvas.create_text(200, 100, text=f"无法加载图片：{exc}", fill="red")
            return
        self._render()
        self._refresh_table()

    # ------------------------------------------------------ 缩放 / 平移 / 渲染
    def _render(self):
        if self._orig is None:
            return
        w = max(int(self._orig.width * self._scale), 1)
        h = max(int(self._orig.height * self._scale), 1)
        img = self._orig.resize((w, h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        if self._img_id is None:
            self._img_id = self.canvas.create_image(
                self._offset[0], self._offset[1], image=self._photo, anchor="nw")
        else:
            self.canvas.itemconfigure(self._img_id, image=self._photo)
            self.canvas.coords(self._img_id, self._offset[0], self._offset[1])
        self._redraw_boxes()
        self._zoom_label.configure(text=f"缩放 {self._scale * 100:.0f}%")

    def _redraw_boxes(self):
        for ids in self._box_ids.values():
            for i in ids:
                self.canvas.delete(i)
        self._box_ids = {}
        for r in self.regions:
            self._draw_box(r)

    def _draw_box(self, rect):
        x0 = self._offset[0] + rect["x"] * self._scale
        y0 = self._offset[1] + rect["y"] * self._scale
        x1 = self._offset[0] + (rect["x"] + rect["w"]) * self._scale
        y1 = self._offset[1] + (rect["y"] + rect["h"]) * self._scale
        rid = self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ffd54f", width=2)
        tid = self.canvas.create_text(x0, max(0, y0 - 8), anchor="sw", text=rect["name"], fill="#ffd54f")
        self._box_ids[rect["name"]] = (rid, tid)

    def _on_wheel(self, event):
        factor = 1.15 if getattr(event, "delta", 0) > 0 else (1 / 1.15)
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, x, y, factor):
        if self._orig is None:
            return
        new_scale = max(self._scale_min, min(self._scale * factor, self._scale_max))
        if abs(new_scale - self._scale) < 1e-9:
            return
        mx = x - self._offset[0]
        my = y - self._offset[1]
        self._offset[0] = x - mx * (new_scale / self._scale)
        self._offset[1] = y - my * (new_scale / self._scale)
        self._scale = new_scale
        self._render()

    # ------------------------------------------------------ 框选 / 平移事件
    def _on_press(self, event):
        if self._orig is None:
            return
        if event.state & 0x0004:  # Ctrl+左键 = 平移
            self._drag = (event.x, event.y, self._offset[0], self._offset[1])
            self._start = None
            return
        self._start = (event.x, event.y)
        if self._rubber is not None:
            self.canvas.delete(self._rubber)
        self._rubber = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#ff5252", width=2)

    def _on_drag(self, event):
        if self._drag is not None:
            sx, sy, ox, oy = self._drag
            self._offset[0] = ox + (event.x - sx)
            self._offset[1] = oy + (event.y - sy)
            if self._img_id is not None:
                self.canvas.coords(self._img_id, self._offset[0], self._offset[1])
            self._redraw_boxes()
            return
        if self._start is None:
            return
        x0, y0 = self._start
        self.canvas.coords(self._rubber, x0, y0, event.x, event.y)

    def _on_release(self, event):
        if self._drag is not None:
            self._drag = None
            return
        if self._start is None:
            return
        x0, y0 = self._start
        x1, y1 = event.x, event.y
        self._start = None
        if self._rubber is not None:
            self.canvas.delete(self._rubber)
            self._rubber = None
        if abs(x1 - x0) < 5 or abs(y1 - y0) < 5:
            return
        x0o = int((x0 - self._offset[0]) / self._scale)
        y0o = int((y0 - self._offset[1]) / self._scale)
        x1o = int((x1 - self._offset[0]) / self._scale)
        y1o = int((y1 - self._offset[1]) / self._scale)
        name = ctk.CTkInputDialog(text="给这个区块命名（如：头部花纹）：", title="命名区块").get_input()
        if name is None:  # 用户点击「取消」：不添加区块
            return
        if not name.strip():  # 输入为空或纯空格：自动命名
            name = f"区块{len(self.regions) + 1}"
        rect = {
            "name": name,
            "x": min(x0o, x1o),
            "y": min(y0o, y1o),
            "w": abs(x1o - x0o),
            "h": abs(y1o - y0o),
        }
        self.regions.append(rect)
        self._draw_box(rect)
        self._refresh_table()

    # ------------------------------------------------------ 表格
    def _refresh_table(self):
        for item in self.table.get_children():
            self.table.delete(item)
        for i, r in enumerate(self.regions):
            self.table.insert("", "end", iid=str(i), values=(r["name"], r["x"], r["y"], r["w"], r["h"]))

    def _delete_selected(self):
        sel = self.table.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.regions):
            r = self.regions.pop(idx)
            ids = self._box_ids.pop(r["name"], None)
            if ids:
                for i in ids:
                    self.canvas.delete(i)
            self._refresh_table()

    def _finish(self):
        self.on_done(self.regions)
        self.destroy()


class AegisBrushApp(ctk.CTk):
    """AegisBrush 主窗口。"""

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.title(APP_TITLE)
        self.geometry("1220x820")
        self.minsize(1000, 680)
        self._apply_icon()

        self._fonts = {
            "title": ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            "section": ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            "label": ctk.CTkFont(family=FONT_FAMILY, size=13),
            "small": ctk.CTkFont(family=FONT_FAMILY, size=12),
            "metric": ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"),
        }
        self._previews: dict[str, ctk.CTkImage] = {}  # 持有 CTkImage 引用，防 GC
        self._tooltips: list[ToolTip] = []  # 持有 ToolTip 引用，防 GC
        self._image_paths: dict = {}  # 预览框 -> 原图路径（点击打开灯箱）
        self._lightbox = None

        # ---- 变量：防护 ----
        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        self.owner_var = tk.StringVar()
        self.contact_var = tk.StringVar()
        self.license_var = tk.StringVar(value=DEFAULT_LICENSE)
        self.key_var = tk.StringVar()
        self.visible_var = tk.StringVar(value="套件水印")
        self.opacity_var = tk.DoubleVar(value=0.35)
        self.font_size_var = tk.StringVar(value="48")
        self.font_path_var = tk.StringVar()
        self.font_choice_var = tk.StringVar(value="默认（自动匹配中文字体）")
        self.top_text_var = tk.StringVar(value="禁止盗用 · 禁止转载 · 禁止修改 · 禁止商用")
        self.en_text_var = tk.StringVar(value="Unauthorized use prohibited")
        self.tile_text_var = tk.StringVar(value=DEFAULT_TILE_TEXT)
        self.stego_var = tk.StringVar(value="盲水印(频域)")
        self.adv_var = tk.DoubleVar(value=0.0)
        self.texture_var = tk.StringVar(value="关闭")
        self.texture_opacity_var = tk.DoubleVar(value=0.1)
        self.texture_seed_var = tk.StringVar(value="42")
        self.fmt_var = tk.StringVar(value="PNG")
        self.quality_var = tk.IntVar(value=95)

        # ---- 变量：溯源 ----
        self.query_var = tk.StringVar()
        self.original_var = tk.StringVar()
        self.trace_key_var = tk.StringVar()
        self.min_inliers_var = tk.IntVar(value=15)
        self.min_ratio_var = tk.DoubleVar(value=0.3)
        self.regions: list = []          # 关键花纹区块（原始坐标，相对原图）
        self.regions_file: Optional[str] = None

        # 字体下拉选项（按系统中实际存在的字体构建）
        self.font_choices = ["默认（自动匹配中文字体）"]
        self.font_choice_map = {"默认（自动匹配中文字体）": ""}
        for name, path in FONT_PRESETS:
            if os.path.exists(path):
                self.font_choices.append(name)
                self.font_choice_map[name] = path
        self.font_choices.append("自定义字体文件…")

        self._load_config()
        self._build_topbar()
        self._build_tabs()
        self._build_statusbar()

        self.log("AegisBrush 已启动。请在「作品防护」或「盗图溯源」页开始操作。")

    # ------------------------------------------------------ 配置持久化
    def _load_config(self):
        """读取上次使用的版权信息作为默认值。"""
        try:
            if os.path.isfile(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("owner"):
                    self.owner_var.set(cfg["owner"])
                if cfg.get("contact"):
                    self.contact_var.set(cfg["contact"])
                if cfg.get("license"):
                    self.license_var.set(cfg["license"])
                if cfg.get("key"):
                    self.key_var.set(cfg["key"])
        except Exception:  # noqa: BLE001
            pass

    def _save_config(self):
        """记住本次填写的版权信息，下次启动自动填入。"""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            cfg = {
                "owner": self.owner_var.get().strip(),
                "contact": self.contact_var.get().strip(),
                "license": self.license_var.get().strip(),
                "key": self.key_var.get().strip(),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[配置] 保存失败：{exc}")

    # ------------------------------------------------------------------ 图标
    def _apply_icon(self):
        """设置窗口与任务栏图标（.ico + .png 双保险）。"""
        try:
            if os.path.isfile(_ICON_ICO):
                self.iconbitmap(_ICON_ICO)
        except Exception:  # noqa: BLE001
            pass
        try:
            if os.path.isfile(_ICON_PNG):
                self.iconphoto(True, tk.PhotoImage(file=_ICON_PNG))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 布局
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, height=54, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bar, text="AegisBrush", font=self._fonts["title"],
                     text_color=("dodgerblue3", "#6db3ff")).grid(
            row=0, column=0, padx=(20, 6), pady=10, sticky="w")
        ctk.CTkLabel(bar, text="OC 作品分层防护 · 隐形水印 · 盗图溯源",
                     font=self._fonts["small"], text_color=("gray40", "gray70")).grid(
            row=0, column=1, pady=10, sticky="w")

        ctk.CTkLabel(bar, text="外观", font=self._fonts["small"]).grid(
            row=0, column=2, padx=(20, 4), pady=10, sticky="e")
        appear = ctk.CTkOptionMenu(bar, values=list(APPEARANCES.keys()), width=110,
                                   font=self._fonts["small"], command=self._on_appearance)
        appear.grid(row=0, column=3, padx=(0, 12), pady=10, sticky="e")
        appear.set("跟随系统")

        ctk.CTkLabel(bar, text="主题", font=self._fonts["small"]).grid(
            row=0, column=4, padx=(0, 4), pady=10, sticky="e")
        theme = ctk.CTkOptionMenu(bar, values=THEMES, width=110, font=self._fonts["small"],
                                  command=lambda v: ctk.set_default_color_theme(v))
        theme.grid(row=0, column=5, padx=(0, 20), pady=10, sticky="e")
        theme.set("blue")

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, padx=14, pady=(10, 6), sticky="nsew")
        self.tabs.add("作品防护")
        self.tabs.add("盗图溯源")
        self._build_protect_tab(self.tabs.tab("作品防护"))
        self._build_trace_tab(self.tabs.tab("盗图溯源"))

    def _build_statusbar(self):
        frame = ctk.CTkFrame(self, height=40, corner_radius=0)
        frame.grid(row=2, column=0, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        self.status_label = ctk.CTkLabel(frame, text="就绪", font=self._fonts["small"],
                                         text_color=("gray40", "gray70"))
        self.status_label.grid(row=0, column=0, padx=(20, 12), pady=8, sticky="w")
        self.progress = ctk.CTkProgressBar(frame, mode="indeterminate", height=8)
        self.progress.grid(row=0, column=1, padx=(0, 20), pady=8, sticky="ew")
        self.progress.set(0)

        self.log_box = ctk.CTkTextbox(self, height=118, font=self._fonts["small"], wrap="word")
        self.log_box.grid(row=3, column=0, padx=14, pady=(0, 14), sticky="ew")
        self.log_box.configure(state="disabled")

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------ 作品防护标签页
    def _build_protect_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        left = ctk.CTkScrollableFrame(tab, width=600, label_text="防护参数", label_font=self._fonts["section"])
        left.grid(row=0, column=0, padx=(0, 12), sticky="nsw")
        left.grid_columnconfigure(0, weight=1)
        vcmd = (self.register(self._validate_int), "%P")

        row = 0
        # ---- 输入与输出
        sec = self._section(left, "输入与输出", "选择要防护的原图；输出留空则自动保存到原图同目录。")
        sec.grid(row=row, column=0, padx=12, pady=(8, 6), sticky="ew")
        row += 1
        r = 2
        ctk.CTkLabel(sec, text="原图", font=self._fonts["label"]).grid(row=r, column=0, padx=8, pady=6, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.src_var, placeholder_text="选择要防护的图片…").grid(
            row=r, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(sec, text="浏览", width=68, font=self._fonts["small"],
                      command=lambda: self._pick_image(self.src_var, "选择原图", on_done=self._preview_src)).grid(
            row=r, column=2, padx=8, pady=6)
        r += 1
        ctk.CTkLabel(sec, text="输出", font=self._fonts["label"]).grid(row=r, column=0, padx=8, pady=6, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.dst_var, placeholder_text="留空则自动输出到原图同目录").grid(
            row=r, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(sec, text="另存为", width=68, font=self._fonts["small"],
                      command=self._pick_output).grid(row=r, column=2, padx=8, pady=6)
        r += 1
        fmt_lbl = ctk.CTkLabel(sec, text="格式", font=self._fonts["label"])
        fmt_lbl.grid(row=r, column=0, padx=8, pady=6, sticky="w")
        fmt_menu = ctk.CTkOptionMenu(sec, values=OUT_FORMATS, variable=self.fmt_var, width=120,
                                     font=self._fonts["small"], command=self._on_format_change)
        fmt_menu.grid(row=r, column=1, padx=6, pady=6, sticky="w")
        self._tip(fmt_lbl, "输出图片格式。选择 JPEG 才能调整压缩质量；PNG 无损但体积更大。")
        r += 1
        self.quality_slider, self.quality_val, self.quality_reset = self._slider_row(
            sec, r, "JPEG质量", self.quality_var, 1, 100, 99, "{}", default=95,
            help_text="JPEG 压缩质量：越高越清晰、文件越大；仅对 JPEG 格式生效。")
        sec.grid_columnconfigure(1, weight=1)

        # ---- 版权信息
        sec = self._section(left, "版权信息", "写入图片元数据与隐形水印，作为维权证据；密钥用于签名与置乱，溯源时需一致。")
        sec.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
        row += 1
        r = 2
        for label, var, ph, tip in (
            ("作者", self.owner_var, "必填，如：墨然大玉", "版权人署名，必填。会写入元数据与隐形水印。"),
            ("联系", self.contact_var, "如：闲鱼号 / 邮箱", "联系方式，方便他人联系授权，也作为维权线索。"),
            ("授权", self.license_var, "授权说明", "授权声明，默认禁止使用、转载与商用，可自行修改。"),
            ("密钥", self.key_var, "推荐设置，溯源时需一致", "隐写与盲水印的密钥；不设置则使用固定种子，仅防君子。"),
        ):
            lbl = ctk.CTkLabel(sec, text=label, font=self._fonts["label"])
            lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
            ctk.CTkEntry(sec, textvariable=var, placeholder_text=ph).grid(row=r, column=1, padx=6, pady=5, sticky="ew")
            self._tip(lbl, tip)
            r += 1
        sec.grid_columnconfigure(1, weight=1)

        # ---- 可见水印
        sec = self._section(left, "可见水印", "套件水印 = 六层防盗水印（斜向平铺 + 顶部声明 + 英文 + 中央大字 + 右侧竖排 + 底部署名）。")
        sec.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
        row += 1
        r = 2
        style_lbl = ctk.CTkLabel(sec, text="样式", font=self._fonts["label"])
        style_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkOptionMenu(sec, values=VISIBLE_MODES, variable=self.visible_var, width=150,
                          font=self._fonts["small"], command=lambda _: self._toggle_suite()).grid(
            row=r, column=1, padx=6, pady=5, sticky="w")
        self._tip(style_lbl, "水印排布方式：套件（多层）、平铺、居中、右下角，或关闭可见水印。")
        r += 1
        self._slider_row(sec, r, "透明度", self.opacity_var, 0.0, 1.0, 100, "{:.2f}", default=0.35,
                         help_text="可见水印的不透明度：越大越醒目，越小越不影响画面。")
        r += 1
        size_lbl = ctk.CTkLabel(sec, text="字号", font=self._fonts["label"])
        size_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.font_size_var, width=80, placeholder_text="自动",
                     validate="key", validatecommand=vcmd).grid(row=r, column=1, padx=6, pady=5, sticky="w")
        self._tip(size_lbl, "可见水印字号，仅数字；留空则按图片尺寸自动计算。")
        r += 1
        font_lbl = ctk.CTkLabel(sec, text="字体", font=self._fonts["label"])
        font_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        self.font_menu = ctk.CTkOptionMenu(sec, values=self.font_choices, variable=self.font_choice_var,
                                           width=190, font=self._fonts["small"], command=self._on_font_choice)
        self.font_menu.grid(row=r, column=1, padx=6, pady=5, sticky="w")
        ctk.CTkButton(sec, text="浏览…", width=68, font=self._fonts["small"],
                      command=self._pick_custom_font).grid(row=r, column=2, padx=8, pady=5, sticky="w")
        self._tip(font_lbl, "选择水印字体：默认自动匹配系统中文字体，也可指定字体文件。")
        r += 1
        # suite 专属文本
        self.suite_frame = ctk.CTkFrame(sec, fg_color="transparent")
        self.suite_frame.grid(row=r, column=0, columnspan=4, padx=4, pady=4, sticky="ew")
        self.suite_frame.grid_columnconfigure(1, weight=1)
        sr = 0
        for label, var, ph, tip in (
            ("顶部声明", self.top_text_var, "顶部中文声明", "套件水印顶部的横排中文声明。"),
            ("英文声明", self.en_text_var, "英文声明", "套件水印顶部的英文声明。"),
            ("斜向平铺", self.tile_text_var, "斜向平铺文字", "套件水印底层斜向平铺的大字。"),
        ):
            lbl = ctk.CTkLabel(self.suite_frame, text=label, font=self._fonts["small"])
            lbl.grid(row=sr, column=0, padx=6, pady=4, sticky="w")
            ctk.CTkEntry(self.suite_frame, textvariable=var, placeholder_text=ph).grid(
                row=sr, column=1, padx=6, pady=4, sticky="ew")
            self._tip(lbl, tip)
            sr += 1
        sec.grid_columnconfigure(1, weight=1)

        # ---- 隐形水印与防伪
        sec = self._section(left, "隐形水印与防伪", "隐形水印肉眼不可见、可事后提取取证；对抗扰动与底纹用于干扰 AI 训练与特征提取。")
        sec.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
        row += 1
        r = 2
        stego_lbl = ctk.CTkLabel(sec, text="隐形水印", font=self._fonts["label"])
        stego_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkOptionMenu(sec, values=STEGO_METHODS, variable=self.stego_var, width=150,
                          font=self._fonts["small"]).grid(row=r, column=1, padx=6, pady=5, sticky="w")
        self._tip(stego_lbl, "盲水印（频域）：抗压缩/缩放，推荐；LSB：能携带完整信息但对像素改动极脆弱。")
        r += 1
        self._slider_row(sec, r, "对抗扰动", self.adv_var, 0.0, 20.0, 200, "{:.1f}", default=0.0,
                         help_text="叠加人眼不可见的高频噪声，干扰 AI 特征提取/训练；0 表示关闭，过大会影响画质。")
        r += 1
        tex_lbl = ctk.CTkLabel(sec, text="底纹", font=self._fonts["label"])
        tex_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkOptionMenu(sec, values=TEXTURE_KINDS, variable=self.texture_var, width=150,
                          font=self._fonts["small"]).grid(row=r, column=1, padx=6, pady=5, sticky="w")
        self._tip(tex_lbl, "叠加半透明纹理（噪点/斜线/圆点/网格），视觉防伪并干扰特征提取。")
        r += 1
        self._slider_row(sec, r, "底纹强度", self.texture_opacity_var, 0.0, 0.5, 100, "{:.2f}", default=0.1,
                         help_text="底纹纹理的不透明度；数值过大可能影响画面清晰度与色彩。")
        r += 1
        seed_lbl = ctk.CTkLabel(sec, text="底纹种子", font=self._fonts["label"])
        seed_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        seed_box = ctk.CTkFrame(sec, fg_color="transparent")
        seed_box.grid(row=r, column=1, columnspan=2, padx=6, pady=5, sticky="w")
        ctk.CTkEntry(seed_box, textvariable=self.texture_seed_var, width=120,
                     validate="key", validatecommand=vcmd).pack(side="left")
        ctk.CTkButton(seed_box, text="随机", width=60, font=self._fonts["small"],
                      command=self._random_seed).pack(side="left", padx=(8, 0))
        self._tip(seed_lbl, "底纹纹理的随机种子；相同种子生成相同纹理，便于复现。点「随机」换一个。")
        sec.grid_columnconfigure(1, weight=1)

        # ---- 操作按钮
        self.protect_btn = ctk.CTkButton(left, text="开始防护", height=40, font=self._fonts["section"],
                                         command=self._on_protect)
        self.protect_btn.grid(row=row, column=0, padx=12, pady=(14, 10), sticky="ew")

        # 右侧：预览区
        right = ctk.CTkFrame(tab)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="原图", font=self._fonts["section"]).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")
        self.src_preview = ctk.CTkLabel(right, text="尚未选择图片", width=620, height=230, fg_color=("gray90", "gray20"), corner_radius=8)
        self.src_preview.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        ctk.CTkLabel(right, text="处理后", font=self._fonts["section"]).grid(row=2, column=0, padx=12, pady=(4, 4), sticky="w")
        self.dst_preview = ctk.CTkLabel(right, text="等待处理", width=620, height=230, fg_color=("gray90", "gray20"), corner_radius=8)
        self.dst_preview.grid(row=3, column=0, padx=12, pady=(0, 6), sticky="ew")

        self.protect_summary = ctk.CTkTextbox(right, height=120, font=self._fonts["small"], wrap="word")
        self.protect_summary.grid(row=4, column=0, padx=12, pady=(4, 10), sticky="ew")
        self.protect_summary.insert("0.0", "处理摘要将显示在此处。")
        self.protect_summary.configure(state="disabled")

        self._on_format_change(self.fmt_var.get())

    # ------------------------------------------------------ 盗图溯源标签页
    def _build_trace_tab(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        left = ctk.CTkScrollableFrame(tab, width=560, label_text="溯源设置", label_font=self._fonts["section"])
        left.grid(row=0, column=0, padx=(0, 12), sticky="nsw")
        left.grid_columnconfigure(0, weight=1)
        vcmd = (self.register(self._validate_int), "%P")

        row = 0
        sec = self._section(left, "待比对图片", "把疑似盗图与你的原图做 ORB 局部特征比对，输出取证证据。")
        sec.grid(row=row, column=0, padx=12, pady=(8, 6), sticky="ew")
        row += 1
        r = 2
        ctk.CTkLabel(sec, text="疑似图", font=self._fonts["label"]).grid(row=r, column=0, padx=8, pady=6, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.query_var, placeholder_text="疑似盗图路径").grid(row=r, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(sec, text="浏览", width=68, font=self._fonts["small"],
                      command=lambda: self._pick_image(self.query_var, "选择疑似盗图", on_done=self._preview_query)).grid(
            row=r, column=2, padx=8, pady=6)
        r += 1
        ctk.CTkLabel(sec, text="原图", font=self._fonts["label"]).grid(row=r, column=0, padx=8, pady=6, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.original_var, placeholder_text="原作者原始图路径").grid(row=r, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(sec, text="浏览", width=68, font=self._fonts["small"],
                      command=lambda: self._pick_image(self.original_var, "选择原图", on_done=self._preview_original)).grid(
            row=r, column=2, padx=8, pady=6)
        sec.grid_columnconfigure(1, weight=1)

        sec = self._section(left, "比对参数", "阈值越小越严格；内点率 = RANSAC 几何自洽匹配占比，越高越可信。")
        sec.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
        row += 1
        r = 2
        key_lbl = ctk.CTkLabel(sec, text="密钥", font=self._fonts["label"])
        key_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.trace_key_var, placeholder_text="防护时使用的密钥").grid(
            row=r, column=1, padx=6, pady=5, sticky="ew")
        self._tip(key_lbl, "验证隐形水印时使用的密钥，需与防护时一致才能提取。")
        r += 1
        inlier_lbl = ctk.CTkLabel(sec, text="最小内点数", font=self._fonts["label"])
        inlier_lbl.grid(row=r, column=0, padx=8, pady=5, sticky="w")
        ctk.CTkEntry(sec, textvariable=self.min_inliers_var, width=90,
                     validate="key", validatecommand=vcmd).grid(row=r, column=1, padx=6, pady=5, sticky="w")
        self._tip(inlier_lbl, "RANSAC 几何内点下限：匹配点需足够多才判同源，默认 15。")
        r += 1
        self._slider_row(sec, r, "最小内点率", self.min_ratio_var, 0.0, 1.0, 100, "{:.2f}", default=0.3,
                         help_text="内点占匹配点的比例下限：几何上越自洽越可信，默认 0.3。")
        sec.grid_columnconfigure(1, weight=1)

        sec = self._section(left, "关键花纹区块", "在原图上框选头部 / 胸 / 手臂 / 大腿等独特花纹，溯源时逐块做图案加强比较：命中越多，盗图证据越实锤。")
        sec.grid(row=row, column=0, padx=12, pady=6, sticky="ew")
        row += 1
        self.region_status = ctk.CTkLabel(sec, text="未标注区块（可选）", font=self._fonts["small"],
                                          text_color=("gray40", "gray70"), justify="left", wraplength=500)
        self.region_status.grid(row=2, column=0, columnspan=2, padx=8, pady=(2, 4), sticky="w")
        btnrow = ctk.CTkFrame(sec, fg_color="transparent")
        btnrow.grid(row=3, column=0, columnspan=2, padx=8, pady=(0, 6), sticky="w")
        ctk.CTkButton(btnrow, text="标注区块", width=100, font=self._fonts["small"],
                      command=self._open_annotator).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btnrow, text="清空标注", width=100, font=self._fonts["small"],
                      command=self._clear_regions).pack(side="left")

        self.trace_btn = ctk.CTkButton(left, text="一键溯源（特征匹配 + 隐形水印验证）", height=40,
                                       font=self._fonts["section"], command=self._on_trace)
        self.trace_btn.grid(row=row, column=0, padx=12, pady=(14, 10), sticky="ew")

        # 右侧：结果区
        right = ctk.CTkFrame(tab)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)
        right.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(right, text="疑似图", font=self._fonts["section"]).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")
        ctk.CTkLabel(right, text="原图", font=self._fonts["section"]).grid(row=0, column=1, padx=12, pady=(10, 4), sticky="w")
        self.query_preview = ctk.CTkLabel(right, text="尚未选择", height=150, fg_color=("gray90", "gray20"), corner_radius=8)
        self.query_preview.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="nsew")
        self.original_preview = ctk.CTkLabel(right, text="尚未选择", height=150, fg_color=("gray90", "gray20"), corner_radius=8)
        self.original_preview.grid(row=1, column=1, padx=12, pady=(0, 6), sticky="nsew")

        ctk.CTkLabel(right, text="举证图（特征内点连线）", font=self._fonts["section"]).grid(row=2, column=0, padx=12, pady=(4, 4), sticky="w")
        ctk.CTkLabel(right, text="被盗区域高亮（原图）", font=self._fonts["section"]).grid(row=2, column=1, padx=12, pady=(4, 4), sticky="w")
        self.match_preview = ctk.CTkLabel(right, text="待生成", height=150, fg_color=("gray90", "gray20"), corner_radius=8)
        self.match_preview.grid(row=3, column=0, padx=12, pady=(0, 6), sticky="nsew")
        self.highlight_preview = ctk.CTkLabel(right, text="待生成", height=150, fg_color=("gray90", "gray20"), corner_radius=8)
        self.highlight_preview.grid(row=3, column=1, padx=12, pady=(0, 6), sticky="nsew")

        # 输出路径提示
        self.match_path_label = ctk.CTkLabel(right, text="举证图：待生成", font=self._fonts["small"],
                                             text_color=("gray40", "gray70"), anchor="w")
        self.match_path_label.grid(row=4, column=0, padx=12, pady=(0, 2), sticky="w")
        self.highlight_path_label = ctk.CTkLabel(right, text="高亮图：待生成", font=self._fonts["small"],
                                                 text_color=("gray40", "gray70"), anchor="w")
        self.highlight_path_label.grid(row=4, column=1, padx=12, pady=(0, 2), sticky="w")

        # 证据可视化面板
        panel = ctk.CTkFrame(right)
        panel.grid(row=5, column=0, columnspan=2, padx=12, pady=(2, 10), sticky="ew")
        panel.grid_columnconfigure(0, weight=0)  # 覆盖率标题列：自适应内容宽度
        panel.grid_columnconfigure(1, weight=1)  # 进度条列：占满剩余宽度

        self.verdict_label = ctk.CTkLabel(panel, text="等待溯源", font=self._fonts["metric"],
                                          text_color=("gray40", "gray70"),
                                          justify="left", wraplength=500)
        self.verdict_label.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 0), sticky="w")
        self.ratio_bar = ctk.CTkProgressBar(panel, height=10)
        self.ratio_bar.grid(row=1, column=0, columnspan=2, padx=12, pady=(4, 2), sticky="ew")
        self.ratio_bar.set(0)
        self.ratio_caption = ctk.CTkLabel(panel, text="内点率：--", font=self._fonts["small"],
                                          text_color=("gray40", "gray70"))
        self.ratio_caption.grid(row=2, column=0, columnspan=2, padx=12, sticky="w")

        self.metrics_label = ctk.CTkLabel(panel, text="匹配点 --   几何内点 --", font=self._fonts["small"])
        self.metrics_label.grid(row=3, column=0, columnspan=2, padx=12, pady=(6, 0), sticky="w")

        self.db_cov_caption = ctk.CTkLabel(panel, text="原图覆盖率 --", font=self._fonts["small"],
                                           width=120, anchor="w")
        self.db_cov_caption.grid(row=4, column=0, padx=(12, 4), pady=(6, 0), sticky="w")
        self.db_cov_bar = ctk.CTkProgressBar(panel, height=8)
        self.db_cov_bar.grid(row=4, column=1, padx=(0, 12), pady=(6, 0), sticky="ew")
        self.db_cov_bar.set(0)

        self.query_cov_caption = ctk.CTkLabel(panel, text="疑似图覆盖率 --", font=self._fonts["small"],
                                              width=120, anchor="w")
        self.query_cov_caption.grid(row=5, column=0, padx=(12, 4), pady=(4, 0), sticky="w")
        self.query_cov_bar = ctk.CTkProgressBar(panel, height=8)
        self.query_cov_bar.grid(row=5, column=1, padx=(0, 12), pady=(4, 0), sticky="ew")
        self.query_cov_bar.set(0)

        self.region_label = ctk.CTkLabel(panel, text="关键花纹：未标注", font=self._fonts["small"],
                                          text_color=("gray40", "gray70"), justify="left", wraplength=500)
        self.region_label.grid(row=6, column=0, columnspan=2, padx=12, pady=(6, 0), sticky="w")
        self.noise_label = ctk.CTkLabel(panel, text="噪声水平：--", font=self._fonts["small"],
                                        text_color=("gray40", "gray70"))
        self.noise_label.grid(row=7, column=0, columnspan=2, padx=12, pady=(4, 0), sticky="w")
        self.verify_label = ctk.CTkLabel(panel, text="隐形水印：--", font=self._fonts["small"])
        self.verify_label.grid(row=8, column=0, columnspan=2, padx=12, pady=(2, 8), sticky="w")

        # 窗口缩放时动态更新长文本换行宽度，使结论区自适应
        panel.bind("<Configure>", self._on_trace_panel_resize)

    # ------------------------------------------------------ 通用组件
    def _section(self, parent, title, help_text=""):
        frame = ctk.CTkFrame(parent)
        ctk.CTkLabel(frame, text=title, font=self._fonts["section"]).grid(
            row=0, column=0, columnspan=4, padx=8, pady=(6, 2), sticky="w")
        if help_text:
            ctk.CTkLabel(frame, text=help_text, font=self._fonts["small"],
                         text_color=("gray40", "gray70"), justify="left", wraplength=520).grid(
                row=1, column=0, columnspan=4, padx=8, pady=(0, 4), sticky="w")
        return frame

    def _slider_row(self, parent, row, text, var, from_, to, steps, fmt, default=None, help_text=None):
        """统一滑块行：标签 | 滑块(可拉伸) | 数值 | 重置按钮。返回 (slider, value_label, reset_btn)。"""
        if default is None:
            default = var.get()
        lbl = ctk.CTkLabel(parent, text=text, font=self._fonts["label"])
        lbl.grid(row=row, column=0, padx=8, pady=6, sticky="w")
        if help_text:
            self._tip(lbl, help_text)
        val = ctk.CTkLabel(parent, text=fmt.format(var.get()), width=54, font=self._fonts["small"])
        val.grid(row=row, column=2, padx=(2, 4), pady=6, sticky="e")
        slider = ctk.CTkSlider(parent, from_=from_, to=to, number_of_steps=steps, variable=var,
                               command=lambda v: val.configure(text=fmt.format(v)))
        slider.grid(row=row, column=1, padx=(2, 4), pady=6, sticky="ew")

        def reset():
            var.set(default)
            val.configure(text=fmt.format(default))

        btn = ctk.CTkButton(parent, text="重置", width=48, height=26, font=self._fonts["small"], command=reset)
        btn.grid(row=row, column=3, padx=(4, 8), pady=6)
        parent.grid_columnconfigure(1, weight=1)
        return slider, val, btn

    def _tip(self, widget, text):
        self._tooltips.append(ToolTip(widget, text))

    def _validate_int(self, text):
        """输入校验：只允许空串或纯数字。"""
        return text == "" or text.isdigit()

    def _toggle_suite(self):
        is_suite = self.visible_var.get() == "套件水印"
        state = "normal" if is_suite else "disabled"
        for child in self.suite_frame.winfo_children():
            child.configure(state=state)

    def _on_format_change(self, choice):
        is_jpeg = choice == "JPEG"
        state = "normal" if is_jpeg else "disabled"
        self.quality_slider.configure(state=state)
        self.quality_val.configure(state=state)
        self.quality_reset.configure(state=state)

    def _on_font_choice(self, choice):
        if choice == "自定义字体文件…":
            self._pick_custom_font()
            return
        self.font_path_var.set(self.font_choice_map.get(choice, ""))

    def _pick_custom_font(self):
        path = filedialog.askopenfilename(title="选择字体文件", filetypes=[("字体文件", "*.ttf *.ttc *.otf")])
        if path:
            self.font_path_var.set(path)
            self.font_choice_var.set(os.path.basename(path))

    def _random_seed(self):
        self.texture_seed_var.set(str(random.randint(1, 999999)))

    # ------------------------------------------------------ 文件选择
    def _pick_file(self, var, title, filetypes):
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if path:
            var.set(path)

    def _pick_image(self, var, title, on_done=None):
        path = filedialog.askopenfilename(
            title=title,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")])
        if path:
            var.set(path)
            if on_done:
                on_done(path)

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="选择输出文件",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WEBP", "*.webp")])
        if path:
            self.dst_var.set(path)

    # ------------------------------------------------------ 预览
    def _preview(self, path, label: ctk.CTkLabel, key: str, max_w=500, max_h=240):
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                w, h = im.size
                hi = im.resize((max(w * 2, 2), max(h * 2, 2)), Image.Resampling.LANCZOS)
                img = ctk.CTkImage(light_image=hi, dark_image=hi, size=(w, h))
            self._previews[key] = img
            label.configure(image=img, text="")
            self._image_paths[label] = path
            self._bind_lightbox(label)
        except Exception as exc:  # noqa: BLE001
            label.configure(image=None, text=f"预览失败：{exc}")

    def _preview_src(self, path):
        self._preview(path, self.src_preview, "src", max_w=620, max_h=230)

    def _preview_query(self, path):
        self._preview(path, self.query_preview, "query", max_w=460, max_h=180)

    def _preview_original(self, path):
        self._preview(path, self.original_preview, "original", max_w=460, max_h=180)

    # ------------------------------------------------------ 灯箱预览
    def _bind_lightbox(self, label: ctk.CTkLabel):
        """给预览框绑定点击事件（只绑定一次）。"""
        if getattr(label, "_ab_lightbox", False):
            return
        label._ab_lightbox = True
        label.configure(cursor="hand2")
        label.bind("<Button-1>", lambda e: self._open_lightbox_from(label))

    def _open_lightbox_from(self, label: ctk.CTkLabel):
        path = self._image_paths.get(label)
        if path and os.path.isfile(path):
            self._open_lightbox(path)

    def _open_lightbox(self, path: str):
        if self._lightbox is not None and self._lightbox.winfo_exists():
            self._lightbox.destroy()
        self._lightbox = Lightbox(self, path)

    # ------------------------------------------------------ 日志与状态
    def log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_status(self, text: str, busy: bool = False):
        self.status_label.configure(text=text)
        if busy:
            self.progress.start()
            self.protect_btn.configure(state="disabled")
            self.trace_btn.configure(state="disabled")
        else:
            self.progress.stop()
            self.protect_btn.configure(state="normal")
            self.trace_btn.configure(state="normal")

    def _set_text(self, box: ctk.CTkTextbox, text: str):
        box.configure(state="normal")
        box.delete("0.0", "end")
        box.insert("0.0", text)
        box.configure(state="disabled")

    def _run_async(self, fn: Callable, on_ok: Callable, on_err: Callable):
        self._set_status("处理中，请稍候…", busy=True)

        def worker():
            try:
                result = fn()
                self.after(0, lambda: (self._set_status("完成"), on_ok(result)))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: (self._set_status("出错"), on_err(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_appearance(self, choice):
        ctk.set_appearance_mode(APPEARANCES.get(choice, "system"))

    # ------------------------------------------------------ 防护逻辑
    def _collect_protect_kwargs(self):
        owner = self.owner_var.get().strip()
        if not owner:
            raise ValueError("请填写「作者」信息")
        src = self.src_var.get().strip()
        if not src or not os.path.isfile(src):
            raise ValueError("请选择有效的原图文件")

        dst = self.dst_var.get().strip()
        fmt = self.fmt_var.get()
        if not dst:
            base, _ = os.path.splitext(src)
            ext = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[fmt]
            dst = base + "_已防护" + ext

        return dict(
            src=src,
            dst=dst,
            owner=owner,
            contact=_blank(self.contact_var.get()),
            license=_blank(self.license_var.get()),
            no_ai=True,
            visible_mode=VISIBLE_MODE_MAP[self.visible_var.get()],
            opacity=self.opacity_var.get(),
            font_size=_int_or_none(self.font_size_var.get()),
            font_path=_blank(self.font_path_var.get()),
            top_text=_blank(self.top_text_var.get()),
            en_text=_blank(self.en_text_var.get()),
            tile_text=_blank(self.tile_text_var.get()),
            stego_method=STEGO_MAP[self.stego_var.get()],
            adv_strength=self.adv_var.get(),
            texture_kind=TEXTURE_MAP[self.texture_var.get()],
            texture_opacity=self.texture_opacity_var.get(),
            texture_seed=_int_or_none(self.texture_seed_var.get()),
            key=_blank(self.key_var.get()),
            fmt=fmt,
            quality=self.quality_var.get(),
        )

    def _on_protect(self):
        try:
            kwargs = self._collect_protect_kwargs()
        except ValueError as exc:
            self.log(f"[防护] 参数错误：{exc}")
            return

        def work():
            return pipeline.protect(**kwargs)

        def done(result):
            self._save_config()
            self.log(f"[防护] 已输出：{result['dst']}")
            self.log("[防护] 摘要：" + json.dumps(result, ensure_ascii=False, indent=2))
            self._preview(result["dst"], self.dst_preview, "dst", max_w=620, max_h=230)
            summary = (
                f"输出文件：{result['dst']}\n"
                f"格式：{result['format']}   可见水印：{result['visible_mode']}\n"
                f"隐形水印：{result['stego_method']}（盲水印{'已' if result['blindwm_embedded'] else '未'}嵌入）\n"
                f"对抗扰动：{result['adversarial_strength']}   底纹：{result['texture_kind']}\n"
                f"原始尺寸：{result['orig_size']}   指纹：{result['pixel_sha256'][:16]}…"
            )
            if result.get("warnings"):
                summary += "\n⚠ " + "；".join(result["warnings"])
            self._set_text(self.protect_summary, summary)

        def fail(exc):
            self.log(f"[防护] 失败：{exc}")

        self._run_async(work, done, fail)

    # ------------------------------------------------------ 关键花纹区块标注
    def _open_annotator(self):
        original = self.original_var.get().strip()
        if not original or not os.path.isfile(original):
            self.log("[标注] 请先在「待比对图片」选择原图")
            return
        RegionAnnotator(self, original, on_done=self._on_regions_annotated,
                        initial_regions=self.regions)

    def _on_regions_annotated(self, regions):
        self.regions = regions
        self._save_regions_file()
        self._update_region_status()
        self.log(f"[标注] 已记录 {len(regions)} 个关键花纹区块")

    def _clear_regions(self):
        self.regions = []
        self.regions_file = None
        self._update_region_status()
        self.log("[标注] 已清空关键花纹区块")

    def _regions_file_for(self, original):
        base, _ = os.path.splitext(original)
        return base + "_关键花纹.json"

    def _save_regions_file(self):
        original = self.original_var.get().strip()
        if not original or not self.regions:
            self.regions_file = None
            return
        path = self._regions_file_for(original)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"image": os.path.basename(original), "regions": self.regions},
                          fh, ensure_ascii=False, indent=2)
            self.regions_file = path
        except Exception as exc:  # noqa: BLE001
            self.log(f"[标注] 保存失败：{exc}")

    def _load_regions_file(self, original):
        """若原图旁存在 <原图名>_关键花纹.json，则自动载入区块。"""
        path = self._regions_file_for(original)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                regions = data.get("regions") if isinstance(data, dict) else data
                if isinstance(regions, list) and regions:
                    self.regions = regions
                    self.regions_file = path
                    return True
            except Exception:
                pass
        return False

    def _update_region_status(self):
        if not self.regions:
            self.region_status.configure(text="未标注区块（可选）", text_color=("gray40", "gray70"))
        else:
            names = "、".join(r.get("name", "?") for r in self.regions)
            self.region_status.configure(text=f"已标注 {len(self.regions)} 个区块：{names}",
                                         text_color=("dodgerblue3", "#6db3ff"))

    # ------------------------------------------------------ 溯源逻辑
    def _on_trace(self):
        query = self.query_var.get().strip()
        original = self.original_var.get().strip()
        if not query or not os.path.isfile(query):
            self.log("[溯源] 请选择有效的疑似图文件")
            return
        if not original or not os.path.isfile(original):
            self.log("[溯源] 请选择有效的原图文件")
            return

        key = _blank(self.trace_key_var.get())
        min_inliers = self.min_inliers_var.get()
        min_ratio = self.min_ratio_var.get()

        # 关键花纹区块：若尚未标注，尝试自动载入原图旁的 <原图名>_关键花纹.json
        if not self.regions:
            self._load_regions_file(original)
            self._update_region_status()
        regions = self.regions or None

        qbase, _ = os.path.splitext(query)
        obase, _ = os.path.splitext(original)
        visualize = qbase + "_举证图.png"
        highlight = obase + "_高亮被盗区域.png"

        def work():
            match = pipeline.match(
                query, original, method="feature",
                min_inliers=min_inliers, min_ratio=min_ratio,
                regions=regions,
                visualize=visualize, highlight=highlight, top=1)
            phash_res = pipeline.match(query, original, method="phash", top=1)
            verify = pipeline.verify(query, key=key, original=original)
            return {"match": match, "phash": phash_res, "verify": verify,
                    "visualize": visualize, "highlight": highlight}

        def done(payload):
            self._render_trace_result(payload)

        def fail(exc):
            self.log(f"[溯源] 失败：{exc}")

        self._run_async(work, done, fail)

    def _render_trace_result(self, payload):
        match = payload["match"]
        verify = payload["verify"]
        results = match.get("results") or []

        # 输出路径提示（举证图 / 高亮图）
        self.match_path_label.configure(text="举证图：" + payload["visualize"])
        self.highlight_path_label.configure(text="高亮图：" + payload["highlight"])

        if results:
            top = results[0]
            c = top.get("color") or {}
            cons = f"，颜色一致率 {c.get('consistency'):.0%}" if c.get("consistency") is not None else ""
            self.log(f"[溯源] 判定：{top['verdict']}（内点 {top['inliers']}，内点率 {top['inlier_ratio']}{cons}）")
            if top.get("matched"):
                self._preview(payload["visualize"], self.match_preview, "match", max_w=460, max_h=150)
                self._preview(payload["highlight"], self.highlight_preview, "highlight", max_w=460, max_h=150)
            else:
                self.match_preview.configure(image=None, text="非盗图判定，未生成举证图")
                self.highlight_preview.configure(image=None, text="非盗图判定，未生成高亮图")
                self.match_path_label.configure(text="举证图：未生成（非盗图）")
                self.highlight_path_label.configure(text="高亮图：未生成（非盗图）")
        else:
            self.log("[溯源] 未找到可比对的特征结果")

        self._render_evidence(results[0] if results else None, verify, payload.get("phash"))
        self.log("[溯源] 举证图：" + payload["visualize"])
        self.log("[溯源] 高亮图：" + payload["highlight"])

    def _on_trace_panel_resize(self, event):
        """溯源结论区随窗口宽度自适应换行。"""
        w = max(event.width - 30, 120)
        if getattr(self, "verdict_label", None) is not None:
            self.verdict_label.configure(wraplength=w)
        if getattr(self, "region_label", None) is not None:
            self.region_label.configure(wraplength=w)

    def _render_evidence(self, top, verify, phash_res=None):
        """把溯源证据渲染成可视化指标（替代纯文本）。"""
        bw = verify.get("blindwm") or {}
        tamper = verify.get("tamper") or {}
        pl = verify.get("payload") or {}
        phash_dist = None
        if phash_res:
            ph_top = (phash_res.get("results") or [{}])[0]
            phash_dist = ph_top.get("distance")

        if top:
            matched = bool(top.get("matched"))
            verdict = top.get("verdict", "不相关")
            color = ("#c0392b", "#e74c3c") if matched else ("#27ae60", "#2ecc71")
            # 边界兜底：结构相同、颜色被判不同，但 pHash 距离极小 -> 疑似整体去色/调色盗图
            if (not matched and "同结构不同上色" in verdict
                    and phash_dist is not None and phash_dist <= 5):
                verdict += "（⚠ 亮度结构高度一致，疑似整体去色/调色盗图，请结合 pHash 判定）"
                color = ("#c0392b", "#e74c3c")
            self.verdict_label.configure(text=verdict, text_color=color)

            ratio = float(top.get("inlier_ratio") or 0)
            self.ratio_bar.set(min(max(ratio, 0.0), 1.0))
            self.ratio_caption.configure(text=f"内点率：{ratio:.2%}")
            color = top.get("color") or {}
            cons = color.get("consistency")
            cons_text = f"    颜色一致率 {cons:.0%}" if cons is not None else ""
            self.metrics_label.configure(
                text=f"匹配点 {top.get('matches')}    几何内点 {top.get('inliers')}{cons_text}"
            )

            cov = top.get("coverage") or {}
            dc = cov.get("db_coverage") or {}
            qc = cov.get("query_coverage") or {}
            dg = float(dc.get("grid") or 0)
            qg = float(qc.get("grid") or 0)
            self.db_cov_caption.configure(text=f"原图覆盖率 {dg:.0%}")
            self.db_cov_bar.set(min(max(dg, 0.0), 1.0))
            self.query_cov_caption.configure(text=f"疑似图覆盖率 {qg:.0%}")
            self.query_cov_bar.set(min(max(qg, 0.0), 1.0))

            noise = top.get("noise") or {}
            qn = noise.get("query_noise")
            dn = noise.get("db_noise")
            if qn is not None and dn is not None:
                self.noise_label.configure(text=f"噪声水平：疑似图 {qn}   vs   原图 {dn}")
            else:
                self.noise_label.configure(text="噪声水平：--")

            region_evidence = top.get("region_evidence")
            if region_evidence and region_evidence.get("total_regions"):
                total = region_evidence.get("total_regions")
                hit = region_evidence.get("matched_regions")
                rate = region_evidence.get("match_rate", 0)
                items = region_evidence.get("regions") or []
                marks = "  ".join(
                    ("✓" if b.get("matched") else "✗") + str(b.get("name", ""))
                    for b in items
                )
                strong = bool(top.get("region_matched"))
                self.region_label.configure(
                    text=f"关键花纹命中 {hit}/{total}（{rate:.0%}）：{marks}",
                    text_color=("#c0392b", "#e74c3c") if strong else ("#b9770e", "#f1c40f"),
                )
            else:
                self.region_label.configure(text="关键花纹：未标注", text_color=("gray40", "gray70"))
        else:
            self.verdict_label.configure(text="未找到可比对结果", text_color=("gray40", "gray70"))
            self.ratio_bar.set(0)
            self.ratio_caption.configure(text="内点率：--")
            self.metrics_label.configure(text="匹配点 --   几何内点 --")
            self.db_cov_caption.configure(text="原图覆盖率 --")
            self.db_cov_bar.set(0)
            self.query_cov_caption.configure(text="疑似图覆盖率 --")
            self.query_cov_bar.set(0)
            self.noise_label.configure(text="噪声水平：--")
            self.region_label.configure(text="关键花纹：未标注", text_color=("gray40", "gray70"))

        parts = []
        parts.append("盲水印 " + ("✓已检出" if bw.get("found") else "✗未检出"))
        if pl:
            parts.append("作者 " + str(pl.get("owner")))
            parts.append("禁止AI训练 " + ("✓" if pl.get("no_ai_training") else "✗"))
        if "pixel_hash_match" in tamper:
            parts.append("像素指纹 " + ("✓一致" if tamper.get("pixel_hash_match") else "✗不一致"))
        if tamper.get("dhash_distance") is not None:
            parts.append(f"dHash距离 {tamper.get('dhash_distance')}")
        if phash_dist is not None:
            parts.append(f"pHash距离 {phash_dist}")
        self.verify_label.configure(text="  |  ".join(parts) if parts else "隐形水印：无数据")


def main():
    app = AegisBrushApp()
    app.mainloop()


if __name__ == "__main__":
    main()
