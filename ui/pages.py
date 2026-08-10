import os
import threading

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xiaoe_ui import (
    BottomItem,
    CheckItem,
    ComboItem,
    Dialog,
    InstantTipButton,
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
    COVER_H,
    COVER_W,
    AddChoiceDialog,
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
    悬停模型卡片时在右侧浮现 ×（删除）/📌（置顶/取消置顶）/＋（移动）
    小按钮（同框架「自定义主题预设」交互）；按住 ＋ 拖拽排序，松手持久化。
    置顶/非置顶拆成两个网格实例，各自只含本组卡片，拖拽天然物理隔离。
    """

    def __init__(self, on_delete_cb=None, on_reorder_cb=None,
                 on_pin_cb=None, pinned_group=False):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._cards = []
        self.on_delete_cb = on_delete_cb
        self.on_reorder_cb = on_reorder_cb
        self.on_pin_cb = on_pin_cb
        self.pinned_group = pinned_group

        self._corner_mid = None  # 当前悬浮角按钮所依附的模型 id
        self._drag = None

        # 角按钮：做成主窗口的顶层子控件（不随滚动内容被视口裁剪），
        # 悬停时用窗口坐标挪到对应卡片角落，并钳制在右侧内容可视区内。
        # 用框架 InstantTipButton，悬停即弹框架样式的即时 tooltip。
        self.del_btn = InstantTipButton("×")
        self.del_btn.setFixedSize(20, 20)
        self.del_btn.setProperty("class", "image-picker-close")
        self.del_btn.setToolTip("删除模型")
        self.del_btn.hide()
        self.del_btn.clicked.connect(self._on_del_clicked)

        # 置顶/取消置顶按钮：右缘中间。按网格所属组定样式与动作。
        self.pin_btn = InstantTipButton("📌")
        self.pin_btn.setFixedSize(20, 20)
        if pinned_group:
            self.pin_btn.setStyleSheet(
                "QPushButton {"
                "background: rgba(255,193,7,220); border: none;"
                "border-radius: 10px; color: white; font-size: 12px;"
                "font-weight: bold; padding: 0px;"
                "}"
                "QPushButton:hover { background: rgba(255,193,7,255); }"
            )
            self.pin_btn.setToolTip("取消置顶")
        else:
            self.pin_btn.setStyleSheet(
                "QPushButton {"
                "background: rgba(100,100,100,180); border: none;"
                "border-radius: 10px; color: white; font-size: 12px;"
                "font-weight: bold; padding: 0px;"
                "}"
                "QPushButton:hover { background: rgba(80,80,80,240); }"
            )
            self.pin_btn.setToolTip("置顶")
        self.pin_btn.hide()
        self.pin_btn.clicked.connect(self._on_pin_clicked)

        self.move_btn = InstantTipButton("＋")
        self.move_btn.setFixedSize(20, 20)
        self.move_btn.setStyleSheet(
            "QPushButton {"
            "background: rgba(100,100,100,180); border: none;"
            "border-radius: 10px; color: white; font-size: 10px;"
            "font-weight: bold; padding: 0px;"
            "}"
            "QPushButton:hover { background: rgba(80,80,80,240); }"
        )
        self.move_btn.setToolTip("拖拽排序")
        self.move_btn.hide()
        self.move_btn.pressed.connect(self._on_move_pressed)

        # 悬停轮询：卡片内含多个子控件（封面/名字/按钮），enter/leave 不可靠，改定时查光标
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._hover_tick)
        self._hover_timer.start()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def set_cards(self, cards):
        for c in self._cards:
            if hasattr(c, "cleanup"):
                c.cleanup()
            c.setParent(None)
            c.deleteLater()
        self._cards = cards
        for c in cards:
            c.setParent(self)
        self._corner_mid = None
        self._hide_corners()
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

    # ------------------------------------------------------------------
    # 悬停角按钮（同 ThemePopup editable 模式，但提升为窗口级顶层浮层）
    # ------------------------------------------------------------------
    def _win(self):
        w = self.window()
        return w if w is not None else self

    def _viewport_rect(self, win):
        """右侧内容滚动区的可视区域（窗口坐标）。"""
        w = self.parentWidget()
        while w is not None:
            if isinstance(w, QAbstractScrollArea):
                vp = w.viewport()
                return QRect(vp.mapTo(win, QPoint(0, 0)), vp.size())
            w = w.parentWidget()
        return None

    def _show_corners(self, card):
        self._corner_mid = card.mid
        win = self._win()
        if self.del_btn.parent() is not win:
            self.del_btn.setParent(win)
            self.pin_btn.setParent(win)
            self.move_btn.setParent(win)
        tl = card.mapTo(win, QPoint(0, 0))
        br = tl + QPoint(card.width(), card.height())
        half = 10  # 20px 按钮半跨卡片
        vp = self._viewport_rect(win)
        self._place_corner(self.del_btn, QPoint(br.x() - half, tl.y() - half), vp)
        self._place_corner(
            self.pin_btn, QPoint(br.x() - half, tl.y() + card.height() // 2 - half), vp,
        )
        self._place_corner(self.move_btn, QPoint(br.x() - half, br.y() - half), vp)
        self.del_btn.show()
        self.pin_btn.show()
        self.move_btn.show()
        self.del_btn.raise_()
        self.pin_btn.raise_()
        self.move_btn.raise_()

    def _place_corner(self, btn, pos, vp):
        """定位角按钮；超出滚动可视区时钳制回可视区内，保证不裁剪。"""
        if vp is not None:
            x = min(max(pos.x(), vp.left()), vp.right() - btn.width() + 1)
            y = min(max(pos.y(), vp.top()), vp.bottom() - btn.height() + 1)
            pos = QPoint(x, y)
        btn.move(pos)

    def _hide_corners(self):
        self._corner_mid = None
        self.del_btn.hide()
        self.pin_btn.hide()
        self.move_btn.hide()
        self.del_btn.hide_tip()
        self.pin_btn.hide_tip()
        self.move_btn.hide_tip()

    def _hover_tick(self):
        if self._drag is not None:
            return
        if not self.isVisible():
            self._hide_corners()
            return
        gp = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(gp):
            self._hide_corners()
            return
        # 光标在可见角按钮上 → 保持显示，不重算（按钮是窗口子控件，
        # 用局部坐标 rect() 判断：geometry() 是父窗口坐标，mapFromGlobal 是局部坐标，不能混用）
        cg = QCursor.pos()
        if self.del_btn.isVisible() and \
                self.del_btn.rect().contains(self.del_btn.mapFromGlobal(cg)):
            return
        if self.pin_btn.isVisible() and \
                self.pin_btn.rect().contains(self.pin_btn.mapFromGlobal(cg)):
            return
        if self.move_btn.isVisible() and \
                self.move_btn.rect().contains(self.move_btn.mapFromGlobal(cg)):
            return
        for c in self._cards:
            if hasattr(c, "mid") and c.isVisible() and c.geometry().contains(gp):
                if self._corner_mid != c.mid:
                    self._show_corners(c)
                return
        self._hide_corners()

    def _on_del_clicked(self):
        mid = self._corner_mid
        if mid and self.on_delete_cb:
            self.on_delete_cb(mid)

    def _on_pin_clicked(self):
        mid = self._corner_mid
        if mid and self.on_pin_cb:
            self.on_pin_cb(mid)

    def _on_move_pressed(self):
        mid = self._corner_mid
        if mid:
            self._start_drag(mid)

    # ------------------------------------------------------------------
    # 拖拽排序（同 ThemePopup）
    # ------------------------------------------------------------------
    def _start_drag(self, mid):
        card = next((c for c in self._cards
                     if hasattr(c, "mid") and c.mid == mid), None)
        if card is None or self._drag is not None:
            return
        self._hide_corners()
        self._hover_timer.stop()

        card.setEnabled(False)
        ghost = self._make_ghost(card)
        mb = self.move_btn
        br = mb.mapTo(self, QPoint(mb.width(), mb.height()))
        ghost.move(br.x() - ghost.width(), br.y() - ghost.height())
        ghost.show()

        mids = [c.mid for c in self._cards if hasattr(c, "mid")]
        self._drag = {
            "card": card,
            "mid": mid,
            "mids": mids,
            "idx": mids.index(mid),
            "changed": False,
            "ghost": ghost,
        }
        self.grabMouse()
        self.installEventFilter(self)

    def _make_ghost(self, card):
        """被拖卡片的半透明副本（封面 + 名字），右下角跟鼠标。"""
        g = QFrame(self)
        g.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        g.setStyleSheet(
            "QFrame { background: rgba(80,80,80,200); border: 1px solid"
            " rgba(255,255,255,90); border-radius: 8px; }"
        )
        eff = QGraphicsOpacityEffect(g)
        eff.setOpacity(0.85)
        g.setGraphicsEffect(eff)
        lay = QVBoxLayout(g)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        img.setFixedHeight(COVER_H)
        path = card._img_cfg.get("image")
        if path and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                img.setPixmap(pix.scaled(COVER_W, COVER_H, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
        name = QLabel(card.name.text())
        name.setAlignment(Qt.AlignCenter)
        lay.addWidget(img)
        lay.addWidget(name)
        g.raise_()
        return g

    def eventFilter(self, obj, event):
        d = self._drag
        if d is None:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.MouseMove:
            local = event.pos()
            f = d["ghost"]
            # 右下角跟鼠标，同 ThemePopup
            f.move(local.x() - f.width(), local.y() - f.height())
            center = f.geometry().center()
            new_idx = self._calc_index(center, d)
            if new_idx != d["idx"] and 0 <= new_idx < len(d["mids"]):
                mid = d["mids"].pop(d["idx"])
                d["mids"].insert(new_idx, mid)
                d["idx"] = new_idx
                d["changed"] = True
                self._reorder_cards(d["mids"])
                f.raise_()
            return True
        if event.type() == QEvent.MouseButtonRelease:
            self._finish_drag()
            return True
        return super().eventFilter(obj, event)

    def _calc_index(self, center, d):
        """命中检测：ghost 中心落在哪张模型卡片上，返回其索引。"""
        for c in self._cards:
            if not hasattr(c, "mid") or c is d["card"]:
                continue
            if c.geometry().contains(center):
                return d["mids"].index(c.mid)
        return d["idx"]

    def _reorder_cards(self, mids):
        """按新顺序重排现有卡片 widget（＋导入块恒居末），就地换位不重建。"""
        by_mid = {c.mid: c for c in self._cards if hasattr(c, "mid")}
        ordered = [by_mid[m] for m in mids]
        tail = [c for c in self._cards if not hasattr(c, "mid")]
        self._cards = ordered + tail
        self._relayout()

    def _finish_drag(self):
        d = self._drag
        if d is None:
            return
        self.releaseMouse()
        self.removeEventFilter(self)
        d["ghost"].deleteLater()
        d["card"].setEnabled(True)
        changed = d["changed"]
        mids = d["mids"]
        self._drag = None
        self._hover_timer.start()
        if changed and self.on_reorder_cb:
            self.on_reorder_cb(mids)


class _BatchProgressDialog(Dialog):
    """批量导入进度窗：实时显示扫描 / 导入状态；关闭即中止导入。"""

    def __init__(self, parent):
        super().__init__(
            parent,
            win_title="批量添加",
            width=380,
            height=180,
            set_fixed_size=False,
            modal=True,
        )
        self.on_close = None
        self.status_label = QLabel("准备中…")
        self.status_label.setWordWrap(True)
        self.root_layout.addWidget(self.status_label)

    def set_status(self, text):
        self.status_label.setText(text)

    def closeEvent(self, event):
        if self.on_close:
            self.on_close()
        super().closeEvent(event)


class _BatchImportWorker(QObject):
    """后台批量导入：扫描 → 请求重名决策 → 逐个导入，全程发进度信号。

    finished 返回值：>=0 完成并返回导入数量；-1 被中止/扫描失败。
    """

    scanned = Signal(list, list)   # (pth 文件名列表, 重名列表)
    status = Signal(str)
    finished = Signal(int)         # 成功导入数量；-1=中止

    def __init__(self, folder, existing, library):
        super().__init__()
        self.folder = folder
        self.existing = set(existing)
        self.library = library
        self.skip = False
        self._abort = threading.Event()
        self._decided = threading.Event()

    def run(self):
        f = self.folder
        self.status.emit(f"正在扫描文件夹：\n{f}")
        pths = []
        try:
            names = os.listdir(f)
        except Exception:
            self.finished.emit(-1)
            return
        for name in names:
            if self._abort.is_set():
                self.finished.emit(-1)
                return
            if name.lower().endswith(".pth") and os.path.isfile(os.path.join(f, name)):
                pths.append(name)
                self.status.emit(
                    f"正在扫描文件夹：\n{f}\n已收集到 {len(pths)} 个模型"
                )
        pths.sort()
        collided = [os.path.splitext(p)[0] for p in pths
                    if os.path.splitext(p)[0] in self.existing]
        self.scanned.emit(pths, collided)
        self._decided.wait()  # 主线程完成重名决策后放行
        if self._abort.is_set():
            self.finished.emit(-1)
            return
        if not pths:
            self.finished.emit(0)
            return
        imported = 0
        existing = set(self.existing)
        total = len(pths)
        for i, p in enumerate(pths, 1):
            if self._abort.is_set():
                self.finished.emit(-1)
                return
            base = os.path.splitext(p)[0]
            if self.skip and base in existing:
                continue
            name = base
            if base in existing:
                n = 1
                while f"{base} ({n})" in existing:
                    n += 1
                name = f"{base} ({n})"
                existing.add(name)
            else:
                existing.add(base)
            idx = os.path.join(f, base + ".index")
            if not os.path.isfile(idx):
                idx = None
            self.status.emit(f"正在导入 {i}/{total}：{name}")
            self.library.import_model(os.path.join(f, p), idx, name=name)
            imported += 1
        self.finished.emit(imported)


class ModelPage:
    """模型库页：上网格置顶组 + 分割线 + 下网格非置顶组。

    置顶组初始为空时不占空间；存在置顶时占用若干行并自动换行，
    与下网格之间显示一条分割线。排序被两个网格物理隔离。
    """

    def __init__(self, container, library, on_activate=None, on_edit=None,
                 on_delete=None):
        self.container = container  # 页面内容布局
        self.library = library
        self.on_activate = on_activate
        self.on_edit = on_edit
        self.on_delete = on_delete
        self._batch_worker = None
        self._batch_dialog = None

        self.pinned_grid = _GridWidget(
            on_delete_cb=self._on_delete,
            on_reorder_cb=lambda mids: self._on_reorder(mids, pinned=True),
            on_pin_cb=self._on_pin,
            pinned_group=True,
        )
        self.divider = QFrame()
        self.divider.setFrameStyle(QFrame.HLine)
        self.divider.setProperty("class", "ligh-line")
        self.divider.setVisible(False)
        self.unpinned_grid = _GridWidget(
            on_delete_cb=self._on_delete,
            on_reorder_cb=lambda mids: self._on_reorder(mids, pinned=False),
            on_pin_cb=self._on_pin,
            pinned_group=False,
        )
        container.addWidget(self.pinned_grid)
        container.addWidget(self.divider)
        container.addWidget(self.unpinned_grid)
        self.refresh()

    def _make_card(self, e, active):
        card = ModelCard(e, self.library, e["id"] == active)
        card.clicked.connect(self._on_card_clicked)
        card.edit_clicked.connect(self._on_card_edit)
        return card

    def refresh(self):
        active = self.library.active_id()
        self.pinned_grid.set_cards(
            [self._make_card(e, active) for e in self.library.pinned_entries()]
        )
        unpinned = self.library.unpinned_entries()
        cards = [self._make_card(e, active) for e in unpinned]
        # 下网格末尾放「＋」添加块（点击弹「单个 / 批量」选择）
        add_card = AddModelCard()
        add_card.clicked.connect(self._import)
        cards.append(add_card)
        self.unpinned_grid.set_cards(cards)
        # 置顶组为空 → 上网格与分割线都不占空间
        has_pinned = bool(self.library.pinned_entries())
        self.pinned_grid.setVisible(has_pinned)
        self.divider.setVisible(has_pinned)

    def _on_card_clicked(self, mid):
        if self.on_activate:
            self.on_activate(mid)

    def _on_card_edit(self, mid):
        if self.on_edit:
            self.on_edit(mid)

    def _on_delete(self, mid):
        entry = self.library.get_entry(mid)
        name = entry["name"] if entry else mid
        if ask("删除模型", f"确定删除模型「{name}」？文件将一并移除。"):
            self.library.remove(mid)
            if self.on_delete:
                self.on_delete()
            else:
                self.refresh()

    def _on_reorder(self, mids, pinned):
        self.library.set_order(mids, pinned)
        self.refresh()

    def _on_pin(self, mid):
        e = self.library.get_entry(mid)
        if not e:
            return
        if self.library.is_pinned(mid):
            self.library.unpin(mid)
        else:
            self.library.pin(mid)
        self.refresh()

    def _import(self):
        # 弹「添加单个 / 批量添加」选择
        dlg = AddChoiceDialog(self.unpinned_grid.window())
        if not dlg.exec():
            return
        if dlg.choice == "batch":
            self._batch_import()
            return
        # 添加单个：先建空块，再打开编辑页上传
        entry = self.library.create_entry()
        self.refresh()
        if self.on_edit:
            self.on_edit(entry["id"])

    def _batch_import(self):
        """批量添加：选文件夹 → 后台扫描/导入（进度窗实时显示，关闭即中止）。"""
        folder = QFileDialog.getExistingDirectory(
            self.unpinned_grid.window(), "选择模型文件夹", ""
        )
        if not folder:
            return
        existing = set(e["name"] for e in self.library.entries())
        worker = _BatchImportWorker(folder, existing, self.library)
        dlg = _BatchProgressDialog(self.unpinned_grid.window())
        dlg.on_close = worker._abort.set  # 关闭对话框 → 中止导入
        worker.status.connect(dlg.set_status)
        worker.scanned.connect(self._on_batch_scanned)
        worker.finished.connect(lambda n: self._on_batch_finished(dlg, n))
        self._batch_worker = worker
        self._batch_dialog = dlg
        dlg.show()
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_batch_scanned(self, pths, collided):
        w = self._batch_worker
        if collided:
            shown = "\n".join(f"· {n}" for n in collided[:8])
            if len(collided) > 8:
                shown += f"\n… 共 {len(collided)} 个"
            # ask 返回 True=跳过重名；False=全部保留自动加序号
            w.skip = ask(
                "重名处理",
                f"检测到 {len(collided)} 个模型与现有列表重名：\n{shown}\n\n"
                "「跳过重名」：这些模型不导入；\n"
                "「全部保留」：全部导入，重名的自动加序号。",
                yes_text="跳过重名",
                no_text="全部保留",
            )
        else:
            w.skip = False
        w._decided.set()

    def _on_batch_finished(self, dlg, count):
        dlg.close()
        self._batch_worker = None
        self._batch_dialog = None
        self.refresh()
        if count < 0:
            info("批量添加", "已取消导入。")
        elif count:
            info("批量添加", f"成功导入 {count} 个模型。")
        else:
            info("批量添加", "没有导入任何模型。")


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

    # 默认 index（全局兜底）：模型无自带 index 时使用，置底 + 分割线
    make_line(container, bold=True)
    _default_index_row(container, config)


def _default_index_row(container, config):
    """「默认 index」文件行：模型没有自带 index 时使用的全局兜底 index。"""
    from PySide6.QtWidgets import QWidget

    def _label():
        path = config.get("default_index") or ""
        lbl = QLabel(os.path.basename(path) if path else "未设置")
        lbl.setToolTip(path or "")
        return lbl

    path_lbl = _label()
    pick_btn = QPushButton("选择")
    clear_btn = QPushButton("清除")

    def _pick():
        p, _ = QFileDialog.getOpenFileName(
            None, "选择默认 index", "", "Index (*.index)"
        )
        if p:
            config.set("default_index", p)
            path_lbl.setText(os.path.basename(p))
            path_lbl.setToolTip(p)

    def _clear():
        config.set("default_index", "")
        path_lbl.setText("未设置")
        path_lbl.setToolTip("")

    pick_btn.clicked.connect(_pick)
    clear_btn.clicked.connect(_clear)

    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(path_lbl, 1)
    row.addWidget(pick_btn)
    row.addWidget(clear_btn)
    container.addWidget(make_form_row("默认 index", holder))


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
