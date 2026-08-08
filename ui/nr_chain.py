"""降噪链排序控件 —— 框架 CheckItem 的链式扩展（可提炼进 xiaoe_ui 框架）。

块容器用 ClickFrame(light-line disable) 自带细线框线；每行复用 CheckItem 行结构
（ClickFrame item-line + QCheckBox）。配置项为 list（顺序即执行顺序）。

模型：算法字符串（静态行）与 VST 插件（动态行）混排。
- 勾选链 config_name（如 I_nr_chain）：只含启用的元素，顺序即执行顺序；
- 插件列表 vst_plugins_name（如 I_vst_plugins）：所有已添加的插件路径，决定行存在。
  取消勾选只移出勾选链（行保留），「移除」按钮才从插件列表删除。

绑定遵循框架 ConfigBridge 单向流：交互只改配置（config.set），一切刷新由
config.on 驱动；反向同步用 blockSignals 防回环。行序由拖拽维护（刷新不弹回）。
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
    """一块降噪链：细线框容器 + 每行「复选框(启用) + 名称 + 操作/拖拽手柄」。

    items: [(显示名, 配置值), ...] 或 [字符串, ...]（显示名=配置值）。
    side: "I"（输入）/ "O"（输出），供编辑器子进程区分。
    """

    def __init__(self, title, items, config, config_name, vst_plugins_name,
                 side="I", enable_key=None, parent_layout=None):
        super().__init__()
        self.config = config
        self.config_name = config_name
        self.vst_plugins_name = vst_plugins_name
        self.side = side
        self._items = [
            (it, it) if isinstance(it, str) else (it[0], it[1]) for it in items
        ]
        # 行记录：[value(字符串或dict), QCheckBox, handle, ClickFrame, kind, buttons]
        # kind: "algo"/"vst"；buttons: (界面按钮, 移除按钮) 或 None
        self._rows = []
        self._drag_idx = None
        self._drag_changed = False
        # 总开关：关闭时整块半透明置灰（仅视觉，不限制交互）
        self._enable_key = enable_key

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 块容器：disable + 细线 ClickFrame，自带框线
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

        for display, value in self._items:
            self._add_algo_row(display, value)

        add_btn = QPushButton("+ 添加 VST3")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_vst)
        frame_layout.addWidget(add_btn)

        if config:
            for path in config.get(vst_plugins_name) or []:
                if path:
                    self._add_vst_row(path)
            chain = list(config.get(config_name) or [])
            self._order_rows(chain)
            self._apply_checks(chain)
            config.on(config_name, self._refresh)
            config.on(vst_plugins_name, self._refresh)
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
    def _add_algo_row(self, display, value):
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
        self._rows.append([value, cb, handle, row, "algo", None])

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
        rm_btn.setObjectName("dangerBtn")  # 红色（项目 #dangerBtn 样式）
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.clicked.connect(lambda: self._remove_vst(path))
        handle = _DragHandle(self)
        lay.addWidget(cb)
        lay.addStretch(1)
        lay.addWidget(ui_btn)
        lay.addWidget(rm_btn)
        lay.addWidget(handle)
        self.list_layout.addWidget(row)
        self._rows.append([{"type": "vst", "path": path}, cb, handle, row, "vst", (ui_btn, rm_btn)])

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
    def _in_chain(r, chain):
        if r[4] == "vst":
            return any(
                isinstance(el, dict) and el.get("path") == r[0]["path"]
                for el in chain
            )
        return r[0] in chain

    def _commit(self, *_):
        if not self.config:
            return
        chain = [r[0] for r in self._rows if r[1].isChecked()]
        self.config.set(self.config_name, chain)

    def _add_vst(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 VST3 插件", "", "VST3 插件 (*.vst3)")
        if not p:
            return
        cfg = self.config
        plugs = list(cfg.get(self.vst_plugins_name) or [])
        if p not in plugs:
            plugs.append(p)
            cfg.set(self.vst_plugins_name, plugs)  # 触发 _refresh 增行
        chain = list(cfg.get(self.config_name) or [])
        chain.append({"type": "vst", "path": p})
        cfg.set(self.config_name, chain)

    def _remove_vst(self, path):
        cfg = self.config
        cfg.set(self.vst_plugins_name,
                [x for x in (cfg.get(self.vst_plugins_name) or []) if x != path])
        cfg.set(self.config_name,
                [el for el in (cfg.get(self.config_name) or [])
                 if not (isinstance(el, dict) and el.get("path") == path)])

    def _refresh(self, *_):
        """config.on 回调：按插件列表增删 VST 行、同步勾选；不重排行序（拖拽不弹回）。"""
        if not self.config:
            return
        chain = list(self.config.get(self.config_name) or [])
        vst_paths = [p for p in (self.config.get(self.vst_plugins_name) or []) if p]
        have = {r[0]["path"] for r in self._rows if r[4] == "vst"}
        for p in vst_paths:
            if p not in have:
                self._add_vst_row(p)
        for r in list(self._rows):
            if r[4] == "vst" and r[0]["path"] not in vst_paths:
                self._rows.remove(r)
                self._discard_row(r)
        self._apply_checks(chain)
        self._relayout()

    def _order_rows(self, chain):
        """构造时按配置链重排一次：勾选行按链序在前，未勾选行保持原序在后。"""
        ordered = []
        rest = []
        for r in self._rows:
            (ordered if self._in_chain(r, chain) else rest).append(r)
        pos = {}
        for i, el in enumerate(chain):
            key = el if isinstance(el, str) else el.get("path")
            pos.setdefault(key, i)
        ordered.sort(key=lambda r: pos.get(r[0] if r[4] == "algo" else r[0]["path"], 10**9))
        self._rows = ordered + rest
        self._relayout()

    def _apply_checks(self, chain):
        for r in self._rows:
            cb = r[1]
            cb.blockSignals(True)
            cb.setChecked(self._in_chain(r, chain))
            cb.blockSignals(False)

    # ------------------------------------------------------------------
    # 拖拽排序（任意行可拖，每次交换即提交，刷新不弹回）
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
        self._relayout()  # 本地重排，视觉即时
        self._drag_idx = target
        self._drag_changed = True  # 拖拽中不提交，松手统一生效（避免反复重载 VST）

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
