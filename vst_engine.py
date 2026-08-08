"""VST3 插件支持：VstConfig（独立配置）+ VSTEngine（链引擎）+ VstEditorManager（子进程编辑器）。

pedalboard 关键约束（冒烟测试确认）：
- bundle 目录扫描在此环境失败，加载须降级到 Contents/x86_64-win/ 下的 dll；
- 不支持 mono 输入，须 mono→stereo→mono 显式转换；
- show_editor() 只能从 Python 主线程调用 → 编辑器放子进程（vst_editor_worker.py），
  关窗后 raw_state 经状态文件回传，主进程音频链完全不受影响；
- 流式 process 必须 reset=False；状态序列化用 raw_state（bytes）。
"""

import base64
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

import torch

from ui.config import CONFIG_FILES_DIR

VST_STATES_PATH = os.path.join(CONFIG_FILES_DIR, "vst_states.json")


# ---------------------------------------------------------------------------
# 独立配置对象：插件状态与显示名，与 RVC 配置完全分离
# ---------------------------------------------------------------------------
class VstConfig:
    """vst_states.json：{path: {"state": base64, "name": ...}}，独立存储。"""

    def __init__(self, path=VST_STATES_PATH):
        self.path = path
        self.data = {"plugins": {}}
        self._lock = threading.Lock()
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf8") as f:
                d = json.load(f)
            if isinstance(d.get("plugins"), dict):
                self.data = d
        except Exception:
            self.data = {"plugins": {}}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get_state(self, path):
        e = self.data["plugins"].get(path)
        if e and e.get("state"):
            try:
                return base64.b64decode(e["state"])
            except Exception:
                return None
        return None

    def set_state(self, path, raw):
        entry = self.data["plugins"].setdefault(path, {})
        entry["state"] = base64.b64encode(raw).decode("ascii")
        self.save()

    def get_params(self, path):
        e = self.data["plugins"].get(path)
        return dict(e.get("params") or {}) if e else {}

    def set_param(self, path, name, value):
        self.data["plugins"].setdefault(path, {}).setdefault("params", {})[name] = value
        self.save()

    def set_params(self, path, params):
        self.data["plugins"].setdefault(path, {})["params"] = dict(params)
        self.save()

    def get_name(self, path):
        e = self.data["plugins"].get(path)
        return e.get("name") if e else None

    def set_name(self, path, name):
        self.data["plugins"].setdefault(path, {})["name"] = name
        self.save()


vst_config = VstConfig()


# ---------------------------------------------------------------------------
# VST3 路径解析：bundle 目录 → 实际 dll
# ---------------------------------------------------------------------------
def resolve_vst_dll(path):
    """Windows VST3 bundle 是目录（Contents/x86_64-win/*.vst3），直接返回 dll 文件路径。"""
    if os.path.isdir(path):
        base = os.path.join(path, "Contents")
        if os.path.isdir(base):
            for sub in os.listdir(base):
                cand = os.path.join(base, sub, os.path.basename(path))
                if os.path.isfile(cand) and cand.lower().endswith(".vst3"):
                    return cand
    return path


# ---------------------------------------------------------------------------
# VST 加载线程：load_plugin 必须在 JUCE 消息线程调用（首次加载的线程即消息线程）。
# 热切换/启动都在不定线程，故所有插件加载与释放投递到常驻 loader 线程串行执行。
# process 可在任意线程（reset=False 已验证）；show_editor 走子进程，与此无关。
# ---------------------------------------------------------------------------
class _VSTLoader:
    def __init__(self):
        self._q = queue.Queue()
        self._t = threading.Thread(target=self._run, daemon=True, name="vst-loader")
        self._t.start()

    def _run(self):
        while True:
            fn, res, evt = self._q.get()
            if fn is None:
                break
            try:
                res["v"] = fn()
            except Exception as e:
                res["e"] = e
            evt.set()

    def call(self, fn):
        res = {}
        evt = threading.Event()
        self._q.put((fn, res, evt))
        evt.wait()
        if "e" in res:
            raise res["e"]
        return res.get("v")


vst_loader = _VSTLoader()


# ---------------------------------------------------------------------------
# 链引擎
# ---------------------------------------------------------------------------
class VSTEngine:
    """包 pedalboard 插件，接入降噪链（__call__ 收 mono torch 块 → 同长返回）。"""

    def __init__(self, path, sr, device):
        self.path = path
        self.sr = int(sr)
        self.device = device
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.latency = 0
        dll = resolve_vst_dll(path)
        try:
            import pedalboard as pb
        except ImportError:
            raise RuntimeError("pedalboard 未安装，无法加载 VST3 插件")
        self._pb = pb
        self.plugin = pb.load_plugin(dll)
        try:
            self.name = self.plugin.name or self.name
        except Exception:
            pass
        try:
            self.latency = int(self.plugin.reported_latency_samples or 0)
        except Exception:
            self.latency = 0
        # 恢复已保存参数（参数级，raw_state 对部分插件不含实时参数，不用）
        for name, value in vst_config.get_params(path).items():
            try:
                setattr(self.plugin, name, value)
            except Exception:
                pass
        if not vst_config.get_name(path):
            try:
                vst_config.set_name(path, self.name)
            except Exception:
                pass

    def __call__(self, x):
        n = x.shape[0]
        if n == 0 or self.plugin is None:
            return x
        y = x.cpu().numpy().astype("float32")
        # mono → stereo(dup) → process → 左声道（插件多为 stereo-only）
        y2 = self.plugin.process(
            y[:, None].repeat(2, axis=1), self.sr, reset=False
        )
        return torch.from_numpy(y2[:, 0].copy()).to(self.device)

    def close(self):
        # 链实例参数从不变化（编辑器是独立子进程），不写回状态，避免覆盖编辑器保存。
        # C++ 实例析构投递到 loader 线程（避免跨线程释放）
        plugin = self.plugin
        self.plugin = None
        if plugin is not None:
            try:
                # lambda 引用 plugin → 闭包捕获，引用在 loader 线程执行后释放（C++ 析构在该线程）
                vst_loader.call(lambda: plugin is None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 编辑器管理器（子进程）
# ---------------------------------------------------------------------------
class VstEditorManager:
    """每个打开的编辑器 = 一个子进程（vst_editor_worker.py）。

    子进程内 show_editor 满足"仅主线程"约束；关窗后 raw_state 经状态文件回传，
    保存进 VstConfig 并触发 on_state_saved 回调（应用侧据此重建链使参数生效）。
    坏插件崩溃只死子进程，不影响主进程音频。
    """

    def __init__(self, on_state_saved=None, on_error=None, on_param=None):
        self._procs = {}  # (side, path) -> subprocess.Popen
        self._lock = threading.Lock()
        self.on_state_saved = on_state_saved or (lambda path: None)
        self.on_error = on_error or (lambda side, path, msg: None)
        self.on_param = on_param or (lambda side, path, name, value: None)

    def is_open(self, side, path):
        with self._lock:
            p = self._procs.get((side, path))
            return p is not None and p.poll() is None

    def show_editor(self, side, path):
        with self._lock:
            p = self._procs.get((side, path))
            if p is not None and p.poll() is None:
                return  # 已打开
        fd, state_file = tempfile.mkstemp(suffix=".json", prefix="vst_params_")
        os.close(fd)
        # 已存参数写入状态文件（json），worker 加载后逐个恢复（重开界面不再回默认）
        params = vst_config.get_params(path)
        if params:
            try:
                with open(state_file, "w", encoding="utf8") as f:
                    json.dump(params, f)
            except OSError:
                pass
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vst_editor_worker.py")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", worker, resolve_vst_dll(path), state_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            try:
                os.remove(state_file)
            except OSError:
                pass
            self.on_error(side, path, f"编辑器启动失败：{e}")
            return
        with self._lock:
            self._procs[(side, path)] = proc
        threading.Thread(
            target=self._read_params, args=(side, path, proc.stdout), daemon=True
        ).start()
        threading.Thread(
            target=self._wait_close,
            args=(side, path, proc, state_file),
            daemon=True,
        ).start()

    def _read_params(self, side, path, stream):
        """读 worker 的 PARAM 行并实时应用到链实例（对端退出即 EOF 结束）。"""
        import json

        try:
            for line in stream:
                line = line.decode("utf8", "replace").strip()
                if line.startswith("DBG "):
                    print(f"[vst:{side}] {line[4:]}", file=sys.stderr, flush=True)
                    continue
                if not line.startswith("PARAM "):
                    continue
                payload = line[len("PARAM "):]
                try:
                    item = json.loads(payload)
                except Exception:
                    continue
                for name, value in item.items():
                    print(f"[vst:{side}] param {name}={value}", file=sys.stderr, flush=True)
                    self.on_param(side, path, name, value)
        except Exception:
            pass

    def _wait_close(self, side, path, proc, state_file):
        proc.wait()
        # 读 worker 关闭时写入的全量参数并持久化（覆盖实时增量，兜底防遗漏）
        try:
            if os.path.exists(state_file):
                with open(state_file, "r", encoding="utf8") as f:
                    params = json.load(f)
                if params:
                    vst_config.set_params(path, params)
                try:
                    os.remove(state_file)
                except OSError:
                    pass
        except Exception:
            pass
        with self._lock:
            cur = self._procs.get((side, path))
            if cur is proc:
                del self._procs[(side, path)]
        if proc.returncode != 0:
            self.on_error(side, path, "插件界面进程异常退出")

    def close_editor(self, side, path):
        with self._lock:
            p = self._procs.pop((side, path), None)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def close_all(self):
        with self._lock:
            procs = list(self._procs.values())
            self._procs.clear()
        for p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass


# 模块级单例（app / 控件直接使用；回调由 app 启动时注入）
editor_manager = VstEditorManager()
