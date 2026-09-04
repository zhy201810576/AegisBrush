# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir + windowed + customtkinter 资源 + 图标 + Tcl/Tk 依赖。"""
import os
import sys
import customtkinter

project_root = SPECPATH
ctk_root = os.path.dirname(customtkinter.__file__)

# Anaconda 环境下 tkinter 的 DLL 与脚本库位于 base 环境的 Library 下，需显式收录
base_prefix = getattr(sys, 'base_prefix', sys.prefix)
lib_bin = os.path.join(base_prefix, 'Library', 'bin')
lib_dir = os.path.join(base_prefix, 'Library', 'lib')

tcl_dlls = []
for name in ('tcl86t.dll', 'tk86t.dll', 'libexpat.dll', 'ffi.dll', 'liblzma.dll'):
    p = os.path.join(lib_bin, name)
    if os.path.isfile(p):
        tcl_dlls.append((p, '.'))

tcl_datas = []
for name in ('tcl8.6', 'tk8.6'):
    p = os.path.join(lib_dir, name)
    if os.path.isdir(p):
        tcl_datas.append((p, name))

a = Analysis(
    [os.path.join(project_root, 'gui_launcher.py')],
    pathex=[project_root],
    binaries=tcl_dlls,
    datas=[
        (os.path.join(ctk_root, 'assets', 'themes'), 'customtkinter/assets/themes'),
        (os.path.join(ctk_root, 'assets', 'fonts'), 'customtkinter/assets/fonts'),
        (os.path.join(project_root, 'aegisbrush', 'assets'), 'aegisbrush/assets'),
    ] + tcl_datas,
    hiddenimports=['pywt', 'cv2', 'piexif'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'matplotlib', 'IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AegisBrush',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, 'aegisbrush', 'assets', 'icon.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AegisBrush',
)
