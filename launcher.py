"""启动器（由 run.vbs 以 pythonw 无窗口调用）。

职责：依赖检查 → 缺失时弹窗询问并自动安装（pip 用独立控制台窗口显示进度）
→ 启动 main.py。所有错误用 Windows 弹窗提示，避免被隐藏窗口淹没。
"""

import ctypes
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RVC_ROOT = os.path.dirname(SCRIPT_DIR)
PYEXE = os.path.join(RVC_ROOT, "runtime", "python.exe")
PYWEXE = os.path.join(RVC_ROOT, "runtime", "pythonw.exe")
MAIN = os.path.join(SCRIPT_DIR, "main.py")
REQ = os.path.join(SCRIPT_DIR, "requirements.txt")
WHL = os.path.join(SCRIPT_DIR, "xiaoe_ui-1.4.4-py3-none-any.whl")
DEPS = ["xiaoe_ui", "PySide6", "win32com", "pyrnnoise", "pedalboard"]

_MB_OK = 0x0
_MB_YESNO = 0x4
_MB_ICONINFO = 0x40
_MB_ICONERROR = 0x10


def msgbox(text, title, flags=_MB_OK | _MB_ICONINFO):
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def check_deps():
    try:
        return subprocess.call([PYEXE, "-c", "import " + ", ".join(DEPS)]) == 0
    except Exception:
        return False


def _pip_visible(args):
    """在新控制台窗口里跑 pip，让安装进度可见；返回退出码。"""
    try:
        proc = subprocess.Popen(
            [PYEXE, "-m", "pip", "--disable-pip-version-check"] + args,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        proc.wait()
        return proc.returncode
    except Exception:
        return -1


def install_deps():
    if not os.path.exists(PYEXE):
        msgbox(f"未找到 RVC 运行环境：\n{PYEXE}\n请确认已解压原版 RVC 且目录结构正确。",
               "启动失败", _MB_OK | _MB_ICONERROR)
        return False
    if _pip_visible(["install", "-r", REQ]) != 0:
        return False
    if os.path.exists(WHL):
        return _pip_visible(["install", WHL]) == 0
    return True


def main():
    try:
        if not check_deps():
            if msgbox("缺少依赖（首次运行需联网安装 PySide6 / xiaoe_ui / pedalboard 等）。\n"
                      "是否现在自动安装？（安装进度会弹出窗口显示）",
                      "xiaoe_rvc_ui", _MB_YESNO | _MB_ICONINFO) != 6:  # IDYES
                return
            if not install_deps():
                msgbox("依赖安装失败，请检查网络后重试，或双击 install.bat 手动安装。",
                       "安装失败", _MB_OK | _MB_ICONERROR)
                return
        subprocess.Popen([PYWEXE, "-I", MAIN], cwd=RVC_ROOT)
    except Exception as e:
        msgbox(f"启动失败：{e}", "错误", _MB_OK | _MB_ICONERROR)


if __name__ == "__main__":
    main()
