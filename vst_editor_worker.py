"""VST3 编辑器子进程：加载插件 → 恢复已存状态 → show_editor（阻塞至关窗）→ 状态写回文件。

由 vst_engine.VstEditorManager 以子进程方式启动。
show_editor 只能在 Python 主线程调用——本进程的"主线程"即为此处。
状态文件（state_file）同时作为输入（已存参数 json）与输出（关闭后保存）。

JUCE 编辑器窗口默认出现在主屏左上角（标题栏被遮挡）。用 SetWinEventHook
监听窗口显示事件（事件驱动、精确匹配本进程窗口）移到屏幕中央，2 秒后单次
枚举兜底（覆盖极端情况下 hook 未命中的情况）。
"""

import base64  # noqa: F401  (保留导入，编辑器复用)
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

_EVENT_OBJECT_SHOW = 0x8002
_WINEVENT_OUTOFCONTEXT = 0x0000
_WINEPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,   # event
    wintypes.HWND,    # hwnd
    wintypes.LONG,    # idObject
    wintypes.LONG,    # idChild
    wintypes.DWORD,   # idEventThread
    wintypes.DWORD,   # dwmsEventTime
)


def _install_center_hook():
    """监听窗口显示事件，本进程新窗口出现即居中（一次性，事件驱动非轮询）。"""
    user32 = ctypes.windll.user32
    ctx = {"done": False}

    def _cb(_hook, _event, hwnd, _obj, _child, _tid, _ms):
        if ctx.get("done"):
            return
        # 只处理顶层窗口（EVENT_OBJECT_SHOW 对子窗口也触发，移动子控件会错位）
        if user32.GetAncestor(hwnd, 2) != hwnd:  # GA_ROOT
            return
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != os.getpid() or not user32.IsWindowVisible(hwnd):
            return
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        user32.MoveWindow(
            hwnd, max((sw - w) // 2, 0), max((sh - h) // 2, 0), w, h, True
        )
        ctx["done"] = True
        try:
            user32.UnhookWinEvent(ctx.get("hook"))
        except Exception:
            pass

    ctx["cb"] = _WINEPROC(_cb)  # 保持引用，防回调被 GC
    ctx["hook"] = user32.SetWinEventHook(
        _EVENT_OBJECT_SHOW, _EVENT_OBJECT_SHOW, None, ctx["cb"],
        0, 0, _WINEVENT_OUTOFCONTEXT,
    )
    return ctx


def _center_once(ctx, delay):
    """兜底：延迟后单次查找本进程的可见窗口并居中（hook 已命中则跳过）。"""
    user32 = ctypes.windll.user32
    time.sleep(delay)
    if ctx.get("done"):
        return
    try:
        found = []
        PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        proc = PROC(
            lambda hwnd, _lp: (found.append(hwnd) or True)
        )
        user32.EnumWindows(proc, 0)
        for hwnd in found:
            # 只处理顶层窗口
            if user32.GetAncestor(hwnd, 2) != hwnd:
                continue
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value != os.getpid() or not user32.IsWindowVisible(hwnd):
                continue
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            user32.MoveWindow(
                hwnd, max((sw - w) // 2, 0), max((sh - h) // 2, 0), w, h, True
            )
            return
    except Exception:
        pass


def _read_params(state_file):
    import json

    try:
        with open(state_file, "r", encoding="utf8") as f:
            return json.load(f)
    except Exception:
        return None


def _apply_params(plugin, params):
    if not params:
        return
    for name, value in params.items():
        try:
            setattr(plugin, name, value)
        except Exception:
            pass


def _write_all_params(plugin, state_file):
    """关闭前把全部参数写入状态文件（全量快照，主进程据此持久化）。"""
    import json

    try:
        allp = {k: getattr(plugin, k) for k in plugin.parameters}
        with open(state_file, "w", encoding="utf8") as f:
            json.dump(allp, f)
    except Exception:
        pass


def _param_loop(plugin):
    """轮询插件参数变化并输出 PARAM <json> 行，主进程据此实时应用到音频链实例。

    plugin.parameters 的值是 AudioProcessorParameter 对象（不可序列化），
    故用 getattr(plugin, name) 读实际数值比较。
    """
    import json

    try:
        keys = list(plugin.parameters)
        print(f"DBG paramloop keys={len(keys)}", flush=True)
        last = {k: getattr(plugin, k) for k in keys}
        print("DBG paramloop initial snapshot ok", flush=True)
    except Exception as e:
        print(f"DBG paramloop init fail: {e}", flush=True)
        return
    while True:
        time.sleep(0.25)
        try:
            cur = {k: getattr(plugin, k) for k in keys}
        except Exception as e:
            print(f"DBG paramloop read fail: {e}", flush=True)
            return
        for k in cur:
            if k not in last or last[k] != cur[k]:
                try:
                    print(f"PARAM {json.dumps({k: cur[k]})}", flush=True)
                except Exception:
                    pass
        last = cur


def main():
    path, state_file = sys.argv[1], sys.argv[2]
    import pedalboard as pb

    # 事件驱动居中（主方案）+ 2 秒枚举兜底
    ctx = _install_center_hook()
    threading.Thread(target=_center_once, args=(ctx, 2.0), daemon=True).start()

    plugin = pb.load_plugin(path)
    # 恢复上次保存的参数（worker 是独立实例，参数经状态文件 json 传递）
    _apply_params(plugin, _read_params(state_file))
    # 实时参数同步线程（stdout → 主进程）
    threading.Thread(target=_param_loop, args=(plugin,), daemon=True).start()
    plugin.show_editor()  # 阻塞直到窗口关闭
    _write_all_params(plugin, state_file)
    sys.exit(0)


if __name__ == "__main__":
    main()
