# AegisBrush 用 Inno Setup 封装安装包经验

## 目标
把 PyInstaller 打包产物（`dist/AegisBrush/`，含 `AegisBrush.exe` 与 `_internal/`）封装为单个 Windows 安装程序，带简体中文向导、开始菜单/桌面快捷方式与卸载入口。

## 环境
- Inno Setup 6（编译器 `D:\Inno Setup 6\ISCC.exe`，自带简体中文语言文件 `Languages\ChineseSimplified.isl`）
- 待打包目录：`E:\Python-Project\AegisBrush\dist\AegisBrush\`（PyInstaller onedir 结构，含 numpy / cv2 / PIL / customtkinter / tcl8 / tk8.6 / _tcl_data / tzdata 等大量文件）

## 流程
1. 探测产物结构：`dist/AegisBrush/` 下有 `AegisBrush.exe` + `_internal/`。
2. 读 exe 的 PE 头判断架构：`Machine` 字段 `0x8664` = AMD64，据此写 64 位相关指令。
3. 生成 `.iss`，`Source` 用绝对路径，避免受脚本所在目录影响。
4. 命令行编译：`"D:\Inno Setup 6\ISCC.exe" installer\AegisBrush.iss`。
5. 产物 `dist\AegisBrush-Setup-1.0.0.exe`（约 55 MB，lzma2/max 压缩）。

## 关键 .iss 配置（精简）
```ini
#define MyAppName "AegisBrush"
#define MyAppVersion "1.0.0"
#define MyAppExeName "AegisBrush.exe"

[Setup]
AppId={{B7E8F3A9-6C2D-4D5E-9B1A-4F7C8E2D9A1B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
OutputDir=E:\Python-Project\AegisBrush\dist
OutputBaseFilename=AegisBrush-Setup-{#MyAppVersion}
SetupIconFile=E:\Python-Project\AegisBrush\aegisbrush\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "E:\Python-Project\AegisBrush\dist\AegisBrush\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
```

## 可复用要点 / 坑
- **AppId 固定 GUID**：`AppId={{B7E8F3A9-...}` 保证后续升级识别稳定，改名不破坏升级。
- **默认目录用常量**：`{autopf}` 而非硬编码 `C:\Program Files`。
- **管理员 + 降级对话框**：`PrivilegesRequired=admin` 配 `PrivilegesRequiredOverridesAllowed=dialog`，非管理员环境仍可继续安装。
- **多语言**：`[Languages]` 第一项为默认语言；简体中文文件名是 `ChineseSimplified.isl`，用 `compiler:` 前缀指向编译器自带语言目录。
- **[Files] Source 用绝对路径**：相对路径是相对脚本所在目录，绝对路径最稳；打包整个目录用 `Flags: recursesubdirs createallsubdirs ignoreversion`。
- **[Run] 安装后启动**：`Flags: nowait postinstall skipifsilent`；显示名里的 `&` 要转义为 `&&`（`{#StringChange(MyAppName, '&', '&&')}`）。
- **编译日志海量**：`_internal` 有数千个小文件，日志可能被截断，判断成功看末尾 `Successful compile (...)` 与 `Resulting Setup program filename is:`。
- **图标复用**：`SetupIconFile`、`UninstallDisplayIcon={app}\AegisBrush.exe`、快捷方式统一用同一 `icon.ico`。
- **DSH 环境**：bash 工具须在 `run_code` 程序内通过 `tools.bash(...)` 调用（直接调 bash 会报 unknown tool）；Git Bash 下访问 Windows 路径可用 `/d/...`、`/e/...` 形式。
- **架构检测**：PyInstaller exe 的 PE 头 `Machine` 字段 `64 86`（小端 `0x8664`）即 AMD64。
