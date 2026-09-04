# AegisBrush CustomTkinter GUI 开发与 PyInstaller 打包经验

## 概述

用 CustomTkinter 给 Python 图像处理工具（AegisBrush）做桌面 GUI，并打包成 Windows exe 的完整经验。涵盖布局坑、灯箱图片查看器、打包 DLL 依赖、图标透明处理、AI 生图集成等可复用要点。

## 一、CustomTkinter 布局与交互

### 1.1 分组标题与控件行号冲突（高频坑）
自定义 _section() 返回带标题的 Frame，标题放在 row=0。若调用方控件也从 row=0 开始 grid，标题与第一行控件会重叠（视觉上文字粘连、错乱）。
修复：标题独占 row 0，控件统一从 row=1（若还有说明行则 row=2）开始。

### 1.2 统一滑块组件
透明度/强度/阈值类参数统一封装为：标签 | 滑块(weight=1) | 数值 | 重置按钮。标签要紧贴滑块（不要中间隔数值标签，否则标签离滑块太远）。返回 (slider, value_label, reset_btn) 以便联动禁用（如格式非 JPEG 时禁用质量滑块）。

### 1.3 数字输入校验
CTkEntry 限制纯数字：vcmd = (self.register(self._validate_int), "%P") + validate="key"，_validate_int 返回 P == "" or P.isdigit()。

### 1.4 系统字体下拉 + 自定义文件
维护「字体名 -> 文件路径」映射（Windows 常见中文字体 -> C:/Windows/Fonts/xxx.ttc），按存在性动态构建 OptionMenu 选项 +「默认」+「自定义字体文件…」；选自定义时 askopenfilename 并把 OptionMenu set(os.path.basename(path))（CTkOptionMenu.set 可设任意值，不必在 values 里）。

### 1.5 配置持久化
版权信息（作者/联系/授权/密钥）保存到 ~/.aegisbrush/config.json，启动时加载作为默认值，防护成功后保存——实现"记住上次输入"的人性化默认值。

### 1.6 悬停说明 Tooltip
CustomTkinter 无内置 tooltip：用 tk.Toplevel(overrideredirect=True) + 黄色 tk.Label 实现，绑定 <Enter>/<Leave>，延迟显示；需持有 Tooltip 对象引用防 GC。

### 1.7 说明文字
每个分组标题下加灰色小字说明（wraplength 控制换行），关键术语用 tooltip——满足"专业术语要有用户能理解的说明"。

## 二、灯箱 / 图片查看器（缩放 + 平移）

用 tk.Canvas + ImageTk.PhotoImage（不是 CTkLabel）实现：

- 滚轮缩放：<MouseWheel>（Windows）/ <Button-4/5>（Linux），以鼠标位置为锚点：offset = mouse - (mouse - offset) * (new_scale / old_scale)。
- Ctrl+左键拖动平移：event.state & 0x0004 判断 Ctrl，记录按下点与偏移，B1-Motion 更新 canvas.coords(image_id, ...)。
- 内存保护：缩放上限不能固定倍数，要按原图尺寸动态限制最大渲染边长（如 4800px），否则 3300px 图放大 12 倍变成 3.9 万像素，报 TclError: not enough free memory for image buffer。
- CTkToplevel.geometry("") 不接受空串（内部 scaling 解析 "WxH" 出错）：改用 winfo_reqwidth()/reqheight() 计算窗口尺寸并居中。

## 三、PyInstaller 打包 CustomTkinter

- 必须 onedir + windowed（不能 onefile：customtkinter 含 .json 主题 + .otf 字体数据文件，onefile 解包会缺）。
- spec datas 收录：customtkinter/assets/themes、customtkinter/assets/fonts、应用自己的 assets/。
- Anaconda/conda venv 陷阱：tkinter 从 base 环境继承，但 tcl86t.dll / tk86t.dll / libexpat.dll / ffi.dll / liblzma.dll 在 base/Library/bin，tcl8.6/tk8.6 脚本库在 base/Library/lib，PyInstaller 默认找不到 -> 报 "Library not found"。修复：spec binaries 显式加这些 DLL（目标 "."），datas 加 tcl8.6/tk8.6；base 路径用 sys.base_prefix 获取。
- 入口脚本用英文名（中文名脚本打包有编码坑）。
- 打包后启动测试：subprocess.Popen([exe]) + time.sleep(8) + poll() 为 None 即启动成功（windowed 无控制台，崩溃会立即退出）。

## 四、图标透明 + 多尺寸 ico

- AI 生图（RunningHub/文生图）常输出 RGB 无 alpha，圆角方形外的背景是不透明黑色 -> Windows 任务栏黑底。先检查 img.mode 和四角像素。
- 抠透明：numpy arr[(r<30)&(g<30)&(b<30), 3] = 0，再对深色过渡像素按亮度羽化 alpha，消除黑边。
- 高质量多尺寸 ico：LANCZOS 逐尺寸缩放；32px 以下清杂边（alpha<128 设 0），因为小尺寸下圆角无意义、且 LANCZOS 缩放在角落产生半透明杂边。小尺寸（16/24px）表现为纯色方形填满是正确的小图标做法。
- Pillow ico 保存关键坑：im.save("x.ico", append_images=[...]) 时主图必须是最大帧。源码里 if size[0] > width or size[1] > height: continue（width/height 取主图尺寸），主图太小会把大于它的尺寸全部跳过。正确：最大帧.save(ico, append_images=其余帧, sizes=全部尺寸列表)，每个尺寸匹配到对应帧（直接用、不再缩放），可实现"每尺寸自定义内容"。

## 五、RunningHub MCP 生图

- 串行调用：RunningHub 所有接口（提交/查询/上传）只能串行，不能并发，否则限流。
- 避免超时：专用工具默认 waitForResult=true 会阻塞到超时（生图排队久）。传 waitForResult=false 先拿 taskId，再用 runninghub_query_task({taskId}) 轮询（间隔 15s），状态 RUNNING -> SUCCESS 后取 results[0].url。
- 结果 URL 仅 24 小时有效，需及时下载到本地。

## 六、DSH/Windows 环境操作坑

- edit 工具 Windows 偶发 ReplaceFileW EIO (Win32 1175)：重试，或改用 Python 脚本读改写文件绕过。
- edit 报 "file changed since it was read"：同一 run_code 内先 read 再 edit；每次 edit 前重新 read 目标区域。
- Python 脚本 print 中文/特殊符号到 GBK 控制台报 UnicodeEncodeError：命令前缀 PYTHONIOENCODING=utf-8。
- 已删除文件用同名路径 write 会报 "file no longer exists"：换新文件名。
