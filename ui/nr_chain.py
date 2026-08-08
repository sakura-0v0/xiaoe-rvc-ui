"""处理链排序控件 —— 框架 CheckItem 的链式扩展（可提炼进 xiaoe_ui 框架）。

块容器用 ClickFrame(light-line disable) 自带细线框线；每行复用 CheckItem 行结构
（ClickFrame item-line + QCheckBox）。

配置模型（统一单一列表 config_name，如 I_chain）：元素
  {"type":"algo","name":"RNNoise","enabled":bool}  算法行
  {"type":"vst","path":"C:/...","enabled":bool}    插件行
列表顺序 = 全部行顺序（含未勾选，重启恢复），enabled = 是否启用。
一个列表表达顺序 / 启用 / 插件存在，无冗余键。

绑定遵循框架 ConfigBridge 单向流：交互只改配置（config.set），一切刷新由
config.on 驱动；反向同步用 blockSignals 防回环。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xiaoe_ui import ClickFrame
from vst_engine import editor_manager, vst_config


class _DragHandle(QLabel):
    """拖拽手柄：按下拖动块内排序。"""

    def __init__(self, owner):
        super().__init__("≡")
        self.owner = owner
        self.setCursor(Qt.SizeAllCursor)
        self.setFixedWidth(24)
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.owner.begin_drag(self)

    def mouseMoveEvent(self, e):
        self.owner.drag_move(self, e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self.owner.end_drag()


class DragCheckList(QWidget):
    """一块处理链：细线框容器 + 每行「复选框(启用) + 名称 + 操作/拖拽手柄」。

    items: [(显示名, 配置值), ...]，仅用于算法显示名映射。
    side: "I"（输入）/ "O"（输出），供编辑器子进程区分。
    """

    def __init__(self, title, items, config, config_name,
                 side="I", enable_key=None, parent_layout=None):
        super().__init__()
        self.config = config
        self.config_name = config_name
        self.side = side
        self._items = [
            (it, it) if isinstance(it, str) else (it[0], it[1]) for it in items
        ]
        self._display_map = {value: display for display, value in self._items}
        # 行记录：[key(算法值/VST路径), QCheckBox, handle, ClickFrame, kind, buttons]
        # kind: "algo"/"vst"；buttons: (设置按钮, 移除按钮) 或 None
        self._rows = []
        self._drag_idx = None
        self._drag_changed = False
        self._enable_key = enable_key

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        frame = ClickFrame(hand_cursor=False, custom_class="light-line disable")
        outer.addWidget(frame)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        if title:
            t = QLabel(title)
            t.setProperty("class", "line_title")
            t.setContentsMargins(5, 4, 5, 4)
            frame_layout.addWidget(t)

        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        frame_layout.addLayout(self.list_layout)

        add_btn = QPushButton("+ 添加 VST3")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_vst)
        frame_layout.addWidget(add_btn)

        if config:
            chain = list(config.get(config_name) or [])
            # 确保所有算法都在链中（首次/异常时补全并写回）
            present = {el.get("name") for el in chain if el.get("type") == "algo"}
            if any(v not in present for _, v in self._items):
                for display, value in self._items:
                    if value not in present:
                        chain.append({"type": "algo", "name": value, "enabled": False})
                config.set(config_name, chain)
            for el in chain:
                if el.get("type") == "vst":
                    self._add_vst_row(el.get("path", ""))
                else:
                    self._add_algo_row(
                        self._display_map.get(el.get("name"), el.get("name")),
                        el.get("name"),
                    )
            self._order_rows(chain)
            self._apply_checks(chain)
            config.on(config_name, self._refresh)
            if enable_key:
                config.on(enable_key, self._on_enable_changed)
                self._on_enable_changed(config.get(enable_key))

        if parent_layout is not None:
            parent_layout.addWidget(self)

    # ------------------------------------------------------------------
    # 总开关视觉反馈（仅置灰，不限制交互）
    # ------------------------------------------------------------------
    def _on_enable_changed(self, value):
        if value:
            self.setGraphicsEffect(None)
        else:
            eff = QGraphicsOpacityEffect(self)
            eff.setOpacity(0.45)
            self.setGraphicsEffect(eff)

    # ------------------------------------------------------------------
    # 行构建
    # ------------------------------------------------------------------
    def _add_algo_row(self, display, name):
        row = ClickFrame(hand_cursor=False, custom_class="light-line disable item-line")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(5, 3, 5, 3)
        cb = QCheckBox(display)
        cb.stateChanged.connect(self._commit)
        handle = _DragHandle(self)
        lay.addWidget(cb)
        lay.addStretch(1)
        lay.addWidget(handle)
        self.list_layout.addWidget(row)
        self._rows.append([name, cb, handle, row, "algo", None])

    def _add_vst_row(self, path):
        if not path:
            return
        display = vst_config.get_name(path) or os.path.splitext(os.path.basename(path))[0]
        row = ClickFrame(hand_cursor=False, custom_class="light-line disable item-line")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(5, 3, 5, 3)
        cb = QCheckBox(display)
        cb.setToolTip(path)
        cb.stateChanged.connect(self._commit)
        ui_btn = QPushButton("设置")
        ui_btn.setProperty("class", "small")
        ui_btn.setCursor(Qt.PointingHandCursor)
        ui_btn.clicked.connect(lambda: editor_manager.show_editor(self.side, path))
        rm_btn = QPushButton("移除")
        rm_btn.setProperty("class", "small")
        rm_btn.setObjectName("dangerBtn")
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.clicked.connect(lambda: self._remove_vst(path))
        handle = _DragHandle(self)
        lay.addWidget(cb)
        lay.addStretch(1)
        lay.addWidget(ui_btn)
        lay.addWidget(rm_btn)
        lay.addWidget(handle)
        self.list_layout.addWidget(row)
        self._rows.append([path, cb, handle, row, "vst", (ui_btn, rm_btn)])

    def _discard_row(self, r):
        try:
            ClickFrame._active_frames.discard(r[3])
        except Exception:
            pass
        r[3].setParent(None)
        r[3].deleteLater()

    # ------------------------------------------------------------------
    # 配置绑定（config.on 单向流）
    # ------------------------------------------------------------------
    @staticmethod
    def _row_key(r):
        return r[0]

    def _commit(self, *_):
        """按当前行序写回完整 I_chain（含未勾选行与 enabled 状态）。"""
        if not self.config:
            return
        chain = []
        for r in self._rows:
            if r[4] == "vst":
                chain.append({"type": "vst", "path": r[0], "enabled": r[1].isChecked()})
            else:
                chain.append({"type": "algo", "name": r[0], "enabled": r[1].isChecked()})
        self.config.set(self.config_name, chain)

    def _add_vst(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 VST3 插件", "", "VST3 插件 (*.vst3)")
        if not p:
            return
        chain = list(self.config.get(self.config_name) or [])
        if not any(el.get("type") == "vst" and el.get("path") == p for el in chain):
            chain.append({"type": "vst", "path": p, "enabled": True})
            self.config.set(self.config_name, chain)

    def _remove_vst(self, path):
        chain = [
            el for el in (self.config.get(self.config_name) or [])
            if not (el.get("type") == "vst" and el.get("path") == path)
        ]
        self.config.set(self.config_name, chain)

    def _refresh(self, *_):
        """config.on 回调：按链增删 VST 行、按链序重排、同步勾选。"""
        if not self.config:
            return
        chain = list(self.config.get(self.config_name) or [])
        vst_paths = {el.get("path") for el in chain if el.get("type") == "vst"}
        have = {r[0] for r in self._rows if r[4] == "vst"}
        for p in vst_paths:
            if p not in have:
                self._add_vst_row(p)
        for r in list(self._rows):
            if r[4] == "vst" and r[0] not in vst_paths:
                self._rows.remove(r)
                self._discard_row(r)
        self._order_rows(chain)
        self._apply_checks(chain)

    def _order_rows(self, chain):
        """按 I_chain 顺序重排全部行（含未勾选行，重启/刷新不置顶）。"""
        pos = {}
        for i, el in enumerate(chain):
            key = el.get("path") if el.get("type") == "vst" else el.get("name")
            pos.setdefault(key, i)
        self._rows.sort(key=lambda r: pos.get(r[0], 10**9))
        self._relayout()

    def _apply_checks(self, chain):
        enabled = {}
        for el in chain:
            key = el.get("path") if el.get("type") == "vst" else el.get("name")
            enabled[key] = el.get("enabled", True)
        for r in self._rows:
            cb = r[1]
            cb.blockSignals(True)
            cb.setChecked(enabled.get(r[0], False))
            cb.blockSignals(False)

    # ------------------------------------------------------------------
    # 拖拽排序（任意行可拖，松手统一提交，刷新不弹回）
    # ------------------------------------------------------------------
    def begin_drag(self, handle):
        self._drag_idx = next(i for i, r in enumerate(self._rows) if r[2] is handle)
        self._drag_changed = False

    def drag_move(self, handle, gpos):
        if self._drag_idx is None:
            return
        target = self._row_at_y(gpos.y())
        if target is None:
            return
        cur = next(i for i, r in enumerate(self._rows) if r[2] is handle)
        if target == cur:
            return
        self._rows[cur], self._rows[target] = self._rows[target], self._rows[cur]
        self._relayout()
        self._drag_idx = target
        self._drag_changed = True

    def end_drag(self):
        self._drag_idx = None
        if self._drag_changed:
            self._drag_changed = False
            self._commit()

    def _row_at_y(self, y):
        for i, r in enumerate(self._rows):
            top = r[3].mapToGlobal(r[3].rect().topLeft()).y()
            bottom = top + r[3].height()
            if top <= y <= bottom:
                return i
        return None

    def _relayout(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for r in self._rows:
            self.list_layout.addWidget(r[3])
