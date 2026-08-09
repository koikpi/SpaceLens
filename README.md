# SpaceLens

SpaceLens 是一款完全在本机运行的磁盘空间分析器，使用交互式矩形树图、列表和容量条展示目录占用，帮助定位大文件、重复文件和可清理空间。

## 特性

- 扫描本地磁盘、文件夹、外置磁盘和已挂载的网络共享
- 矩形树图、层级列表、容量条等多种视图
- 搜索文件并查看最大的文件
- 支持快速比较、SHA-256 和逐字节重复文件检测
- 保存和重新打开本地扫描快照
- 在 Windows 资源管理器或 macOS Finder 中定位文件
- 只使用 Python 标准库，无需安装第三方 Python 依赖
- 提供 Windows x64、Windows ARM64 和 macOS ARM64 独立发行包

## 隐私与安全

SpaceLens 的本地服务只监听 `127.0.0.1`，不会对局域网或互联网开放。扫描得到的文件名、路径、大小、索引和历史快照只保存在本机的 `saved_scans/` 目录中。

独立发行版的数据保存位置为：

- Windows：`%LOCALAPPDATA%\SpaceLens\saved_scans`
- macOS：`~/Library/Application Support/SpaceLens/saved_scans`

`saved_scans/`、环境变量文件、构建缓存和发布压缩包均已加入 `.gitignore`，不会被提交到 Git 仓库。SpaceLens 不会主动上传扫描结果或硬盘信息。

> 提醒：扫描快照可能包含真实文件名和完整路径。分享日志、截图或程序目录前，请先检查并移除 `saved_scans/`。

## Windows 使用方法

要求：Windows 10/11、Python 3.10 或更高版本。

1. 下载源码并解压。
2. 双击 `本地启动.cmd`。
3. 浏览器会自动打开 <http://127.0.0.1:8765>。
4. 关闭启动窗口即可停止 SpaceLens。

也可以在 PowerShell 中运行：

```powershell
python local_server.py
```

从 GitHub Actions 下载的独立版无需安装 Python，解压后双击 `启动 SpaceLens.cmd`。请根据设备选择 `Windows-x64` 或 `Windows-ARM64`。

## macOS 使用方法

Apple Silicon Mac 推荐从 GitHub Releases 直接下载 `SpaceLens-macOS-ARM64.dmg`。双击 DMG，将 `SpaceLens.app` 拖入“应用程序”后即可运行；DMG 安装版不需要安装 Python。

源码版要求 macOS 12 或更高版本、Python 3.10 或更高版本。

首次使用时，在终端中进入项目目录并运行：

```bash
chmod +x "启动 SpaceLens.command"
./启动\ SpaceLens.command
```

更详细的说明见 [MACOS.md](MACOS.md)。

当前免费构建采用临时签名，没有经过 Apple 公证。首次启动若被 macOS 拦截，请按住 Control 点击 SpaceLens，选择“打开”。详细说明见 [MACOS.md](MACOS.md)。

## 免费跨平台测试与打包

仓库包含 `.github/workflows/build-cross-platform.yml`，只能在 GitHub Actions 页面手动触发，不会在每次提交时消耗额度。一次运行会：

1. 在 Windows x64、Windows ARM64 和 macOS ARM64 上运行同一组测试。
2. 使用 PyInstaller 在目标系统上原生打包。
3. 启动打包后的程序并请求本地 HTTP 服务。
4. 构建 Windows ZIP 和 macOS DMG，并发布到 GitHub Releases 提供直接下载。

详细操作见 [CROSS_PLATFORM_TESTING.md](CROSS_PLATFORM_TESTING.md)。

## 从源码启动

```bash
git clone https://github.com/你的用户名/SpaceLens.git
cd SpaceLens
python local_server.py
```

本地服务启动后会自动打开默认浏览器。程序默认使用端口 `8765`。

## Web 界面开发

仓库也包含 SpaceLens 的 React/Web 界面。开发环境要求 Node.js 22.13 或更高版本：

```bash
npm install
npm run dev
```

构建和测试：

```bash
npm run lint
npm test
```

## 项目结构

- `local_server.py`：跨平台本地扫描服务
- `local/index.html`：本地版浏览器界面
- `app/`：React/Web 界面
- `tests/`：Web 界面与本地服务测试
- `SpaceLens.spec`：跨平台 PyInstaller 打包配置
- `.github/workflows/build-cross-platform.yml`：手动跨平台 CI
- `本地启动.cmd`：Windows 启动脚本
- `启动 SpaceLens.command`：macOS 启动脚本

## 开源许可

本项目采用 [MIT License](LICENSE)。
