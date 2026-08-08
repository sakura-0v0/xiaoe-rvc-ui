import os
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSystemTrayIcon,
)

from xiaoe_ui import (
    ClickFrame,
    LeftList,
    MainLayout,
    MainWin,
    NotifyOverlay,
    ThemePage,
    WinManager,
    run_in_main,
)

import info
from ui.config import LIBRARY_PATH, MODELS_DIR, RVC_ROOT, ModelLibrary
from vst_engine import editor_manager, vst_config
from ui.model_card import ModelEditDialog
from ui.pages import (
    AudioPage,
    BottomBar,
    ModelPage,
    build_chain_page,
    build_settings_page,
    build_voice_page,
)

# 修改这些参数会导致流停止（对齐原版"不支持热更新→停流"行为）
STOP_ON_CHANGE_KEYS = (
    "block_time",
    "crossfade_length",
    "extra_time",
    "sg_wasapi_exclusive",
    "sg_hostapi",
    "sg_input_device",
    "sg_output_device",
    "sr_type",
)


class RvcApp(MainWin):
    def __init__(self, engine, theme_cfg, rvc_cfg, audio_engine, show_default=True):
        self.engine = engine
        self.theme_cfg = theme_cfg
        self.rvc_cfg = rvc_cfg
        self.ae = audio_engine
        self.library = ModelLibrary(MODELS_DIR, LIBRARY_PATH)
        # 库中没有有效模型时才尝试导入原版默认模型
        if not any(e.get("model") for e in self.library.entries()):
            self._import_legacy_default_model()
        self._running = False
        self._starting = False
        self._restart_pending = False
        # 通知文字跟随主题主标题色（框架默认是白色，白字+半透明白背景对比度太低）
        self.notify = NotifyOverlay(
            text_color_cb=lambda: tuple(
                self.engine.resolve_value(self.theme_cfg, "config_title_color")
            )
        )

        self._add_card_qss()

        super().__init__(
            win_title=info.APP_NAME,
            scroll=False,  # MainLayout 自带左右独立滚动区，外层滚动关闭
            maxsize_btn=False,  # 隐藏按钮替代最大化按钮
            hide_btn=True,
            show_default=show_default,  # 框架参数控制初始显示（启动隐藏用）
        )
        self.setup_ui()
        self.resize(1024, 700)
        self.apply_all()
        self._wire()
        self._setup_tray()
        # 初始显示由框架 show_default 参数驱动（启动隐藏时 False 则隐藏到托盘）
        if self.show_default:
            self.show()

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------
    def _add_card_qss(self):
        self.engine.add_qss(
            """
            /* 仅给必要按钮配色，其余按钮保持框架默认 */
            #startBtn {
                background: rgb(0, 160, 80);
                color: rgb(255, 255, 255);
                border: none;
            }
            #startBtn:hover { background: rgb(0, 190, 95); }
            #startBtn:disabled, #stopBtn:disabled {
                background: rgba(0, 0, 0, 0.12);
                color: rgba(0, 0, 0, 0.35);
                border: none;
            }

            #stopBtn, #dangerBtn {
                background: rgb(213, 0, 0);
                color: rgb(255, 255, 255);
                border: none;
            }
            #stopBtn:hover, #dangerBtn:hover { background: rgb(255, 60, 60); }

            #primaryBtn {
                background: rgb({{config_elem_color_3}});
                color: rgb(255, 255, 255);
                border: none;
            }
            #primaryBtn:hover { background: rgb({{config_elem_color_2}}); }

            #cancelBtn {
                background: rgba(0, 0, 0, 0.06);
                color: rgb({{config_item_title_color}});
                border: none;
            }
            #cancelBtn:hover { background: rgba(0, 0, 0, 0.12); }

            /* 「＋」导入块文字 */
            #addPlus {
                font-size: 44px;
                color: rgb({{config_elem_color_3}});
            }
            """
        )

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def add_ui(self):
        layout = MainLayout(self)  # 自带左右独立滚动区，挂在 content_layout 上
        left = LeftList()

        # 首页
        page_home = left.add_page("home", "首页", icon="🏠")
        self._build_home(page_home)

        # 模型库（配置项直接放页面布局，右侧滚动由 MainLayout 负责）
        page_model = left.add_page("model", "模型列表", icon="🧬")
        self.model_page = ModelPage(
            page_model,
            self.library,
            on_activate=self._switch_model,
            on_edit=self._edit_model,
        )
        page_model.addStretch(1)

        # 音频设备
        page_audio = left.add_page("audio", "音频设备", icon="📢")
        self.audio_page = AudioPage(page_audio, self.rvc_cfg, self.ae)
        page_audio.addStretch(1)


        # 音频处理（输入/输出二级页）
        fx_group = left.add_group("fx", "音频处理", icon="🎛")
        page_in = fx_group.add_page("nr_in", "输入处理", icon="📥")
        build_chain_page(page_in, self.rvc_cfg, "I")
        page_in.addStretch(1)
        page_out = fx_group.add_page("nr_out", "输出处理", icon="📤")
        build_chain_page(page_out, self.rvc_cfg, "O")
        page_out.addStretch(1)

        # 变声设置
        page_voice = left.add_page("voice", "变声设置", icon="🎤")
        build_voice_page(page_voice, self.rvc_cfg)
        page_voice.addStretch(1)

        # 通用设置
        page_settings = left.add_page("settings", "通用设置", icon="⚙")
        build_settings_page(page_settings, self.rvc_cfg)
        page_settings.addStretch(1)

        # 主题（ThemePage 内部自己会在末尾 addStretch）
        page_theme = left.add_page("theme", "自定主题", icon="🎨")
        ThemePage(
            page_theme,
            engine=self.engine,
            config=self.theme_cfg,
            on_style_changed=WinManager.apply_style_all,
        )

        # 侧栏底部补 stretch，让导航项靠上排列
        left.add_stretch_before_left()

        left.switch_to("home")

        layout.left_layout.addLayout(left.left_layout)
        layout.right_layout.addWidget(left.stack, 1)

        # 底部操作栏：并列放在左右栏下方（全宽，固定于窗口底部）
        self.bottom_bar = BottomBar()
        self.content_layout.addWidget(self.bottom_bar)
        self.content_layout.setStretch(0, 1)  # MainLayout 占满剩余高度，底部栏贴底

    def _build_home(self, page):
        """首页：大字在上方剩余空间居中，信息行贴底（ClickFrame 细线版）。"""
        page.setSpacing(6)

        # 大字在上方剩余空间垂直居中
        page.addStretch(1)

        # 大字行：图标+名字包在 ClickFrame 容器里，点击跳项目 GitHub（暂用作者链接）
        title_frame = ClickFrame(hand_cursor=True)
        title_frame.setToolTip("点击打开项目 GitHub")
        title_frame.on_left_click(
            lambda: QDesktopServices.openUrl(
                QUrl(info.APP_GITHUB_URL)
            )
        )
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(24, 16, 24, 16)
        title_layout.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QIcon(self._icon_source).pixmap(96, 96))
        title_layout.addWidget(logo)
        title_label = QLabel(info.APP_NAME)
        title_label.setProperty("class", "app_title")
        title_label.setAlignment(Qt.AlignCenter)
        title_layout.addWidget(title_label)
        page.addWidget(title_frame, 0, Qt.AlignHCenter)

        page.addStretch(1)

        # 信息行贴底：标题左对齐 + 值左对齐（表单式对齐）；链接行可点击
        def info_row(title, value, url=None):
            frame = ClickFrame(default_line=True, hand_cursor=url is not None)
            if url:
                frame.setToolTip("点击打开")
                frame.on_left_click(
                    lambda: QDesktopServices.openUrl(QUrl(url))
                )
            lay = QHBoxLayout(frame)
            lay.setContentsMargins(16, 7, 16, 7)
            t = QLabel(title)
            t.setFixedWidth(112)
            t.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            v = QLabel(value)
            v.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lay.addWidget(t)
            lay.addWidget(v)
            page.addWidget(frame)

        info_row("软件版本", f"v{info.APP_VERSION}")
        info_row("作者B站", "一只黄小娥", info.AUTHOR_BILIBILI_URL)
        info_row("RVC 适配版本", info.ADAPTED_RVC_VERSION)
        info_row("RVC 当前版本", info.detect_rvc_version())
        info_row(
            "RVC 原项目",
            "Retrieval-based-Voice-Conversion-WebUI",
            info.RVC_GITHUB_URL,
        )
        info_row("RVC 作者B站", "花儿不哭", info.RVC_AUTHOR_BILIBILI_URL)

    # ------------------------------------------------------------------
    # 信号接线
    # ------------------------------------------------------------------
    def _wire(self):
        self.ae.on_status = self._on_status

        # 热更新参数
        self.rvc_cfg.on("pitch", self._hot_pitch)
        self.rvc_cfg.on("formant", self._hot_formant)
        self.rvc_cfg.on("index_rate", self._hot_index_rate)
        self.rvc_cfg.on("I_noise_reduce", self._hot_noise_reduce)
        # 降噪链热切换：不重启流，后台重建链引擎后原子替换
        self.rvc_cfg.on("I_chain", self._hot_nr_chain)
        self.rvc_cfg.on("O_chain", self._hot_nr_chain)

        # 不支持热更新 → 自动重启（防抖，避免拖动滑块时疯狂重建）
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(350)
        self._restart_timer.timeout.connect(self._do_restart)
        for key in STOP_ON_CHANGE_KEYS:
            self.rvc_cfg.on(key, self._make_restart_on_change())

        # 转换模式由 config.on 驱动（变声设置页的 CheckItem 配置项）
        self.ae.function = "vc" if self.rvc_cfg.get("vc") else "im"
        self.rvc_cfg.on("im", self._on_im_change)
        self.rvc_cfg.on("vc", self._on_vc_change)

        self.bottom_bar.start_btn.clicked.connect(self._start)
        self.bottom_bar.stop_btn.clicked.connect(self._stop)

        # VST 编辑器子进程回调（参数实时同步即持久化，关窗无需重建链）
        editor_manager.on_error = self._on_vst_editor_error
        editor_manager.on_param = self._on_vst_param

        self._update_delay()
        self._update_model_label()
        self._set_ui_starting(False)  # 初始化按钮状态：未运行时停止按钮置灰

    # ------------------------------------------------------------------
    # 引擎状态 → UI
    # ------------------------------------------------------------------
    def _on_status(self, name, value):
        if name == "infer_time":
            run_in_main(lambda: self.bottom_bar.infer_label.setText(f"推理:{value}ms"))
        elif name == "samplerate":
            run_in_main(lambda: self.bottom_bar.sr_label.setText(f"采样率:{value}"))
        elif name == "running":
            run_in_main(lambda: self._set_running(value))
        elif name == "vst_error":
            side, path, msg = value
            run_in_main(lambda: self._notify(f"VST 插件加载失败（{path}）：{msg}"))

    def _set_running(self, running):
        self._running = running
        self._update_tray_actions()
        if self._starting:
            return  # 启动/重载期间按钮状态由 _set_ui_starting 管理
        self.bottom_bar.start_btn.setEnabled(not running)
        self.bottom_bar.stop_btn.setEnabled(running)

    def _update_tray_actions(self):
        """打钩当前所处状态：运行中勾「开始」，已停止勾「停止」。"""
        running = self._running
        self.tray_action_start.setChecked(running)
        self.tray_action_stop.setChecked(not running)

    # ------------------------------------------------------------------
    # 热更新处理
    # ------------------------------------------------------------------
    def _hot_pitch(self, v):
        if hasattr(self.ae, "rvc"):
            try:
                self.ae.rvc.change_key(v)
            except Exception:
                traceback.print_exc()

    def _hot_formant(self, v):
        if hasattr(self.ae, "rvc"):
            try:
                self.ae.rvc.change_formant(v)
            except Exception:
                traceback.print_exc()

    def _hot_index_rate(self, v):
        if hasattr(self.ae, "rvc"):
            try:
                self.ae.rvc.change_index_rate(v)
            except Exception:
                traceback.print_exc()

    def _hot_noise_reduce(self, v):
        self._update_delay()

    def _hot_nr_chain(self, v):
        self.ae.hot_update_nr()
        self._update_delay()

    def _make_restart_on_change(self):
        def handler(value):
            if self._running:
                self._restart_pending = True
                self._restart_timer.start()
        return handler

    def _do_restart(self):
        """停流并用当前配置重启转换（自动重载，显示"重新加载中"）。"""
        if not self._restart_pending:
            return
        self._restart_pending = False
        self.ae.stop_stream()
        self._threaded_reload(self._do_start)

    # ------------------------------------------------------------------
    # 开始 / 停止
    # ------------------------------------------------------------------
    def _start(self):
        if self._starting:
            return
        entry = self.library.active_entry()
        if entry is None or not entry.get("model"):
            self._notify("请先在模型库导入并选择模型")
            return
        pth = self.library.model_path(entry["id"])
        idx = self.library.index_path(entry["id"])
        if not pth or not os.path.exists(pth):
            self._notify("模型文件缺失，请重新导入")
            return
        # 写回配置（同步到引擎参数）
        self.rvc_cfg.set("pth_path", pth)
        self.rvc_cfg.set("index_path", idx or "")
        self._threaded_reload(self._do_start)

    def _do_start(self):
        self.ae.set_devices(
            self.rvc_cfg.get("sg_input_device"),
            self.rvc_cfg.get("sg_output_device"),
        )
        self.ae.start_vc()

    def _threaded_reload(self, work, success_msg=None):
        """后台加载/切换模型，期间底部栏与开始按钮统一显示"加载中"。

        本 app 的 CUDA 推理本就在 sounddevice 回调线程运行，后台线程安全。
        """
        if self._starting:
            return
        self._starting = True
        self._notify("加载中...")
        self._set_ui_starting(True)

        def worker():
            try:
                work()
            except Exception:
                traceback.print_exc()
                run_in_main(lambda: self._notify("操作失败，请查看控制台日志"))
            else:
                if success_msg:
                    run_in_main(lambda: self._notify(success_msg))
                else:
                    run_in_main(lambda: self._notify("变声已启动"))
            finally:
                run_in_main(self._finish_start)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_start(self):
        self._starting = False
        self._set_ui_starting(False)
        self._update_delay()

    def _set_ui_starting(self, starting):
        self.bottom_bar.start_btn.setText("开始" if not starting else "加载中...")
        if starting:
            self.bottom_bar.start_btn.setEnabled(False)
            self.bottom_bar.stop_btn.setEnabled(False)
        else:
            self.bottom_bar.start_btn.setEnabled(not self._running)
            self.bottom_bar.stop_btn.setEnabled(self._running)
        self.bottom_bar.model_label.setText(
            self._model_name_text() if not starting else "正在加载..."
        )

    def _model_name_text(self):
        entry = self.library.active_entry()
        name = entry.get("name") if entry else None
        return f"当前模型: {name}" if name else "当前模型: 未选择"

    def _notify(self, text):
        """通知横幅，受「通知显示」开关控制。"""
        if self.rvc_cfg.get("notify_show"):
            self.notify.show(text)

    def _on_vst_editor_error(self, side, path, msg):
        run_in_main(lambda: self._notify(msg))

    def _on_vst_param(self, side, path, name, value):
        """编辑器子进程的参数变化：实时应用到音频链实例 + 写入配置（即持久化）。"""
        vst_config.set_param(path, name, value)
        nr = getattr(self.ae, "_in_nr" if side == "I" else "_out_nr", None)
        if nr is None:
            return
        for eng in getattr(nr, "engines", []):
            if getattr(eng, "path", None) == path and getattr(eng, "plugin", None) is not None:
                try:
                    setattr(eng.plugin, name, value)
                except Exception:
                    pass
                return

    def _stop(self):
        # 用户手动停止：取消待执行的重启
        self._restart_timer.stop()
        self._restart_pending = False
        self.ae.stop_stream()
        self._notify("变声已停止")

    def _on_im_change(self, value):
        if value:
            self.rvc_cfg.set("vc", False)  # 互斥：取消另一个
            self.ae.function = "im"

    def _on_vc_change(self, value):
        if value:
            self.rvc_cfg.set("im", False)
            self.ae.function = "vc"

    def _update_model_label(self):
        self.bottom_bar.model_label.setText(self._model_name_text())

    def _update_delay(self):
        bt = self.rvc_cfg.get("block_time")
        cf = self.rvc_cfg.get("crossfade_length")
        delay = bt + cf + 0.01
        if self.rvc_cfg.get("I_noise_reduce"):
            for el in self.rvc_cfg.get("I_chain") or []:
                if not el.get("enabled", True) or el.get("type") != "algo":
                    continue
                name = el.get("name")
                if name == "TorchGate":
                    delay += min(cf, 0.04)
                elif name == "RNNoise":
                    delay += 0.01
                elif name == "DTLN":
                    delay += 0.032
        # VST 插件延迟（链已构建时从引擎读取）
        for attr in ("_in_nr", "_out_nr"):
            nr = getattr(self.ae, attr, None)
            if nr is None:
                continue
            for eng in getattr(nr, "engines", []):
                lat = getattr(eng, "latency", 0) or 0
                if lat:
                    delay += lat / max(self.ae.gui_config.samplerate, 1)
        if self.ae.stream is not None:
            try:
                delay += self.ae.stream.latency[-1]
            except Exception:
                pass
        self.bottom_bar.delay_label.setText(f"延迟:{int(round(delay * 1000))}ms")

    # ------------------------------------------------------------------
    # 模型库
    # ------------------------------------------------------------------
    def _import_legacy_default_model(self):
        """库中无有效模型时，尝试导入原版 RVC 默认模型；失败仅打印日志，不中断启动。"""
        try:
            pth = self.rvc_cfg.get("pth_path")
            if not pth:
                return
            # 原版配置里可能是相对路径（如 assets/weights/kikiV1.pth），基于 RVC 根解析
            if not os.path.isabs(pth):
                pth = os.path.join(RVC_ROOT, pth)
            if os.path.exists(pth):
                idx = self.rvc_cfg.get("index_path")
                if idx and not os.path.isabs(idx):
                    idx = os.path.join(RVC_ROOT, idx)
                self.library.import_model(
                    pth,
                    idx if idx and os.path.exists(idx) else None,
                    name=os.path.splitext(os.path.basename(pth))[0],
                )
        except Exception:
            traceback.print_exc()

    def _switch_model(self, mid):
        entry = self.library.get_entry(mid)
        if entry is None or not entry.get("model"):
            return
        self.library.set_active(mid)
        pth = self.library.model_path(mid)
        idx = self.library.index_path(mid)
        self.rvc_cfg.set("pth_path", pth)
        self.rvc_cfg.set("index_path", idx or "")
        self.model_page.refresh()
        self._update_model_label()
        if self._running:
            self._threaded_reload(
                lambda: self.ae.switch_model(pth, idx or ""),
                success_msg=f"已切换：{entry.get('name')}",
            )

    def _edit_model(self, mid):
        entry = self.library.get_entry(mid)
        if entry is None:
            return
        dlg = ModelEditDialog(self, self.library, entry, on_changed=self._on_library_changed)
        dlg.exec()

    def _on_library_changed(self):
        self.model_page.refresh()
        self._update_model_label()

    # ------------------------------------------------------------------
    # 系统托盘
    # ------------------------------------------------------------------
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(QIcon(self._icon_source), self)
        self.tray.setToolTip(info.APP_NAME)
        menu = QMenu()
        menu.addAction("显示主窗口", self._show_main_window)
        self.tray_action_start = menu.addAction("开始")
        self.tray_action_start.setCheckable(True)
        self.tray_action_start.triggered.connect(self._start)
        self.tray_action_stop = menu.addAction("停止")
        self.tray_action_stop.setCheckable(True)
        self.tray_action_stop.triggered.connect(self._stop)
        menu.addAction("退出", self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._update_tray_actions()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_main_window()

    def _show_main_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        self.ae.stop_stream()
        editor_manager.close_all()
        self.tray.hide()
        QApplication.instance().quit()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self.ae.stop_stream()
        editor_manager.close_all()
        super().closeEvent(event)
