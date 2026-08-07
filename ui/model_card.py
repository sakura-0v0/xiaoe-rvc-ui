import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from xiaoe_ui import (
    ClickFrame,
    Dialog,
    ImagePicker,
    ask,
    make_line,
)
from xiaoe_ui.widgets.status_widgets import StatusImagePicker

CARD_WIDTH = 180
CARD_COVER_HEIGHT = 110
CARD_HEIGHT = 176
COVER_W = CARD_WIDTH - 20
COVER_H = CARD_COVER_HEIGHT


class ReadOnlyImagePicker(StatusImagePicker):
    """图片编辑器的只读版：不触发文件选择，点击转发为回调（供卡片切换模型）。"""

    def __init__(self, width, height, path, clicked_cb=None):
        super().__init__(width=width, height=height, path=path, on_changed=None)
        self._close_btn.hide()
        self.img_frame.on_enter(lambda: None)
        self.img_frame.on_leave(lambda: None)
        if clicked_cb:
            self.img_frame.on_left_click(clicked_cb)

    def _pick(self):
        pass


class ModelCard(ClickFrame):
    """模型卡片：只读封面图 + 名字 + 「当前」角标 + 编辑按钮。

    封面绑定该模型共享的 ConfigBridge（image 键），编辑框改图后自动同步；
    卡片本体与封面都用 ClickFrame，点击即切换模型。
    """

    clicked = Signal(str)
    edit_clicked = Signal(str)

    def __init__(self, entry, library, is_active, parent=None):
        super().__init__(default_line=True, hand_cursor=True)
        self.entry = entry
        self.mid = entry["id"]
        self.setObjectName("modelCard")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.set_selected(is_active)

        self._img_cfg = library.image_bridge(self.mid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.picker = ReadOnlyImagePicker(
            COVER_W, COVER_H,
            self._img_cfg.get("image"),
            clicked_cb=lambda: self.clicked.emit(self.mid),
        )
        self._img_cfg.value_changed.connect(self._on_img_sync)
        layout.addWidget(self.picker)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)

        self.name = QLabel(entry.get("name", ""))
        self.name.setObjectName("modelName")
        self.name.setToolTip(entry.get("name", ""))
        bottom.addWidget(self.name, 1)

        self.badge = QLabel("当前")
        self.badge.setObjectName("modelBadge")
        self.badge.setVisible(is_active)
        bottom.addWidget(self.badge)

        self.edit_btn = QPushButton("✏️")
        self.edit_btn.setProperty("class", "small")  # 使用框架 small 按钮样式
        self.edit_btn.setToolTip("编辑模型")
        self.edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.mid))
        bottom.addWidget(self.edit_btn)

        layout.addLayout(bottom)

        self.on_left_click(lambda: self.clicked.emit(self.mid))

    def _on_img_sync(self, key, val):
        if key == "image":
            self.picker.refresh(self._img_cfg.get("image"))

    def cleanup(self):
        """卡片移除前断开所有回调与 config 绑定。

        卡片内部有多个捕获 self 的 lambda（点击回调），形成 Python 循环引用，
        导致 deleteLater 删除 C++ 对象后 Python wrapper 仍存活（zombie），
        主题切换时 suspend_highlights 遍历会崩。这里全部断开并移出高亮集合。
        """
        try:
            self._img_cfg.value_changed.disconnect(self._on_img_sync)
        except (RuntimeError, TypeError):
            pass
        self.on_left_click(None)
        try:
            self.picker.img_frame.on_left_click(None)
        except (RuntimeError, TypeError):
            pass
        try:
            self.edit_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            ClickFrame._active_frames.discard(self)
        except Exception:
            pass


class AddModelCard(ClickFrame):
    """模型库末尾的「＋」导入块，与模型卡片同尺寸。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(default_line=True, hand_cursor=True)
        self.setObjectName("addCard")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        layout = QVBoxLayout(self)
        plus = QLabel("＋")
        plus.setObjectName("addPlus")
        plus.setAlignment(Qt.AlignCenter)
        layout.addWidget(plus)
        self.on_left_click(lambda: self.clicked.emit())


class AdaptiveImagePicker(ImagePicker):
    """框架 ImagePicker 的自适应版：封面图随窗口缩放，config 绑定自动同步。"""

    def __init__(self, config, config_name, default=None, callback=None,
                 parent=None, min_h=150):
        super().__init__(config, config_name, size=120, default=default,
                         callback=callback, parent=parent)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(min_h)
        self.picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 首次弹出时 resizeEvent 先于 img_frame 排好布局触发，缩放的图是旧尺寸；
        # 延迟一轮事件循环再刷新，保证弹出即正确（拖动缩放时 resizeEvent 已就位）。
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # 解除内部固定尺寸，改为随窗口自适应
        frame = self.picker.img_frame
        frame.setMinimumSize(0, 0)
        frame.setMaximumSize(16777215, 16777215)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 覆盖内部刷新为自适应缩放
        self.picker._refresh = self._adaptive_refresh

        # 修正 × 按钮位置跟随实际宽度
        def _repos():
            self.picker._close_btn.move(
                max(self.picker.img_frame.width() - 22, 0), 2
            )

        self.picker.img_frame.on_resize(_repos)
        self.picker.img_frame.on_enter(
            lambda: (_repos(), self.picker._close_btn.show()
                     if self.picker._path else None)
        )
        self.picker.img_frame.on_leave(lambda: self.picker._close_btn.hide())

        self._adaptive_refresh(self.picker.value)

    def _adaptive_refresh(self, path):
        self.picker._path = path
        w = max(40, self.picker.img_frame.width())
        h = max(40, self.picker.img_frame.height())
        if not path or not os.path.exists(path):
            # setText 会清掉旧 pixmap；不要再 setPixmap(空)，否则会顶掉文本
            self.picker._img_label.setText("未设置图片" if not path else "找不到图片")
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.picker._img_label.setText("找不到图片")
            return
        self.picker._img_label.setText("")
        self.picker._img_label.setPixmap(
            pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_timer.start(0)

    def _do_refresh(self):
        try:
            self._adaptive_refresh(self.picker.value)
        except RuntimeError:
            pass


class ModelEditDialog(Dialog):
    """模型编辑弹窗：封面图（框架编辑器）/改名/上传模型与 index/删除/↑↓ 排序。"""

    def __init__(self, parent, library, entry, on_changed=None):
        super().__init__(
            parent,
            win_title="编辑模型",
            width=440,
            height=520,
            set_fixed_size=False,  # 允许拖拽调整大小
        )
        self.library = library
        self.mid = entry["id"]
        self.on_changed = on_changed or (lambda: None)
        self.root_layout.setSpacing(8)
        self._build(entry)

    # ------------------------------------------------------------------
    def _entry(self):
        return self.library.get_entry(self.mid)

    def _build(self, entry):
        root = self.root_layout

        # 封面图：框架 ImagePicker 自适应版，config 绑定 → 卡片自动同步
        self.picker = AdaptiveImagePicker(
            self.library.image_bridge(self.mid),
            "image",
            callback=lambda p: self.on_changed(),
            min_h=150,
        )
        root.addWidget(self.picker)

        make_line(root)

        # 名字
        name_row = QHBoxLayout()
        name_lbl = QLabel("名字")
        name_lbl.setObjectName("dialogLabel")
        name_lbl.setFixedWidth(70)
        self.name_edit = QLineEdit(entry.get("name", ""))
        self.name_edit.setPlaceholderText("模型名字")
        self.name_edit.editingFinished.connect(self._commit_name)
        name_row.addWidget(name_lbl)
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        # 模型 / index 文件
        model_row, self._model_path_label = self._file_row(
            "模型文件", self.library.model_path(self.mid), self._pick_model, "替换"
        )
        root.addLayout(model_row)
        index_row, self._index_path_label = self._file_row(
            "index文件", self.library.index_path(self.mid), self._pick_index, "替换"
        )
        root.addLayout(index_row)
        if self._entry() and self._entry().get("index"):
            self._rm_index_btn = QPushButton("移除 index")
            self._rm_index_btn.clicked.connect(self._remove_index)
            root.addWidget(self._rm_index_btn)
        else:
            self._rm_index_btn = None

        make_line(root)

        # 删除在左，↑↓ 排序在右，同一行
        sort_row = QHBoxLayout()
        delete_btn = QPushButton("🗑 删除模型")
        delete_btn.setObjectName("dangerBtn")
        delete_btn.clicked.connect(self._delete)
        sort_row.addWidget(delete_btn)
        sort_row.addStretch(1)
        up = QPushButton("↑ 上移")
        up.clicked.connect(lambda: self._reorder(-1))
        down = QPushButton("↓ 下移")
        down.clicked.connect(lambda: self._reorder(1))
        sort_row.addWidget(up)
        sort_row.addWidget(down)
        root.addLayout(sort_row)

    def _file_row(self, label, path, pick_cb, btn_text):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("dialogLabel")
        lbl.setFixedWidth(70)
        # 库内保留原文件名，这里显示文件名，悬浮显示完整路径
        path_label = QLabel(os.path.basename(path) if path else "未设置")
        path_label.setObjectName("filePath")
        path_label.setToolTip(path or "")
        btn = QPushButton(btn_text)
        btn.clicked.connect(pick_cb)
        row.addWidget(lbl)
        row.addWidget(path_label, 1)
        row.addWidget(btn)
        return row, path_label

    # ------------------------------------------------------------------
    def _commit_name(self):
        entry = self._entry()
        if entry is None:
            return  # 模型可能已被删除
        name = self.name_edit.text().strip()
        if name and entry.get("name") != name:
            self.library.rename(self.mid, name)
            self.on_changed()

    def _pick_model(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择模型", "", "RVC 模型 (*.pth)")
        if p:
            self.library.replace_model_file(self.mid, p)
            self._model_path_label.setText(os.path.basename(p))
            self._model_path_label.setToolTip(p)
            # 名字若为自动模式，已被同步为 pth 文件名，刷新输入框
            new_name = self._entry().get("name")
            if new_name and new_name != self.name_edit.text():
                self.name_edit.setText(new_name)
            self.on_changed()

    def _pick_index(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 index", "", "索引 (*.index)")
        if p:
            self.library.replace_index_file(self.mid, p)
            self._index_path_label.setText(os.path.basename(p))
            self._index_path_label.setToolTip(p)
            self.on_changed()

    def _remove_index(self):
        self.library.remove_index(self.mid)
        self._index_path_label.setText("未设置")
        self._index_path_label.setToolTip("")
        if self._rm_index_btn:
            self._rm_index_btn.hide()
        self.on_changed()

    def _reorder(self, delta):
        self.library.reorder(self.mid, delta)
        self.on_changed()

    def _delete(self):
        if ask("删除模型", "确定删除该模型？文件将一并移除。"):
            self.library.remove(self.mid)
            self.on_changed()
            self.close()

    def closeEvent(self, event):
        self._commit_name()
        super().closeEvent(event)
