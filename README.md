# xiaoe_rvc_ui — 基于 xiaoe_ui 框架的 RVC 实时变声界面

基于 [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) 实时变声的图形界面，基于自研 PySide6 框架 `xiaoe_ui` 重写。界面更美观，支持模型库（图片网格 + 点击热切换 + 编辑/排序），内置 37 套主题可切换。

## 安装

只需两步：解压 RVC 整合包 → 双击 `install.bat` 一键部署。

1. **下载并解压原版 RVC**：前往 [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) 的 Releases 页下载整合包并解压，得到 RVC 根目录（含 `runtime`、`realtime_gui.py`、`configs` 等）。
2. **下载本项目**：前往本项目的 [Release 页面](https://github.com/sakura-0v0/xiaoe-rvc-ui/releases) 下载并解压（若 ZIP 解压后文件夹名带 `-main` 等后缀，先重命名文件夹为 `xiaoe_rvc_ui`）。
3. **双击 `install.bat` 一键部署 / 更新**：
   - ⚠️ **最关键一步——选择 RVC 根目录**：在弹出的窗口中选择你解压 RVC 整合包得到的那个文件夹（即含 `runtime`、`realtime_gui.py`、`configs` 的那个）。选错会提示重新选择。
   - 自动把应用部署到 RVC 根目录下的 `xiaoe_rvc_ui\`，**自动保留 `config_files/` 设置与 `models/` 模型**（升级/重装不会被覆盖）。
   - 完成后询问**是否创建桌面快捷方式**。
   - 安装器会**记住上次选择的 RVC 根目录**：下次再运行 `install.bat` 自动识别上次路径并询问是否更新到该路径。
4. **启动**：双击桌面上的「RVC实时变声-小娥UI版」快捷方式即可（无控制台、不闪黑框；首次运行自动联网安装依赖，进度实时显示在弹窗内）。

## 使用

- **模型库（首页）**：点「＋ 导入模型」选择 `.pth`（可同时选 `.index` 和封面图），文件会自动复制进 `models/`。卡片点击即热切换；卡片左下角 ✎ 可编辑（改图/改名/上传 index/删除/↑↓ 排序）。
- **音频处理（降噪 + VST3 机架）**：输入/输出各一条独立处理链（侧栏「音频处理」二级页），内置 TorchGate / RNNoise / DTLN 三种降噪算法（可拖拽排序，调整即时热切换，无需重启），并支持加载 VST3 插件与降噪算法同链混排（插件机架）——插件可弹出原厂界面实时调参、参数自动保存、重开软件自动恢复。
- **变声设置**：响应阈值、音调、性别因子、Index Rate、响度因子、音高算法、采样长度、淡入淡出、额外推理时长。
- **音频设备**：设备类型、独占 WASAPI、输入/输出设备、采样率来源。
- **主题**：37 套内置主题一键切换，可自定义配色并保存。
- **底部栏**：开始/停止转换、输入监听/输出变声、延迟/推理时间/采样率。

## 文件说明

```
xiaoe_rvc_ui/
├── install.bat / install.ps1              # 部署安装器：选 RVC 根目录 → 复制/更新（保留用户数据）→ 创建桌面快捷方式
├── InstallDependencies.bat                # 手动联网安装依赖
├── run.vbs                                # 无控制台启动（不闪黑框）
├── launcher.py                            # 启动器：依赖检查 → 自动安装（进度弹窗）→ 启动
├── run_with_console.bat                   # 带控制台启动（查看日志 / 安装进度）
├── main.py                  # 应用入口
├── audio_engine.py          # 实时 DSP 核心（来自原rvc的 realtime_gui.py，逻辑逐字保留）
├── models/                  # 模型库（首次导入自动创建）
└── ui/                      # 界面层
```

- **`install.bat` / `install.ps1`** — 部署安装器。选择 RVC 根目录后自动部署/更新应用，保留 `config_files/` 设置与 `models/` 模型，并可创建桌面快捷方式（记住上次路径，下次直接更新）。
- **`run.vbs`** — 无控制台启动入口，双击即用；首次运行自动检查并安装依赖。
- **`launcher.py`** — 被 `run.vbs` 调用：依赖检查 → 自动安装（进度实时显示在弹窗内）→ 启动主程序。
- **`run_with_console.bat`** — 带控制台启动，方便查看运行日志 / 首次安装进度。
- **`InstallDependencies.bat`** — 手动联网安装依赖（一般不需要，`run.vbs` 首次启动会自动安装）。

## 依赖

- **本项目依赖**（`requirements.txt`，首次启动自动安装）：`PySide6`（GUI）、`pywin32`（托盘/快捷方式）、`pyrnnoise`（RNNoise 降噪）、`pedalboard`（VST3 插件）、`xiaoe_ui`（自研界面框架，闭源 whl）。
- **RVC 自带**：`runtime`（Python + PyTorch 等）由原版 RVC 提供，本界面直接使用，无需额外安装。


## 开源协议

本项目代码以 [MIT License](LICENSE) 开源，Copyright © 2026 一只黄小娥。音频处理核心（`audio_engine.py`）源自 [RVC-Project](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)（MIT），版权见 LICENSE。界面框架 `xiaoe_ui` 为闭源依赖，不适用本项目协议，见上方闭源声明。

> **闭源依赖声明**：本项目的界面框架 `xiaoe_ui` 为闭源专有软件，仅授权在本项目及作者已明确声明授权的其他项目内使用，禁止任何形式他用、修改、再分发或逆向。详见 [xiaoe_ui 使用许可声明](xiaoe_ui_LICENSE.md)。
