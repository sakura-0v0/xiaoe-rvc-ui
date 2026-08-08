import os
import sys

# 本文件位于 xiaoe_rvc_ui/ 下，RVC 根目录是其父目录。
# launcher.py / run_with_console.bat 以 -I 隔离模式启动，显式把脚本目录与 RVC 根目录都加进 sys.path，
# 否则 from audio_engine import ... / from configs.config import Config 等导入会失败。
XIAOE_DIR = os.path.dirname(os.path.abspath(__file__))
RVC_ROOT = os.path.dirname(XIAOE_DIR)
sys.path.insert(0, XIAOE_DIR)
sys.path.insert(0, RVC_ROOT)

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ["OMP_NUM_THREADS"] = "4"


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from xiaoe_ui import ConfigBridge, StyleEngine, WinManager, to_china_text
    from xiaoe_ui import resolve_static

    from configs.config import Config

    from audio_engine import AudioEngine
    from ui.app import RvcApp
    from ui.config import make_rvc_config

    # ① 主题引擎 —— 最先创建，get_defaults() 给主题 config 提供初始值
    engine = StyleEngine()
    # 背景图默认值指向 static 文件夹；图标不归主题管理，用 set_icon_source 单独设置
    engine.set_internal_default(
        "bg_image", resolve_static("xiaoe_rvc_ui/static/background.png")
    )

    # ② 配置 —— 业务配置 + 主题配置；params 是 AudioEngine 直接读的参数对象
    rvc_cfg, theme_cfg, rvc_params = make_rvc_config(engine)

    # ③ Qt 启动
    app = QApplication(sys.argv)
    to_china_text(app, "translations")

    # ④ WinManager 全局注入 —— 设好 source，后续窗口自动继承
    WinManager.set_style_source(lambda: engine.make_style(theme_cfg))
    WinManager.set_bg_source(lambda: engine.resolve_value(theme_cfg, "bg_image"))
    WinManager.set_icon_source(resolve_static("xiaoe_rvc_ui/static/logo.ico"))

    # ⑤ 引擎 —— 传入 RVC 的 Config 与业务参数
    rvc_engine = AudioEngine(rvc_params, Config())

    # ⑥ 主窗口
    win = RvcApp(
        engine=engine,
        theme_cfg=theme_cfg,
        rvc_cfg=rvc_cfg,
        audio_engine=rvc_engine,
        show_default=not rvc_cfg.get("start_hidden"),
    )
    # 通用设置：启动自动变声（窗口隐藏时 _start 也可用）
    if rvc_cfg.get("auto_vc"):
        QTimer.singleShot(600, win._start)
    app.exec()


if __name__ == "__main__":
    main()
