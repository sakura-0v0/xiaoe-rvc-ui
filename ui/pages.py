import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from xiaoe_ui import (
    BottomItem,
    CheckItem,
    ComboItem,
    SliderItem,
    ask,
    error,
    info,
    make_form_row,
    make_line,
    make_tip,
)

from fast_desktop import (
    create_shortcut_file,
    get_desktop_path,
    get_startup_path,
)
from info import APP_NAME
from ui.config import XIAOE_DIR

from ui.model_card import (
    CARD_HEIGHT,
    CARD_WIDTH,
    AddModelCard,
    ModelCard,
    ModelEditDialog,
)
from ui.nr_chain import DragCheckList

SR_OPTIONS = ["使用模型采样率", "使用设备采样率"]
SR_VALUES = ["sr_model", "sr_device"]

# 可选降噪算法：(显示名, 配置值)。编号=降噪效果，编号越大效果越强
NR_ALGORITHMS = [
    ("1. TorchGate（降噪算法）", "TorchGate"),
    ("2. RNNoise（降噪算法）", "RNNoise"),
    ("3. DTLN（降噪算法）", "DTLN"),
]

# 处理链页共用说明（输入/输出两页引用同一字符串）
CHAIN_TIP = (
    "使用方法：勾选要启用的算法，按住 ≡ 拖拽调整处理顺序（从上到下依次执行）。\n"
    "1. TorchGate —— 频谱门控降噪（内置默认）\n"
    "2. RNNoise —— 经典神经网络降噪，效果不错且占用低（推荐）\n"
    "3. DTLN —— 深度学习降噪，占用最高，但实际效果似乎反而不如 2 号，可自己试试对比\n"
    "\nVST3 插件：点「+ 添加 VST3」选 .vst3 文件即可混入链中（与算法同链自由排序）。\n"
    "「设置」在独立进程弹出插件原厂窗口，不影响实时音频；调整参数实时生效并自动保存。\n"
    "重开软件自动恢复（个别插件需先打开一次界面才应用保存的参数）。"
)


# ---------------------------------------------------------------------------
# 模型库页
# ---------------------------------------------------------------------------
GRID_SPACING = 14


class _GridWidget(QWidget):
    """固定大小卡片 + 自动换行的网格容器。

    卡片按固定行列步长手动定位，宽度变化时按列数自动换行，
    不会像 QGridLayout 那样拉伸列距产生不均匀间距。
    """

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._cards = []

    def set_cards(self, cards):
        for c in self._cards:
            if hasattr(c, "cleanup"):
                c.cleanup()
            c.setParent(None)
            c.deleteLater()
        self._cards = cards
        for c in cards:
            c.setParent(self)
        self._relayout()

    def _cols(self):
        w = self.width()
        if w <= 0:
            return 4
        per = CARD_WIDTH + GRID_SPACING
        return max(1, w // per)

    def _relayout(self):
        cols = self._cols()
        for i, c in enumerate(self._cards):
            c.move(
                (i % cols) * (CARD_WIDTH + GRID_SPACING),
                (i // cols) * (CARD_HEIGHT + GRID_SPACING),
            )
            c.show()
        rows = (len(self._cards) + cols - 1) // cols
        self.setMinimumHeight(
            max(0, rows * (CARD_HEIGHT + GRID_SPACING) - GRID_SPACING + 4)
        )
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()


class ModelPage:
    def __init__(self, container, library, on_activate=None, on_edit=None):
        self.container = container  # 页面内容布局
        self.library = library
        self.on_activate = on_activate
        self.on_edit = on_edit

        self.grid_widget = _GridWidget()
        container.addWidget(self.grid_widget)
        self.refresh()

    def refresh(self):
        entries = self.library.entries()
        active = self.library.active_id()
        cards = []
        for e in entries:
            card = ModelCard(e, self.library, e["id"] == active)
            card.clicked.connect(self._on_card_clicked)
            card.edit_clicked.connect(self._on_card_edit)
            cards.append(card)
        # 末尾放「＋」导入块
        add_card = AddModelCard()
        add_card.clicked.connect(self._import)
        cards.append(add_card)
        self.grid_widget.set_cards(cards)

    def _on_card_clicked(self, mid):
        if self.on_activate:
            self.on_activate(mid)

    def _on_card_edit(self, mid):
        if self.on_edit:
            self.on_edit(mid)

    def _import(self):
        # 先建一个空块，再打开它的编辑页，模型文件在编辑页里上传
        entry = self.library.create_entry()
        self.refresh()
        if self.on_edit:
            self.on_edit(entry["id"])


# ---------------------------------------------------------------------------
# 变声设置页
# ---------------------------------------------------------------------------
def build_voice_page(container, config):
    # 转换模式（框架 CheckItem 配置项，互斥由应用层 config.on 处理）
    CheckItem(
        "输入监听", text="直通不转换",
        config=config, config_name="im", parent_layout=container,
    )
    CheckItem(
        "输出变声", text="实时变声",
        config=config, config_name="vc", parent_layout=container,
    )

    make_line(container, bold=True)

    # 滑块 text 是 tooltip，可写完整些；复选框/下拉是行内描述，保持简短
    SliderItem(
        "响应阈值", text="低于该音量时不触发变声；设为 -60 即关闭",
        config=config, config_name="threhold",
        config_range=(-60, 0), step=1, parent_layout=container,
    )
    SliderItem(
        "音调设置", text="音高调整，±12 为一个八度",
        config=config, config_name="pitch",
        config_range=(-24, 24), step=1, parent_layout=container,
    )
    SliderItem(
        "性别因子", text="调整声线粗细与性别感（负值更粗，正值更细）",
        config=config, config_name="formant",
        config_range=(-2, 2), step=0.05, parent_layout=container,
    )
    SliderItem(
        "Index Rate", text="检索特征强度，越高越贴近目标音色",
        config=config, config_name="index_rate",
        config_range=(0.0, 1.0), step=0.01, parent_layout=container,
    )
    SliderItem(
        "响度因子", text="输入与输出响度的混合比例",
        config=config, config_name="rms_mix_rate",
        config_range=(0.0, 1.0), step=0.01, parent_layout=container,
    )
    ComboItem(
        "音高算法", text="基频提取方式",
        config=config, config_name="f0method",
        options=["pm", "rmvpe", "fcpe"], parent_layout=container,
    )

    make_line(container, bold=True)
    SliderItem(
        "采样长度", text="每次处理的音频时长，越短延迟越低",
        config=config, config_name="block_time",
        config_range=(0.02, 1.5), step=0.01, live=False, parent_layout=container,
    )
    SliderItem(
        "淡入淡出长度", text="音频块衔接时的平滑过渡时长",
        config=config, config_name="crossfade_length",
        config_range=(0.01, 0.15), step=0.01, live=False, parent_layout=container,
    )
    SliderItem(
        "额外推理时长", text="每块额外预留的推理时间，越大越稳定",
        config=config, config_name="extra_time",
        config_range=(0.05, 5.0), step=0.01, live=False, parent_layout=container,
    )


# ---------------------------------------------------------------------------
# 处理链页（输入/输出共用，side 区分）
# ---------------------------------------------------------------------------
def build_chain_page(container, config, side):
    if side == "I":
        switch_key, chain_key = "I_noise_reduce", "I_chain"
        switch_text = "输入处理"
        switch_desc = "启用输入处理链（降噪算法 + VST 效果器）"
    else:
        switch_key, chain_key = "O_noise_reduce", "O_chain"
        switch_text = "输出处理"
        switch_desc = "对变声后音频启用输出处理链（降噪算法 + VST 效果器）"
    CheckItem(switch_text, text=switch_desc,
              config=config, config_name=switch_key, parent_layout=container)
    DragCheckList(f"{'输入' if side == 'I' else '输出'}处理链", NR_ALGORITHMS, config,
                  chain_key, side=side, enable_key=switch_key, parent_layout=container)
    make_tip(CHAIN_TIP, parent_layout=container)


# ---------------------------------------------------------------------------
# 通用设置页
# ---------------------------------------------------------------------------
def build_settings_page(container, config):
    # 用 run.vbs 作为启动目标（隐藏 cmd 窗口，快捷方式/自启不闪黑框）
    run_launcher = os.path.join(XIAOE_DIR, "run.vbs")
    icon = os.path.join(XIAOE_DIR, "static", "logo.ico")
    lnk_name = f"{APP_NAME}.lnk"

    def _enable_startup():
        try:
            create_shortcut_file(
                os.path.join(get_startup_path(), lnk_name),
                run_launcher, XIAOE_DIR, icon,
            )
            info("成功", "已设置开机自启")
        except Exception as e:
            error("错误", f"设置失败：{e}")

    def _disable_startup():
        if ask("确认", "是否取消开机自启？"):
            try:
                os.remove(os.path.join(get_startup_path(), lnk_name))
                info("提示", "已取消开机自启")
            except FileNotFoundError:
                info("提示", "未发现开机自启快捷方式")
            except Exception as e:
                error("错误", f"移除失败：{e}")

    def _create_desktop_lnk():
        if ask("确认", "是否创建桌面快捷方式？"):
            try:
                create_shortcut_file(
                    os.path.join(get_desktop_path(), lnk_name),
                    run_launcher, XIAOE_DIR, icon,
                )
                info("成功", "桌面快捷方式已创建")
            except Exception as e:
                error("错误", f"创建失败：{e}")

    BottomItem("开机启动", text="设置开机自启或取消",
               btn_text="设置", callback=_enable_startup,
               reset_callback=_disable_startup,
               parent_layout=container)
    BottomItem("创建快捷方式", text="在桌面创建启动快捷方式",
               btn_text="创建", callback=_create_desktop_lnk,
               parent_layout=container)

    make_line(container, bold=True)

    CheckItem("通知显示", text="启动/停止变声时弹出提示",
              config=config, config_name="notify_show", parent_layout=container)
    CheckItem("启动隐藏", text="启动后隐藏到系统托盘",
              config=config, config_name="start_hidden", parent_layout=container)
    CheckItem("自动变声", text="软件启动后自动开始变声",
              config=config, config_name="auto_vc", parent_layout=container)


# ---------------------------------------------------------------------------
# 音频设备页
# ---------------------------------------------------------------------------
class AudioPage:
    def __init__(self, container, config, engine):
        self.container = container
        self.config = config
        self.engine = engine

        self.hostapi_combo = QComboBox()
        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        self.sr_combo = QComboBox()
        self.sr_combo.addItems(SR_OPTIONS)

        container.addWidget(make_form_row("设备类型", self.hostapi_combo))
        CheckItem(
            "独占 WASAPI 设备", text="低延迟独占",
            config=config,
            config_name="sg_wasapi_exclusive", parent_layout=container,
        )
        container.addWidget(make_form_row("输入设备", self.input_combo))
        container.addWidget(make_form_row("输出设备", self.output_combo))
        container.addWidget(make_form_row("采样率来源", self.sr_combo))

        reload_btn = QPushButton("重载设备列表")
        reload_btn.clicked.connect(self._reload)
        container.addWidget(reload_btn)

        self.hostapi_combo.currentTextChanged.connect(self._on_hostapi)
        self.input_combo.currentTextChanged.connect(self._on_input)
        self.output_combo.currentTextChanged.connect(self._on_output)
        self.sr_combo.currentIndexChanged.connect(self._on_sr)

        self.populate()

    def populate(self):
        self.engine.update_devices()
        self._populate_hostapi()
        self._populate_devices()
        self._populate_sr()

    def _populate_hostapi(self):
        hostapis = self.engine.hostapis or []
        self.hostapi_combo.blockSignals(True)
        self.hostapi_combo.clear()
        self.hostapi_combo.addItems(hostapis)
        saved = self.config.get("sg_hostapi")
        cur = saved if saved in hostapis else (hostapis[0] if hostapis else "")
        self.hostapi_combo.setCurrentText(cur)
        self.hostapi_combo.blockSignals(False)

    def _populate_devices(self):
        self.input_combo.blockSignals(True)
        self.output_combo.blockSignals(True)
        self.input_combo.clear()
        self.output_combo.clear()
        self.input_combo.addItems(self.engine.input_devices or [])
        self.output_combo.addItems(self.engine.output_devices or [])
        saved_in = self.config.get("sg_input_device")
        saved_out = self.config.get("sg_output_device")
        if saved_in in (self.engine.input_devices or []):
            self.input_combo.setCurrentText(saved_in)
        elif self.engine.input_devices:
            self.input_combo.setCurrentText(self.engine.input_devices[0])
        if saved_out in (self.engine.output_devices or []):
            self.output_combo.setCurrentText(saved_out)
        elif self.engine.output_devices:
            self.output_combo.setCurrentText(self.engine.output_devices[0])
        self.input_combo.blockSignals(False)
        self.output_combo.blockSignals(False)
        self.config.set("sg_hostapi", self.hostapi_combo.currentText())
        self.config.set("sg_input_device", self.input_combo.currentText())
        self.config.set("sg_output_device", self.output_combo.currentText())

    def _populate_sr(self):
        self.sr_combo.blockSignals(True)
        cur = self.config.get("sr_type")
        self.sr_combo.setCurrentIndex(SR_VALUES.index(cur) if cur in SR_VALUES else 0)
        self.sr_combo.blockSignals(False)

    def _on_hostapi(self):
        name = self.hostapi_combo.currentText()
        if not name:
            return
        self.engine.update_devices(hostapi_name=name)
        self._populate_devices()
        self.config.set("sg_hostapi", name)
        self.engine.stop_stream()

    def _on_input(self):
        self.config.set("sg_input_device", self.input_combo.currentText())
        self.engine.stop_stream()

    def _on_output(self):
        self.config.set("sg_output_device", self.output_combo.currentText())
        self.engine.stop_stream()

    def _on_sr(self):
        idx = self.sr_combo.currentIndex()
        self.config.set("sr_type", SR_VALUES[idx] if 0 <= idx < len(SR_VALUES) else "sr_model")
        self.engine.stop_stream()

    def _reload(self):
        self.populate()
        self.engine.stop_stream()


# ---------------------------------------------------------------------------
# 底部控制栏
# ---------------------------------------------------------------------------
class BottomBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("bottomBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        # 状态显示在左
        self.model_label = QLabel("当前模型: 未选择")
        self.model_label.setObjectName("modelLabel")
        layout.addWidget(self.model_label)

        self.delay_label = QLabel("延迟:0ms")
        self.infer_label = QLabel("推理:0ms")
        self.sr_label = QLabel("采样率:-")
        layout.addWidget(self.delay_label)
        layout.addWidget(self.infer_label)
        layout.addWidget(self.sr_label)

        layout.addStretch(1)

        # 开始 / 停止在右
        self.start_btn = QPushButton("开始")
        self.start_btn.setObjectName("startBtn")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("stopBtn")
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
