# xiaoe_rvc_ui — 基于 xiaoe_ui 框架的 RVC 实时变声界面

RVC 实时变声的新版图形界面，基于自研 PySide6 框架 `xiaoe_ui` 重写。界面更美观，支持模型库（图片网格 + 点击热切换 + 编辑/排序），内置 37 套主题可切换。

> **闭源依赖声明**：本项目的界面框架 `xiaoe_ui` 为闭源专有软件，仅授权在本项目及作者已明确声明授权的其他项目内使用，禁止任何形式他用、修改、再分发或逆向。详见 [xiaoe_ui 使用许可声明](xiaoe_ui_LICENSE.md)。

## 开源协议

本项目代码以 [MIT License](LICENSE) 开源，Copyright © 2026 一只黄小娥。音频处理核心（`audio_engine.py`）源自 RVC-Project（MIT），版权见 LICENSE。界面框架 `xiaoe_ui` 为闭源依赖，不适用本项目协议，见上方闭源声明。

## 安装

本文件夹需放置在 **RVC 根目录下**（与 `realtime_gui.py`、`runtime`、`configs` 同级）。

1. **下载**：建议前往 [Releases](https://github.com/sakura-0v0/xiaoe-rvc-ui/releases) 下载（解压即用）。若直接下载项目 ZIP，解压后的文件夹名会带 `-main` 等后缀，请**先重命名文件夹为 `xiaoe_rvc_ui`**。
2. 把 `xiaoe_rvc_ui` 文件夹复制到 RVC 根目录（文件夹名必须为 `xiaoe_rvc_ui`）。
3. 双击 `run.bat` 启动即可。启动脚本会自动检测依赖，**首次运行自动联网安装**（PySide6、xiaoe_ui 等），之后直接启动，无需手动装依赖。
4. 想查看运行日志可双击 `run_with_console.bat`（同样会自动装依赖）；也可单独双击 `install.bat` 手动安装依赖。

## 使用

- **模型库（首页）**：点「＋ 导入模型」选择 `.pth`（可同时选 `.index` 和封面图），文件会自动复制进 `models/`。卡片点击即热切换；卡片右上角 ✎ 可编辑（改图/改名/上传 index/删除/↑↓ 排序）。
- **变声设置**：响应阈值、音调、性别因子、Index Rate、响度因子、音高算法、输入/输出降噪、采样长度、淡入淡出、额外推理时长。
- **音频设备**：设备类型、独占 WASAPI、输入/输出设备、采样率来源。
- **主题**：37 套内置主题一键切换，可自定义配色并保存。
- **底部栏**：开始/停止转换、输入监听/输出变声、延迟/推理时间/采样率。

## 目录说明

```
xiaoe_rvc_ui/
├── install.bat / run.bat / run_with_console.bat  # 安装依赖 / 无控制台启动 / 带控制台启动
├── main.py                  # 入口
├── audio_engine.py          # 实时 DSP 核心（来自原 realtime_gui.py，逻辑逐字保留）
├── models/                  # 模型库（首次导入自动创建）
└── ui/                      # 界面层
```

配置沿用 RVC 根目录的 `configs/config.json`，与原版界面兼容；参数修改即写盘，重启自动还原。
