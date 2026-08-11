"""错误记录：统一写入 error.log，并提供全局异常兜底。

所有报错（VST3、引擎、批量导入、未捕获异常等）都走 log_error，
记录带时间戳 + 上下文 + 完整 traceback；写完后回调已注册的 handler，
由应用侧决定是否自动打开「错误日志」窗口。线程安全，不阻塞调用方。
"""

import os
import sys
import threading
import time
import traceback

XIAOE_DIR = os.path.dirname(os.path.abspath(__file__))
# 放在 config_files 下：安装器保留该目录，跨版本存续，利于诊断
LOG_PATH = os.path.join(XIAOE_DIR, "config_files", "error.log")
MAX_SIZE = 512 * 1024   # 超过上限截断，保留尾部
KEEP_LINES = 2000
RECENT_LINES = 200

_lock = threading.Lock()
_handler = None  # callable(context, message)，在写入日志的调用线程内触发


def set_error_handler(cb):
    global _handler
    _handler = cb


def _format_exc(exc):
    if exc is None:
        return ""
    try:
        if isinstance(exc, tuple) and len(exc) == 3:
            return "".join(traceback.format_exception(*exc))
        if isinstance(exc, BaseException):
            return "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
    except Exception:
        pass
    return ""


def log_error(context, message="", exc=None, notify=True):
    """记录错误；notify=False 只写日志、不触发错误窗（如启动标记等非错误信息）。"""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{ts}] [{context}] {message or ''}"]
        tb = _format_exc(exc)
        if tb:
            lines.append(tb.rstrip("\n"))
        with _lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n---\n")
            _maybe_cap()
    except Exception:
        pass
    if not notify:
        return
    h = _handler
    if h is not None:
        try:
            h(context, message)
        except Exception:
            pass


def _maybe_cap():
    try:
        if os.path.getsize(LOG_PATH) <= MAX_SIZE:
            return
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) > KEEP_LINES:
            lines = lines[-KEEP_LINES:]
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def read_recent(lines=RECENT_LINES):
    try:
        if not os.path.exists(LOG_PATH):
            return ""
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            all_lines = f.read().splitlines()
        return "\n".join(all_lines[-lines:])
    except Exception:
        return ""


def clear_log():
    with _lock:
        try:
            if os.path.exists(LOG_PATH):
                os.remove(LOG_PATH)
        except Exception:
            pass


def install_global_hooks():
    """兜住主线程/后台线程的未捕获异常，全部写入日志。"""

    def _hook(exc_type, exc_value, exc_tb):
        log_error(
            "未捕获异常",
            f"{exc_type.__name__}: {exc_value}",
            (exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _hook

    def _thread_hook(args):
        log_error(
            f"后台线程异常: {args.thread.name}",
            f"{args.exc_type.__name__}: {args.exc_value}",
            (args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook
