# SpaceLens for macOS

SpaceLens 是完全在本机运行的磁盘空间分析器。扫描结果、文件索引和历史快照均保存在当前程序目录下的 `saved_scans` 文件夹中，不会上传。

## DMG 安装版（推荐）

Apple Silicon Mac 用户从 GitHub Releases 下载 `SpaceLens-macOS-ARM64.dmg`：

1. 双击打开 DMG。
2. 把 `SpaceLens.app` 拖到“Applications/应用程序”。
3. 在“应用程序”中双击 SpaceLens。

DMG 安装版不需要安装 Python。当前免费构建采用临时签名，没有经过 Apple 公证；首次启动如果被系统拦截，请按住 Control 点击 SpaceLens，选择“打开”，再确认一次。正式消除该提示需要 Apple Developer ID 签名和公证。

## 源码版系统要求

- macOS 12 Monterey 或更高版本
- Python 3.10 或更高版本
- Safari、Chrome 或其他现代浏览器

程序只使用 Python 标准库，不需要安装第三方依赖。

## 源码版首次启动

1. 下载并解压整个 `SpaceLens` 项目文件夹，不要只复制启动脚本。
2. 打开“终端”，输入 `chmod +x `（末尾保留一个空格）。
3. 把 `启动 SpaceLens.command` 拖进终端窗口，按回车。
4. 双击 `启动 SpaceLens.command`。

SpaceLens 会启动本地服务，并自动在默认浏览器中打开 `http://127.0.0.1:8765`。关闭启动程序的终端窗口即可停止。

也可以直接在终端中运行：

```bash
cd "/你的路径/SpaceLens"
python3 local_server.py
```

## 扫描磁盘与群晖

- Mac 内置磁盘显示为 `/`。
- 外置磁盘和已挂载的网络共享显示在 `/Volumes` 下。
- 群晖 SMB 共享需要先在 Finder 中选择“前往 → 连接服务器”，输入 `smb://群晖地址/共享名` 并完成挂载。
- 如果某个目录未出现在顶部磁盘卡片中，使用“选择目录…”可以直接选择它。

首次扫描“桌面”“文稿”“下载”等受保护目录时，macOS 可能请求权限。若部分目录无法读取，请在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”中允许“终端”，然后重新启动 SpaceLens。

## Finder 操作

“打开文件夹”会在 Finder 中打开目录；对仍然存在的文件，会直接在 Finder 中定位该文件。网络共享暂时断开时，需要先在 Finder 中重新挂载。
