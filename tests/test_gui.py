# -*- coding: utf-8 -*-
"""GUI 冒烟测试：验证 CustomTkinter 主窗口可正常构建与销毁。

无显示环境（CI / 服务器）下自动跳过。
"""

import pytest


def test_gui_builds_and_destroys():
    pytest.importorskip("customtkinter")
    try:
        from aegisbrush.gui import AegisBrushApp

        app = AegisBrushApp()
        app.withdraw()
        app.update_idletasks()
        app.update()
        app.destroy()
    except Exception as exc:  # noqa: BLE001
        if "TclError" in type(exc).__name__ or "no display" in str(exc).lower():
            pytest.skip(f"无显示环境，跳过 GUI 测试：{exc}")
        raise


def test_region_annotator_builds():
    """关键花纹区块标注窗口应能正常构建、加载图片并销毁。"""
    pytest.importorskip("customtkinter")
    import os
    import tempfile

    from PIL import Image

    try:
        from aegisbrush.gui import AegisBrushApp, RegionAnnotator

        with tempfile.TemporaryDirectory() as d:
            img = os.path.join(d, "src.png")
            Image.new("RGB", (200, 150), (100, 150, 200)).save(img)

            app = AegisBrushApp()
            app.withdraw()
            ann = RegionAnnotator(
                app, img, on_done=lambda regions: None,
                initial_regions=[{"name": "头部花纹", "x": 10, "y": 20, "w": 50, "h": 60}],
            )
            ann.update_idletasks()
            ann.update()
            # 回填验证：上一次的标注应载入区块列表、表格与画布框
            assert len(ann.regions) == 1
            assert len(ann.table.get_children()) == 1
            assert len(ann._box_ids) == 1
            ann.destroy()
            app.destroy()
    except Exception as exc:  # noqa: BLE001
        if "TclError" in type(exc).__name__ or "no display" in str(exc).lower():
            pytest.skip(f"无显示环境，跳过 GUI 测试：{exc}")
        raise


def test_region_annotator_cancel_no_add():
    """命名对话框点击「取消」时，不应添加区块。"""
    pytest.importorskip("customtkinter")
    import os
    import tempfile

    import customtkinter as ctk
    from PIL import Image

    try:
        from aegisbrush.gui import AegisBrushApp, RegionAnnotator

        class _CancelDialog:
            def __init__(self, *a, **k):
                pass

            def get_input(self):
                return None  # 模拟点击「取消」

        class _FakeEvent:
            def __init__(self, x, y):
                self.x, self.y = x, y

        with tempfile.TemporaryDirectory() as d:
            img = os.path.join(d, "src.png")
            Image.new("RGB", (200, 150), (100, 150, 200)).save(img)

            app = AegisBrushApp()
            app.withdraw()
            ann = RegionAnnotator(app, img, on_done=lambda regions: None)
            ann.update_idletasks()
            ann.update()

            ann._start = (10, 10)
            ann._scale = 1.0
            ann._offset = [0, 0]
            orig = ctk.CTkInputDialog
            ctk.CTkInputDialog = _CancelDialog
            try:
                ann._on_release(_FakeEvent(60, 50))
            finally:
                ctk.CTkInputDialog = orig
            assert len(ann.regions) == 0

            ann.destroy()
            app.destroy()
    except Exception as exc:  # noqa: BLE001
        if "TclError" in type(exc).__name__ or "no display" in str(exc).lower():
            pytest.skip(f"无显示环境，跳过 GUI 测试：{exc}")
        raise
