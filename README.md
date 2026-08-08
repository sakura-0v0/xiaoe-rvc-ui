# xiaoe_rvc_ui — 基于 xiaoe_ui 框架的 RVC 实时变声界面

基于 [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) 实时变声的图形界面，基于自研 PySide6 框架 `xiaoe_ui` 重写。界面更美观，支持模型库（图片网格 + 点击热切换 + 编辑/排序），内置 37 套主题可切换。

## 安装

本文件夹需放置在 **RVC 根目录下**（与 `realtime_gui.py`、`runtime`、`configs` 同级）。

1. **下载并解压原版 RVC**：前往 [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) 的 Releases 页下载整合包并解压，得到含 `runtime`、`configs`、`realtime_gui.py` 等文件、文件夹的 RVC 根目录。
2. **下载本项目**：前往本项目的 [Release 页面](https://github.com/sakura-0v0/xiaoe-rvc-ui/releases) 下载（解压即用）。若直接下载项目 ZIP，解压后的文件夹名会带 `-main` 等后缀，请**先重命名文件夹为 `xiaoe_rvc_ui`**。
3. 把 `xiaoe_rvc_ui` 文件夹复制到 RVC 根目录（文件夹名必须为 `xiaoe_rvc_ui`，并且注意目录结构！）。
4. 双击 `xiaoe_rvc_ui\run.vbs` 启动即可（无控制台窗口，**不会闪黑框**）。启动器自动检测依赖，**首次运行弹窗询问后自动联网安装**（PySide6、xiaoe_ui、pedalboard 等，安装进度可见），任何错误都会弹窗提示；之后直接启动，无需手动装依赖。
5. 想查看运行日志 / 首次安装进度，可双击 `xiaoe_rvc_ui\run_with_console.bat`（带控制台，同样会自动装依赖）；也可单独双击 `xiaoe_rvc_ui\install.bat` 手动安装依赖。

## 依赖

- **本项目依赖**（`requirements.txt`，首次启动自动安装）：`PySide6`（GUI）、`pywin32`（托盘/快捷方式）、`pyrnnoise`（RNNoise 降噪）、`pedalboard`（VST3 插件）、`xiaoe_ui`（自研界面框架，闭源 whl）。
- **RVC 自带**：`runtime`（Python + PyTorch 等）由原版 RVC 提供，本界面直接使用，无需额外安装。

## 使用

- **模型库（首页）**：点「＋ 导入模型」选择 `.pth`（可同时选 `.index` 和封面图），文件会自动复制进 `models/`。卡片点击即热切换；卡片左下角 ✎ 可编辑（改图/改名/上传 index/删除/↑↓ 排序）。
- **音频处理（降噪 + VST3 机架）**：输入/输出各一条独立处理链（侧栏「音频处理」二级页），内置 TorchGate / RNNoise / DTLN 三种降噪算法（可拖拽排序，调整即时热切换，无需重启），并支持加载 VST3 插件与降噪算法同链混排（插件机架）——插件可弹出原厂界面实时调参、参数自动保存、重开软件自动恢复。
- **变声设置**：响应阈值、音调、性别因子、Index Rate、响度因子、音高算法、采样长度、淡入淡出、额外推理时长。
- **音频设备**：设备类型、独占 WASAPI、输入/输出设备、采样率来源。
- **主题**：37 套内置主题一键切换，可自定义配色并保存。
- **底部栏**：开始/停止转换、输入监听/输出变声、延迟/推理时间/采样率。

## 目录说明

```
xiaoe_rvc_ui/
├── install.bat / run.vbs / launcher.py / run_with_console.bat  # 安装依赖 / 无黑框启动 / 启动器(依赖检查+错误弹窗) / 带控制台启动
├── main.py                  # 入口
├── audio_engine.py          # 实时 DSP 核心（来自原rvc的 realtime_gui.py，逻辑逐字保留）
├── models/                  # 模型库（首次导入自动创建）
└── ui/                      # 界面层
```


## 开源协议

本项目代码以 [MIT License](LICENSE) 开源，Copyright © 2026 一只黄小娥。音频处理核心（`audio_engine.py`）源自 [RVC-Project](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)（MIT），版权见 LICENSE。界面框架 `xiaoe_ui` 为闭源依赖，不适用本项目协议，见上方闭源声明。

> **闭源依赖声明**：本项目的界面框架 `xiaoe_ui` 为闭源专有软件，仅授权在本项目及作者已明确声明授权的其他项目内使用，禁止任何形式他用、修改、再分发或逆向。详见 [xiaoe_ui 使用许可声明](xiaoe_ui_LICENSE.md)。
