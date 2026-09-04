# AegisBrush GitHub Release 安装包发布经验

## 目标
把 Inno Setup 编译好的 Windows 安装包（`AegisBrush-Setup-1.0.0.exe`）发布到 GitHub Releases，供用户直接下载双击安装，无需预装 Python。

## 发布结果
- Release 页面：https://github.com/zhy201810576/AegisBrush/releases/tag/v1.0.0
- 安装包直链：https://github.com/zhy201810576/AegisBrush/releases/download/v1.0.0/AegisBrush-Setup-1.0.0.exe
- Tag：`v1.0.0`
- 安装包大小：54.72 MB
- SHA256：`B931DB9FF58A51986DFFD113775EA9B90F993823FEDD6FA827701C68EE841F49`

## 前置检查
1. **确认安装包就绪且最新**：对比 `dist\AegisBrush-Setup-1.0.0.exe` 的 `LastWriteTime` 是否晚于源码最后修改时间（`Get-ChildItem aegisbrush\*.py | Sort LastWriteTime -Descending`），避免发布过期产物。
2. **计算 SHA256**：`Get-FileHash "dist\AegisBrush-Setup-1.0.0.exe" -Algorithm SHA256`，写入 release notes 供用户校验完整性。

## 标准发布流程
1. **打 tag 并推送**：
   ```powershell
   git tag v1.0.0
   git -c http.proxy=http://127.0.0.1:10808 -c https.proxy=http://127.0.0.1:10808 push origin v1.0.0
   ```
2. **写 release notes**：用 `--notes-file` 传中文多行文件，避免 PowerShell 反引号/引号转义踩坑。
3. **创建 release 并上传安装包**：
   ```powershell
   $env:HTTPS_PROXY='http://127.0.0.1:10808'
   gh release create v1.0.0 "dist\AegisBrush-Setup-1.0.0.exe" `
     --repo owner/repo --title "AegisBrush v1.0.0" --notes-file ".gh-release-notes.md"
   ```
4. **验证**：`gh release view v1.0.0 --json name,tagName,isDraft,isPrerelease,assets`

## release notes 编排
- **功能亮点**（体验语言，非技术语言）
- **安装步骤**（1/2/3 编号）
- **系统要求**（Windows 10/11 x64，无需预装 Python）
- **校验**（版本、文件大小、SHA256）
- **源码安装提示**（链接回 README）

## README 下载入口编排
在「安装」小节前插入「下载安装包（Windows，推荐）」，把安装包直链 + Releases 页面链接放最前，源码安装降为备选——符合「README 面向使用者」原则：普通用户最需要的是「下载 → 双击安装」，而非 `pip install -e .`。

## 可复用要点 / 坑
1. **gh release 必须走代理**：设置 `HTTPS_PROXY=http://127.0.0.1:10808`，否则直连 GitHub 上传 50MB+ 文件不稳定。
2. **danger-full-access**：`gh release create` 上传文件需网络 + 凭据，workspace-write 沙箱受限，需升级权限。
3. **`--notes-file` 优于 `--notes`**：中文多行说明用文件传入，避免 shell 转义问题。
4. **SHA256 双校验**：本地 `Get-FileHash` 与 GitHub asset 的 `digest` 字段（`sha256:...`）一致，确认上传无损。
5. **tag 与 release 分离**：先 `git push` tag，再 `gh release create` 引用已存在 tag；gh 会自动计算 asset 的 digest。
6. **dubious ownership**：目录属主为 Administrators 时，git/gh 前用环境变量注入 `safe.directory` 例外（`GIT_CONFIG_COUNT/KEY/VALUE` 方式），不写全局 `~/.gitconfig`（会被沙箱拒绝）。
7. **asset 状态校验**：验证时看 `assets[].state == "uploaded"`、`isDraft=false`、`isPrerelease=false` 才是正式发布。
8. **临时文件清理**：release notes 临时文件（如 `.gh-release-notes.md`）用完删除，避免污染工作区。
