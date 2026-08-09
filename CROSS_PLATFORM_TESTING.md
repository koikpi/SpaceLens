# 免费跨平台测试与发行

项目使用 GitHub Actions 的标准托管运行器原生测试并构建三个版本：

- `SpaceLens-Windows-x64`：当前 Windows 10/11 x64 版
- `SpaceLens-Windows-ARM64`：Windows 11 ARM 版
- `SpaceLens-macOS-ARM64`：Apple Silicon Mac 版

工作流只配置了 `workflow_dispatch`，因此推送和 Pull Request 不会自动运行。

## 第一次使用

1. 在 GitHub 新建一个私有仓库。
2. 将本项目推送到仓库。
3. 打开仓库的 **Actions** 页面。
4. 选择 **Build cross-platform releases**。
5. 点击 **Run workflow**。
6. 三个平台和发布任务全部变绿后，打开仓库的 **Releases** 页面。
7. Windows 用户直接下载对应架构的 ZIP；Apple Silicon Mac 用户直接下载 `SpaceLens-macOS-ARM64.dmg`。

Actions 详情页的 Artifacts 会由 GitHub 统一套一层 ZIP，适合保存构建记录；面向普通用户分发时使用 Releases 页面，DMG 可以直接下载。

GitHub Free 私有仓库使用标准运行器时会先消耗每月包含的 Actions 额度。为防止产生费用，可以不添加付款方式，或在 Billing 中把 Actions 预算设为 0 并启用超额停止。

## 自动验证内容

每个平台都会：

1. 校验实际 CPU 架构。
2. 运行 Python 语法检查和单元测试。
3. 测试扫描、SQLite 文件索引、SMB 挂载解析、Finder 调用和 HTTP 接口。
4. 使用目标平台的 Python/PyInstaller 生成独立程序。
5. 真正启动打包后的程序，并请求 `http://127.0.0.1:8765/api/drives`。

## 仍需人工验证的内容

GitHub 托管运行器无法访问你的群晖，也不适合测试真实的 Finder/目录选择器交互。发布前仍建议在真实 Mac 或 Windows ARM 设备上验证：

- 目录选择窗口
- Finder/资源管理器定位
- 群晖 SMB 扫描与断线恢复
- macOS 完全磁盘访问权限
- 大型磁盘的长时间扫描和取消

## macOS Gatekeeper

CI 生成的 macOS 程序没有使用 Apple Developer ID 签名和公证。首次打开如果被 Gatekeeper 拦截，请在 Finder 中右键程序选择“打开”。如果要向普通用户正式分发，应另行配置 Apple Developer ID 签名和 Notarization。
