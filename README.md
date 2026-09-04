# AegisBrush 🛡️

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](https://github.com/zhy201810576/AegisBrush)

给 OC（原创角色 / 原创作品）图片打上**防盗用 + 反 AI 训练**水印的 Python 工具。

## ⚠️ 先说实话

没有任何像素级方案能 100% 阻止盗用或 AI 训练——截图、重拍、重绘都能绕过。
AegisBrush 的价值在于**分层防护 + 溯源取证**：

| 层级 | 手段 | 作用 |
| --- | --- | --- |
| 1 | 可见水印（文字平铺 / 单点 / Logo） | 直接阻吓盗用，标明归属 |
| 2 | 隐形水印（频域盲水印 DWT/DCT，抗压缩/缩放） | 肉眼不可见，可事后提取作为版权证据 |
| 3 | 元数据（EXIF / XMP / PNG 文本块） | 写入作者、版权、**禁止 AI 训练**标记 |
| 4 | 对抗扰动（高频噪声） | 干扰特征提取/训练信号（Nightshade/Glaze 的简化启发式） |

其中「对抗扰动」是启发式实现，**不等于**学术上的 Nightshade/Glaze，也不能阻止已部署模型识别。

### 必须清楚的边界

- **隐形水印分两种**：默认的频域盲水印（DWT/DCT）抗 JPEG 压缩、缩放、轻微裁剪，但对「裁剪换景别 + 贴图加字」依然失效；LSB 模式仅对「无损搬运」可靠。
- **元数据可能被处理工具剥除**：很多图片编辑器 / 平台在重新保存时会丢弃 EXIF、XMP、PNG 文本块。
- **真正对「改图」鲁棒的是内容指纹比对（`match`）**：`dhash`/`phash` 对颜色滤镜、缩放、轻微编辑有效；「裁剪换景别 + 贴图加字」这类改构图操作则由 `feature` 模式（ORB + RANSAC 局部特征匹配）覆盖，输出几何内点、内点率、匹配区域覆盖率与内点颜色一致率作为取证证据，并能区分「同线稿模板但不同上色」的图（不计盗用）。

## 安装

```bash
pip install -e .
```

## 图形界面（GUI）

内置 CustomTkinter 桌面界面，无需命令行即可完成防护与溯源：

```bash
# 方式一：双击项目根目录的 启动GUI.py
# 方式二：命令行启动
aegisbrush-gui
# 或
python -m aegisbrush.gui
```

界面提供：

- **作品防护**：选择原图 → 可视化配置「版权信息 / 可见水印套件 / 隐形水印 / 对抗扰动 / 底纹噪声」→ 一键防护 → 原图与成图并排对比 + 处理摘要。
- **盗图溯源**：选择疑似图与原图 → 一键溯源（ORB 特征匹配 + 隐形水印验证）→ 输出证据链（匹配点 / 几何内点 / 内点率 / 颜色一致率 / 覆盖率 / 噪声水平）+ 举证图 + 被盗区域高亮图。
- **关键花纹区块**：在原图上框选头部 / 胸 / 手臂 / 大腿等独特花纹，溯源时逐块做「图案 + 颜色」加强比较，命中越多盗图证据越实锤。
- **外观**：浅色 / 深色 / 跟随系统，主题色切换。

> GUI 依赖 `customtkinter`，`pip install -e .` 时已作为依赖一并安装。

## 快速上手

```bash
# 完整防护：可见水印 + 隐形水印 + 元数据 + 对抗扰动
aegisbrush protect -i 原图.png -o 已防护.png \
  --owner "你的画师名" --contact "@你的社交账号" \
  --text "©你的画师名 请勿盗用" --adv 30

# 只做隐形水印 + 元数据（画面保持干净）
aegisbrush protect -i 原图.png -o 已防护.png --owner "画师名" --visible none

# 校验图片（读取元数据 + 隐写载荷 + 内容指纹）
aegisbrush verify -i 已防护.png

# 提取完整隐写载荷
aegisbrush decode -i 已防护.png --key "你的密钥"

# 溯源：找出疑似盗图最像图库里的哪张原图（对滤镜/缩放/轻微编辑有效）
aegisbrush match -i 疑似盗图.png -d 原图库目录
```

## 命令参考

### protect

```
aegisbrush protect -i 输入 -o 输出 --owner 作者 [选项]
  --contact TEXT        联系方式
  --license TEXT        授权说明
  --text TEXT           可见水印文字（默认取 owner）
  --visible MODE        none / tile / single / corner / suite（suite = 多层防盗水印套件）
  --opacity FLOAT       可见水印透明度 0~1（默认 0.35）
  --font-size INT       可见水印字号
  --font-path PATH      自定义水印字体文件
  --top-text TEXT       suite 顶部声明文字
  --en-text TEXT        suite 英文声明文字
  --tile-text TEXT      suite 底层斜向平铺文字
  --logo PATH           Logo 图片
  --logo-position POS   top-left / top-right / bottom-left / bottom-right
  --stego METHOD        blindwm（默认，频域）/ lsb / both / none
  --no-stego            关闭隐形水印（等价 --stego none）
  --adv FLOAT           对抗扰动强度 0~100（默认 0 关闭）
  --texture TYPE        底纹噪声 none / noise / hatch / dots / grid（默认 none）
  --texture-opacity F   底纹噪声强度 0~1（默认 0.1）
  --texture-seed INT    底纹噪声随机种子
  --key TEXT            隐写 / HMAC 密钥（推荐设置）
  --seed INT            对抗噪声随机种子
  --format FMT          PNG / JPEG / WEBP（默认沿用原图）
  --quality INT         JPEG 质量（默认 95）
  --allow-ai            不标记禁止 AI 训练（默认会标记）
```

### match（溯源）

```
aegisbrush match -i 疑似盗图 -d 原图库目录 [选项]
  --method MODE         dhash（滤镜/缩放）/ phash（抗噪声）/ feature（裁剪/旋转/改构图）
  --threshold INT       dHash 汉明距离阈值，默认 10（越小越严）
  --min-inliers INT     feature 模式判同源的 RANSAC 内点下限，默认 15
  --min-ratio FLOAT      feature 模式判同源的内点率下限，默认 0.3
  --min-color-consistency FLOAT  feature 模式判颜色/花纹一致的内点颜色一致率下限，默认 0.70
  --max-color-distance FLOAT     feature 模式判颜色/花纹一致的 Lab 距离中位数上限，默认 25
  --regions PATH           关键花纹区块标注 JSON（feature 模式逐块加强比较）
  --min-region-match-rate FLOAT  关键花纹区块命中率下限，默认 0.5
  --visualize PATH       举证图输出路径（feature 模式绘制内点连线图）
  --highlight PATH        高亮图输出路径（feature 模式在原图上标出被盗区域）
  --top INT               输出最相似的条数，默认 5
```

- `dhash`：全局差异哈希，适合颜色滤镜、缩放、轻微编辑。
- `phash`：DCT 感知哈希，额外抗噪声、抗压缩、抗亮度。
- `feature`：ORB + RANSAC 几何验证（借鉴 duplicate_img_finder 等项目的理念），
  输出证据链（匹配点 / 几何内点 / 内点率 / 内点颜色一致率）+ 匹配区域覆盖率。
  判定 = 结构匹配（内点/内点率）且 颜色/花纹匹配（内点颜色一致率与 Lab 距离）：
    · 结构与颜色都匹配 → 「同源（盗图嫌疑）」
    · 结构匹配但颜色/花纹不同 → 「同结构不同上色」（同一线稿模板但不同上色，不计盗用）
    · 结构不匹配 → 「不相关」
  能溯源「裁剪换景别 + 贴图加字」这类 dHash 无法覆盖的改构图盗图，
  同时避免把「同线稿模板不同上色」的图误判为盗用。
  配合 `--visualize` 可生成内点连线举证图。
- `feature` + `--regions`：在以上判定之外，对用户标注的「关键花纹区块」逐块做
  「局部图案（ORB）+ 局部颜色（分位 Lab）」加强比较。区块命中率 >= 0.5 记为
  region_matched=True，作为盗图实锤的强证据——连标注的花纹都逐块对得上才算盗图。
  区块标注 JSON 格式：{"image": "原图.png", "regions": [{"name": "头部花纹",
  "x": 100, "y": 50, "w": 80, "h": 80}, ...]}（坐标相对原图像素）。

## 打包为 Windows exe

```bash
pip install pyinstaller
pyinstaller --clean AegisBrush.spec
```

- 产物在 `dist/AegisBrush/`，是 **onedir** 目录：**整个文件夹**要一起分发，不能只发 `AegisBrush.exe`（它依赖同目录的 `_internal/`）。
- 已自动打包：customtkinter 主题/字体、应用图标、Tcl/Tk 运行库（兼容 Anaconda 环境）。
- 分发时把 `dist/AegisBrush/` 整个压缩成 zip；`build/` 是中间产物，可删除。
- 重新打包用 `gui_launcher.py` 作为入口，`AegisBrush.spec` 保存了全部配置。

## 重要提示

- **隐形水印默认用频域盲水印（DWT/DCT）**：抗 JPEG 有损压缩；对「整体缩放」需在 `verify` 时
  用 `--original 原图.png`（自动读原图尺寸）或 `--orig-size 宽x高` 还原尺寸后才能提取。
  改构图裁剪仍会失效。需要携带完整载荷时用 `--stego lsb` 或 `--stego both`。
- **密钥**：设置 `--key` 后，隐写位置置乱与 HMAC 签名都会绑定该密钥，校验时需提供同一密钥；
  不设置则隐写位置使用固定种子（可被有心人逆向），仅适合防君子。
- **`verify` 的载荷来源**：优先读隐写，失败时回退读元数据（EXIF / PNG Comment）。
  若两者都被处理工具剥除，则无法报告所有权——此时请改用 `match` 做内容指纹溯源。
- **`match` 是「比对」而非「从图里提取」**：它依赖你手里存有原图（或原图指纹库），
  拿疑似盗图去比对。`dhash` 覆盖滤镜/缩放/轻微编辑；`feature`（ORB 局部特征）
  覆盖裁剪/旋转/改构图。

## 项目结构

```
aegisbrush/
├── gui.py          CustomTkinter 图形界面
├── cli.py          命令行入口
├── pipeline.py     protect / verify 组合流程
├── payload.py      载荷构建/校验 + 内容指纹（dHash）
├── visible.py      可见水印
├── stego.py        LSB 隐形水印
├── blindwm.py      频域盲水印（DWT/DCT，基于 blind_watermark）
├── featurematch.py ORB 局部特征匹配（裁剪/旋转/改构图溯源）
├── metadata.py     EXIF / XMP / PNG 元数据
├── adversarial.py  对抗扰动
├── texture.py      底纹噪声（noise/hatch/dots/grid）
├── fonts.py        中文字体定位
└── assets/          GUI 图标（icon.png / icon.ico，RunningHub 生成）
```

## License

[MIT](./LICENSE) © 2026 zhy201810576
