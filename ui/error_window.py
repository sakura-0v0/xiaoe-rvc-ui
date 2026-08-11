"""错误日志窗口：基于框架 MainWin 的独立副窗口。

显示 error.log 最近片段，操作按钮（刷新/复制全部/清空日志/定位文件）在窗口内。
日志区用框架多行文本组件（QTextEdit + log-area 类，只读，自带滚动），
底部「自动滚动到底部」复选框绑定 ConfigBridge.memory（内存配置，不落盘）。
报错自动打开时用 WA_ShowWithoutActivating 显示而不抢焦点；手动打开时正常激活。
"""

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
)

from xiaoe_ui import CheckEntry, ConfigBridge, MainWin, ask
from xiaoe_ui.core.singleton_mixin import SingletonMixin

import error_report


class ErrorLogWindow(MainWin, SingletonMixin):
    """错误日志窗口：全局单例（框架 SingletonMixin），只允许一个实例。"""

    def __init__(self):
        super().__init__(
            win_title="错误日志",
            scroll=False,  # 日志区自带滚动，按钮固定底部
            maxsize_btn=False,
            hide_btn=True,
            show_default=False,
        )
        self.setup_ui()  # 内部会调用 add_ui()
        self.resize(760, 520)
        self.apply_all()
        # 自动打开时显示但不抢占输入焦点
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        SingletonMixin._singleton_init(self, "error_log", only_one=True)
        self.refresh()

    def closeEvent(self, event):
        SingletonMixin._singleton_close(self)
        super().closeEvent(event)

    def add_ui(self):
        # 顶部状态行：显示行数 + 更新时间
        self.status_label = QLabel("")
        self.status_label.setProperty("class", "tip-text")
        self.content_layout.addWidget(self.status_label)

        # 日志区：框架多行文本（log-area 类），只读，自带滚动
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setProperty("class", "log-area")
        self.content_layout.addWidget(self.text, 1)

        # 自动滚动到底部：L2 复选框（CheckEntry），绑定内存配置不落盘
        self.mem_cfg = ConfigBridge.memory({"auto_scroll_bottom": True})
        auto_scroll_entry = CheckEntry(
            config=self.mem_cfg, config_name="auto_scroll_bottom"
        )

        # 底部操作栏：左侧复选框，右侧操作按钮
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.addWidget(auto_scroll_entry)
        lbl = QLabel("自动滚动到底部")
        lbl.setProperty("class", "line_title")
        row.addWidget(lbl)
        row.addStretch(1)
        for text, cb, danger in (
            ("刷新", self.refresh, False),
            ("复制全部", self._copy, False),
            ("清空日志", self._clear, True),
            ("定位文件", self._reveal, False),
        ):
            btn = QPushButton(text)
            if danger:
                btn.setObjectName("dangerBtn")
            btn.clicked.connect(cb)
            row.addWidget(btn)
        self.content_layout.addLayout(row)

    def refresh(self):
        text = error_report.read_recent()
        self.text.setPlainText(text)
        if self.mem_cfg.get("auto_scroll_bottom"):
            # setPlainText 后滚动条 maximum 要下一轮布局才更新，延迟到布局完成再滚到底
            QTimer.singleShot(0, self._scroll_to_bottom)
        count = len(text.splitlines()) if text else 0
        self.status_label.setText(
            f"显示最近 {count} 行 · 更新 {time.strftime('%H:%M:%S')}"
        )

    def _scroll_to_bottom(self):
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.status_label.setText("已复制全部错误记录")

    def _clear(self):
        if ask("清空日志", "确定清空全部错误记录？此操作不可恢复。"):
            error_report.clear_log()
            self.refresh()

    def _reveal(self):
        # 打开资源管理器并默认选中 log 文件。
        # 注意：/select, 单独成参数、路径单独传，避免 subprocess 的引号转义把命令弄坏
        try:
            import subprocess
            subprocess.Popen(
                ["explorer", "/select,", os.path.normpath(error_report.LOG_PATH)]
            )
        except Exception:
            pass
