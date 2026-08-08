import json
import os
import shutil
import uuid

from xiaoe_ui import ConfigBridge

# ui/config.py 的父目录是 xiaoe_rvc_ui
XIAOE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RVC_ROOT = os.path.dirname(XIAOE_DIR)

# 配置文件统一放在 xiaoe_rvc_ui/config_files/ 下
CONFIG_FILES_DIR = os.path.join(XIAOE_DIR, "config_files")
CONFIG_PATH = os.path.join(CONFIG_FILES_DIR, "config.json")
MODELS_DIR = os.path.join(XIAOE_DIR, "models")
LIBRARY_PATH = os.path.join(MODELS_DIR, "library.json")
THEME_CONFIG_PATH = os.path.join(CONFIG_FILES_DIR, "theme_config.json")

# 原版 RVC 的配置（仅首次无配置时读取，绝不写入）
LEGACY_CONFIG_PATH = os.path.join(
    os.path.dirname(XIAOE_DIR), "configs", "config.json"
)

# config.json 的键 → 引擎参数对象的属性名（两者有命名差异的项）
CONFIG_TO_PARAMS = {
    "sg_wasapi_exclusive": "wasapi_exclusive",
    "crossfade_length": "crossfade_time",
}

# 内置降噪算法（配置值）
ALGORITHMS = ["TorchGate", "RNNoise", "DTLN"]

# 原 realtime_gui.py 的 config.json schema 默认值
RVC_CONFIG_DEFAULTS = {
    "pth_path": "",
    "index_path": "",
    "sg_hostapi": "",
    "sg_wasapi_exclusive": False,
    "sg_input_device": "",
    "sg_output_device": "",
    "sr_type": "sr_model",
    "threhold": -60,
    "pitch": 0,
    "formant": 0.0,
    "index_rate": 0,
    "rms_mix_rate": 0,
    "block_time": 0.25,
    "crossfade_length": 0.05,
    "extra_time": 2.5,
    "f0method": "rmvpe",
    "I_noise_reduce": False,
    "O_noise_reduce": False,
    # 处理链（顺序即执行顺序，空=该侧不处理）。统一列表：
    # 元素为 {"type":"algo","name":"RNNoise","enabled":true} 或 {"type":"vst","path":...,"enabled":true}，
    # 列表顺序=全部行顺序（含未勾选），enabled=是否启用。一个列表表达顺序/启用/插件存在。
    "I_chain": [],
    "O_chain": [],
    # 转换模式：输入监听 / 输出变声（互斥，配置双绑）
    "im": False,
    "vc": True,
    # 通用设置
    "notify_show": True,   # 通知显示
    "start_hidden": False,  # 启动隐藏
    "auto_vc": False,      # 自动变声
}


class Params:
    """引擎参数对象，字段对应原 realtime_gui.GUIConfig。"""

    def __init__(self):
        self.pth_path = ""
        self.index_path = ""
        self.pitch = 0
        self.formant = 0.0
        self.sr_type = "sr_model"
        self.block_time = 0.25
        self.threhold = -60
        self.crossfade_time = 0.05
        self.extra_time = 2.5
        self.I_noise_reduce = False
        self.O_noise_reduce = False
        # 处理链：统一列表（元素 {"type":"algo"/"vst", ..., "enabled":bool}）
        self.I_chain = []
        self.O_chain = []
        self.rms_mix_rate = 0.0
        self.index_rate = 0.0
        self.f0method = "rmvpe"
        self.sg_hostapi = ""
        self.wasapi_exclusive = False
        self.sg_input_device = ""
        self.sg_output_device = ""
        # 以下为运行时字段，不持久化
        self.samplerate = 0
        self.channels = 0


class RvcConfigManager:
    """业务配置：加载/保存 RVC 的 configs/config.json，参数一变即写盘。"""

    def __init__(self, defaults, params, path):
        self._def = dict(defaults)
        self._d = dict(defaults)
        self.params = params
        self.path = path
        self.load()

    # ---- ConfigBridge 接口 ----
    def configget(self, key):
        return self._d.get(key, self._def.get(key))

    def configset(self, key, value):
        if self._d.get(key) == value:
            return
        self._d[key] = value
        self._sync_params(key, value)
        self.save()

    def configreset(self, key):
        self._d[key] = self._def[key]
        self._sync_params(key, self._def[key])
        self.save()

    # ---- 内部 ----
    def _sync_params(self, key, value):
        attr = CONFIG_TO_PARAMS.get(key, key)
        if hasattr(self.params, attr):
            setattr(self.params, attr, value)

    def load(self):
        data = None
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf8") as f:
                    data = json.load(f)
            except Exception:
                data = None
        if data is None:
            data = self._load_legacy()  # 首次/损坏：从原版 RVC 配置导入
        if not isinstance(data, dict):
            data = {}  # 非 dict 一律当失败处理，退回默认值
        for k, v in data.items():
            if k in self._def:
                self._d[k] = v
                self._sync_params(k, v)
        # 旧链配置（勾选链/插件列表/行序）→ 统一 I_chain 迁移（优先，保留已勾选项）
        for chain_key, vst_key, order_key, new_key in (
            ("I_nr_chain", "I_vst_plugins", "I_chain_order", "I_chain"),
            ("O_nr_chain", "O_vst_plugins", "O_chain_order", "O_chain"),
        ):
            if not self._d.get(new_key) and (data.get(chain_key) or data.get(vst_key)):
                self._d[new_key] = self._migrate_chain(
                    data.get(chain_key), data.get(vst_key), data.get(order_key)
                )
                self._sync_params(new_key, self._d[new_key])
        # 旧版降噪开关（bool）→ 兜底迁移：无旧链数据时开关开着默认给 TorchGate
        for bool_key, chain_key in (
            ("I_noise_reduce", "I_chain"),
            ("O_noise_reduce", "O_chain"),
        ):
            if not self._d.get(chain_key) and bool_key in data:
                self._d[chain_key] = (
                    [{"type": "algo", "name": "TorchGate", "enabled": True}]
                    if data.get(bool_key) else []
                )
                self._sync_params(chain_key, self._d[chain_key])
        # 最终兜底：新用户无任何数据 → 全部算法未勾选
        for new_key in ("I_chain", "O_chain"):
            if not self._d.get(new_key):
                self._d[new_key] = self._migrate_chain(None, None, None)
                self._sync_params(new_key, self._d[new_key])
        self.save()

    @staticmethod
    def _migrate_chain(chain, plugins, order):
        """旧链配置合并生成统一列表：勾选元素 → 未勾选插件 → 未勾选算法。"""
        result = []
        keys = set()

        def add(kind, key, enabled):
            if key in keys:
                return
            keys.add(key)
            result.append(
                {"type": kind, **({"name": key} if kind == "algo" else {"path": key}),
                 "enabled": enabled}
            )

        for el in (chain or []):
            if isinstance(el, str):
                add("algo", el, True)
            elif isinstance(el, dict) and el.get("path"):
                add("vst", el["path"], True)
        for p in (plugins or []):
            add("vst", p, False)
        for value in ALGORITHMS:
            add("algo", value, False)
        return result

    def _load_legacy(self):
        """本项目配置不存在时，读原版 RVC configs/config.json；失败返回空。"""
        try:
            if os.path.exists(LEGACY_CONFIG_PATH):
                with open(LEGACY_CONFIG_PATH, "r", encoding="utf8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {k: self._d.get(k, self._def[k]) for k in self._def}
        with open(self.path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False)


class ThemeConfigManager:
    """主题配置：单独持久化到 xiaoe_rvc_ui/theme_config.json，不污染 RVC 配置。"""

    def __init__(self, defaults, path):
        self._def = dict(defaults)
        self._d = dict(defaults)
        self.path = path
        self.load()

    def configget(self, key):
        return self._d.get(key, self._def.get(key))

    def configset(self, key, value):
        if self._d.get(key) == value:
            return
        self._d[key] = value
        self.save()

    def configreset(self, key):
        self._d[key] = self._def[key]
        self.save()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k in self._def:
                    self._d[k] = v
        except Exception:
            pass
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf8") as f:
            json.dump(self._d, f, ensure_ascii=False, indent=2)


class ModelImageBridge:
    """把某个模型条目的封面图桥接成 ConfigBridge 可读写的 'image' 键。

    编辑框的 ImagePicker 与卡片上的只读图片都绑定到同一个 bridge，
    改图后 value_changed 自动同步。
    """

    def __init__(self, library, mid):
        self.library = library
        self.mid = mid

    def configget(self, key):
        return self.library.image_path(self.mid) or ""

    def configset(self, key, value):
        if value:
            self.library.update_image(self.mid, value)

    def configreset(self, key):
        pass


class ModelLibrary:
    """模型库：models/library.json + 每个模型一个子文件夹。"""

    def __init__(self, models_dir, library_path):
        self.models_dir = models_dir
        self.library_path = library_path
        self.data = {"active": None, "models": []}
        self._image_bridges = {}
        self.load()

    def image_bridge(self, mid):
        """返回该模型的共享 ConfigBridge（封面图绑定）。"""
        if mid not in self._image_bridges:
            self._image_bridges[mid] = ConfigBridge(instance=ModelImageBridge(self, mid))
        return self._image_bridges[mid]

    # ---- 持久化 ----
    def load(self):
        os.makedirs(self.models_dir, exist_ok=True)
        if os.path.exists(self.library_path):
            try:
                with open(self.library_path, "r", encoding="utf8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"active": None, "models": []}
        if not isinstance(self.data.get("models"), list):
            self.data["models"] = []
        # 兼容旧数据：name_auto 缺失时，只有默认名字「新模型」视为自动
        for m in self.data["models"]:
            m.setdefault("name_auto", m.get("name") == "新模型")
        self.save()

    def save(self):
        os.makedirs(self.models_dir, exist_ok=True)
        with open(self.library_path, "w", encoding="utf8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 查询 ----
    def entries(self):
        return self.data.get("models", [])

    def get_entry(self, mid):
        for m in self.entries():
            if m["id"] == mid:
                return m
        return None

    def active_id(self):
        return self.data.get("active")

    def active_entry(self):
        return self.get_entry(self.active_id())

    def _path(self, mid, filename):
        return os.path.join(self.models_dir, mid, filename) if filename else None

    def model_path(self, mid):
        e = self.get_entry(mid)
        return self._path(mid, e["model"]) if e and e.get("model") else None

    def index_path(self, mid):
        e = self.get_entry(mid)
        return self._path(mid, e["index"]) if e and e.get("index") else None

    def image_path(self, mid):
        e = self.get_entry(mid)
        return self._path(mid, e["image"]) if e and e.get("image") else None

    # ---- 增删改 ----
    def _unique_name(self, mdir, filename, keep=None):
        """生成 mdir 中不冲突的文件名；keep 指定的同名文件允许覆盖。"""
        base, ext = os.path.splitext(filename)
        candidate = filename
        n = 1
        while os.path.exists(os.path.join(mdir, candidate)):
            if keep and candidate == keep:
                return candidate
            candidate = f"{base} ({n}){ext}"
            n += 1
        return candidate

    def _copy_into(self, mdir, src, keep=None):
        """复制 src 进 mdir（保留原名、重名加序号），返回目标文件名。"""
        name = self._unique_name(mdir, os.path.basename(src), keep=keep)
        dst = os.path.join(mdir, name)
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
            return name  # 源就是目标（重复选择库内文件），无操作
        shutil.copy2(src, dst)
        return name

    def import_model(self, pth_path, index_path=None, image_path=None, name=None):
        os.makedirs(self.models_dir, exist_ok=True)
        mid = uuid.uuid4().hex[:8]
        mdir = os.path.join(self.models_dir, mid)
        os.makedirs(mdir, exist_ok=True)
        mname = self._copy_into(mdir, pth_path)
        entry = {
            "id": mid,
            "name": name or os.path.splitext(mname)[0],
            "name_auto": True,
            "model": mname,
            "index": None,
            "image": None,
        }
        if index_path:
            iname = self._copy_into(mdir, index_path)
            entry["index"] = iname
        if image_path:
            ext = os.path.splitext(image_path)[1].lower() or ".png"
            shutil.copy2(image_path, os.path.join(mdir, "cover" + ext))
            entry["image"] = "cover" + ext
        self.data["models"].append(entry)
        self.data["active"] = mid
        self.save()
        return entry

    def create_entry(self, name="新模型"):
        """创建一个空模型条目（尚无模型文件），返回条目。"""
        os.makedirs(self.models_dir, exist_ok=True)
        mid = uuid.uuid4().hex[:8]
        os.makedirs(os.path.join(self.models_dir, mid), exist_ok=True)
        entry = {
            "id": mid,
            "name": name,
            "name_auto": True,
            "model": None,
            "index": None,
            "image": None,
        }
        self.data["models"].append(entry)
        self.save()
        return entry

    def set_active(self, mid):
        if self.get_entry(mid):
            self.data["active"] = mid
            self.save()

    def rename(self, mid, name):
        e = self.get_entry(mid)
        if e:
            e["name"] = name
            e["name_auto"] = False  # 手动改名后不再自动跟随 pth 文件名
            self.save()

    def replace_model_file(self, mid, new_pth):
        e = self.get_entry(mid)
        if not e:
            return
        mdir = os.path.join(self.models_dir, mid)
        old = e.get("model")
        name = self._copy_into(mdir, new_pth, keep=old)
        if old and name != old:
            oldp = os.path.join(mdir, old)
            if os.path.exists(oldp):
                os.remove(oldp)
        e["model"] = name
        if e.get("name_auto"):
            e["name"] = os.path.splitext(os.path.basename(new_pth))[0]
        self.save()

    def replace_index_file(self, mid, new_index):
        e = self.get_entry(mid)
        if not e:
            return
        mdir = os.path.join(self.models_dir, mid)
        old = e.get("index")
        name = self._copy_into(mdir, new_index, keep=old)
        if old and name != old:
            oldp = os.path.join(mdir, old)
            if os.path.exists(oldp):
                os.remove(oldp)
        e["index"] = name
        self.save()

    def remove_index(self, mid):
        e = self.get_entry(mid)
        if not e or not e.get("index"):
            return
        p = self._path(mid, e["index"])
        if p and os.path.exists(p):
            os.remove(p)
        e["index"] = None
        self.save()

    def update_image(self, mid, image_path):
        e = self.get_entry(mid)
        if not e:
            return
        mdir = os.path.join(self.models_dir, mid)
        if e.get("image"):
            old = self._path(mid, e["image"])
            if old and os.path.exists(old):
                os.remove(old)
        ext = os.path.splitext(image_path)[1].lower() or ".png"
        shutil.copy2(image_path, os.path.join(mdir, "cover" + ext))
        e["image"] = "cover" + ext
        self.save()

    def remove(self, mid):
        self.data["models"] = [m for m in self.entries() if m["id"] != mid]
        if self.data.get("active") == mid:
            self.data["active"] = self.entries()[0]["id"] if self.entries() else None
        shutil.rmtree(os.path.join(self.models_dir, mid), ignore_errors=True)
        self.save()

    def reorder(self, mid, delta):
        models = self.entries()
        idx = next((i for i, m in enumerate(models) if m["id"] == mid), None)
        if idx is None:
            return
        new = idx + delta
        if not (0 <= new < len(models)):
            return
        models[idx], models[new] = models[new], models[idx]
        self.save()


def make_rvc_config(engine):
    """装配业务配置 + 主题配置，返回 (rvc_cfg, theme_cfg, params)。"""
    params = Params()
    manager = RvcConfigManager(RVC_CONFIG_DEFAULTS, params, CONFIG_PATH)
    rvc_cfg = ConfigBridge(instance=manager)

    theme_manager = ThemeConfigManager(engine.get_defaults(), THEME_CONFIG_PATH)
    theme_cfg = ConfigBridge(instance=theme_manager)
    return rvc_cfg, theme_cfg, params
