# xiaoe_ui 使用手册

## 目录

1. [安装](#1-安装)
2. [5 秒上手](#2-5-秒上手)
3. [搭建你的应用](#3-搭建你的应用)
4. [控件参考](#4-控件参考)
5. [窗口参考](#5-窗口参考)
6. [对话框和通知](#6-对话框和通知)
7. [主题系统](#7-主题系统)
8. [热键绑定](#8-热键绑定)
9. [工具函数](#9-工具函数)
10. [打包发布](#10-打包发布-pyinstaller)
11. [附录: 架构树](#11-附录-架构树)

---

## 1. 安装

```bash
pip install xiaoe_ui
```

---

## 2. 五秒上手

```python
import sys
from PySide6.QtWidgets import QApplication
from xiaoe_ui import (
    MainWin, MainLayout, LeftList, ConfigBridge, StyleEngine,
    WinManager, ThemePage, make_form_row, resolve_static,
    CheckItem, ComboItem, SliderItem, ColorItem, make_line,
    SpinEntry,
)

# ① 主题引擎 — 最先创建，get_defaults() 给 config 提供初始值
engine = StyleEngine()
engine.set_internal_default("bg_image",
    resolve_static("xiaoe_ui/demo_static/background.png"))       # 设置背景图；resolve_static 兼容开发/PyInstaller 路径

# ② 配置管理器 — 为每个板块创建独立实例
class MyConfig:
    def __init__(self, defaults): self._d, self._def = {}, defaults
    def configget(self, key):
        return self._d[key] if key in self._d else self._def[key]
    def configset(self, key, value): self._d[key] = value
    def configreset(self, key): self._d[key] = self._def[key]

# 推荐为每个板块创建独立实例，各管各的
theme_cfg = ConfigBridge(instance=MyConfig(engine.get_defaults()))  # 主题配置
config    = ConfigBridge(instance=MyConfig({                         # 业务配置
    "enable": False, "mode": "A", "speed": 50, "age": 25,
    "color": (255, 0, 0),
}))

# ③ Qt 启动
app = QApplication(sys.argv)

# ④ WinManager 全局注入 — 设好 source，后续窗口自动继承
WinManager.set_style_source(lambda: engine.make_style(theme_cfg))   # QSS
WinManager.set_bg_source(lambda: engine.resolve_value(theme_cfg, "bg_image"))

# ⑤ 主窗口 — 继承 MainWin
class MyApp(MainWin):
    def __init__(self):
        super().__init__(win_title="我的应用", scroll=False)
        self.setup_ui()
        self.resize(1100, 700)
        self.apply_all()

    def add_ui(self):
        layout = MainLayout(self)
        left = LeftList()
        page = left.add_page("home", "首页", icon="🏠")

        # ⑥ 添加 L3 配置项 (标题 + 控件 + 重置)
        CheckItem("可用", config=config, config_name="enable", parent_layout=page)
        ComboItem("模式", options=["A","B"], config=config, config_name="mode", parent_layout=page)
        SliderItem("速度", config=config, config_name="speed", config_range=(0,100), step=5, parent_layout=page)
        ColorItem("颜色", config=config, config_name="color", parent_layout=page)

        # ⑦ L2 表单行 — Entry(无标题) + make_form_row(加标题)
        page.addWidget(make_form_row("年龄", SpinEntry(config=config, config_name="age", config_range=(0,150))))

        # ⑧ 主题设置页 — 一行代码自动生成
        theme_page = left.add_page("theme", "主题", icon="🎨")
        ThemePage(theme_page, engine=engine, config=theme_cfg,
                  on_style_changed=WinManager.apply_style_all)

        left.switch_to("home")
        layout.left_layout.addLayout(left.left_layout)
        layout.right_layout.addWidget(left.stack)

# ⑨ 显示
win = MyApp()
win.show()
app.exec()
```

①~⑨ 就是搭建一个 xiaoe_ui 应用的标准流程，下面逐段展开。

---

## 3. 搭建你的应用

初始化顺序固定，和 demo 一致：

```
engine → engine.get_defaults() → config → QApplication → WinManager.set_* → MainWin → show
```

### 3.1 初始化

```python
import sys
from PySide6.QtWidgets import QApplication
from xiaoe_ui import StyleEngine, ConfigBridge, WinManager, resolve_static

# Engine 管理 QSS + 变量 + 预设主题，最先就位（纯数据，不需要 QApplication）
engine = StyleEngine()

# ConfigBridge — 推荐为每个板块创建独立实例
theme_cfg = ConfigBridge(instance=MyConfig(engine.get_defaults()))  # 主题配置
config    = ConfigBridge(instance=MyConfig({                         # 业务配置
    "enable": False, "speed": 50, ...
}))

# QApplication — 创建 Qt 应用
app = QApplication(sys.argv)

# WinManager 全局注入 — 设好 source，后续窗口自动继承
WinManager.set_style_source(lambda: engine.make_style(theme_cfg))  # QSS
WinManager.set_icon_source(resolve_static("xiaoe_ui/demo_static/default_ico.ico"))                               # 窗口图标（不归主题管理）
WinManager.set_bg_source(lambda: engine.resolve_value(theme_cfg, "bg_image"))  # 背景图
```

`StyleEngine` 和 `ConfigBridge` 的详情见 [7. 主题系统](#7-主题系统) 和下面的 [3.5 配置双绑](#35-配置双绑)，这里先按上面的写法就行。

#### ConfigBridge.memory — 临时配置

不需要持久化时，一行搞定：

```python
from xiaoe_ui import ConfigBridge
cfg = ConfigBridge.memory({"speed": 50})
```

### 3.2 主窗口

```python
from xiaoe_ui import MainWin

class MyApp(MainWin):
    def __init__(self):
        super().__init__(win_title="我的应用", scroll=False)
        self.setup_ui()
        self.resize(1100, 700)
        self.apply_all()   # 注入样式/背景/图标

    def add_ui(self):
        # 在这里构建界面
        ...
```

### 3.3 侧栏导航

```python
from xiaoe_ui import MainLayout, LeftList, CheckItem
from PySide6.QtWidgets import QLabel

def add_ui(self):
    layout = MainLayout(self)  # 左右双栏
    left = LeftList()

    # 一级页面
    page = left.add_page("home", "首页", icon="🏠")
    page.addWidget(QLabel("内容"))

    # 二级分组
    group = left.add_group("settings", "设置", icon="📦")
    sub = group.add_page("general", "通用", icon="⚙")
    sub.addWidget(CheckItem("选项", ...))

    left.switch_to("home")

    # 组装
    layout.left_layout.addLayout(left.left_layout)
    layout.right_layout.addWidget(left.stack)
```

`switch_to(key)` 跳转时自动展开对应的二级分组。

### 3.4 添加控件

框架用三层架构管理控件：

| 层级 | 职责 | 示例 |
|------|------|------|
| L1 裸组件 | 只管视觉，不碰 config | CustomSpinBox, GradientBar, StatusLineEdit |
| L2 Entry | L1 + config 绑定，**不带标题** | SpinEntry, TextEntry, SliderEntry |
| L3 配置项 | L2 + 标题 + 重置按钮 | SliderItem, CheckItem, ColorItem |

**常规场景直接用 L3：**

```python
from xiaoe_ui import CheckItem, SliderItem, ColorItem

CheckItem("启用", config=config, config_name="enable", parent_layout=page)
SliderItem("速度", config=config, config_name="speed", config_range=(0,100), parent_layout=page)
ColorItem("颜色", config=config, config_name="color", parent_layout=page)
```

**需要自定义布局时拿 L2 + make_form_row 拼（也可以直接自己排版）：**

```python
from xiaoe_ui import make_form_row, SpinEntry, TextEntry

page.addWidget(make_form_row("年龄", SpinEntry(config, "age", config_range=(0,150))))
page.addWidget(make_form_row("姓名", TextEntry(config, "name", placeholder="请输入")))
```

所有控件详见 [4. 控件参考](#4-控件参考)。

### 3.5 配置双绑

L2 和 L3 都支持：传相同的 `config` + `config_name`，自动互相同步。

```python
from xiaoe_ui import SliderItem, SpinEntry, make_form_row

# L3 — 两个 SliderItem 绑同一个 key
SliderItem("滑块 A", config=config, config_name="speed", parent_layout=page)
SliderItem("滑块 B", config=config, config_name="speed", parent_layout=page)

# L2 — 两个 SpinEntry 绑同一个 key
page.addWidget(make_form_row("整数 A", SpinEntry(config, "count")))
page.addWidget(make_form_row("整数 B", SpinEntry(config, "count")))

# L2 + L3 混绑 — SliderEntry 和 SpinEntry 同 key，拖动滑块数字框自动跟变
# SliderItem 内部就是这么做的
```

原理：`config.set(key, value)` 发出 `value_changed(key, value)` 信号，同 key 的控件收到后刷新自己。

**L3组件不需要 config 时走纯 callback：**

```python
from xiaoe_ui import CheckItem

CheckItem("启用", callback=lambda v: do_something(v))
```

**监听任意 key 的变化，用 `config.on()`：**

```python
def on_speed(v): print(f"速度 → {v}")
config.on("speed", on_speed)
config.off("speed", on_speed)  # 必须传同一个函数引用，不能是 lambda
```

### 3.6 跳转和闪烁

`left` 是 `LeftList` 实例，通常在 `MainWin.add_ui()` 里创建，存为 `self.left`。外部通过 MainWin 实例（即前面 3.2 的 `win`）调用。

`switch_to(key)` 跳转到指定页面（二级页面自动展开分组）。

`tag` 是配置项的参数，传给 `flash_config_widget()`（`from xiaoe_ui import flash_config_widget`）即可闪烁：

```python
from xiaoe_ui import SliderItem, flash_config_widget

SliderItem("速度", tag="speed_demo", ...)  # 创建时注册 tag

win.left.switch_to("home")                  # 跳到首页
flash_config_widget("speed_demo")           # 闪烁 tag，边框闪 5 次

# 跳转+闪烁可以一起
win.left.switch_to("widgets")
flash_config_widget("speed_demo")
```

也可手动注册任意 ClickFrame：`register_tag("my_tag", frame)`。

---

## 4. 控件参考

> 以下示例假定已导入：`from xiaoe_ui import ...` 和 `from typing import Callable`。每个代码块可独立运行，缺少的 import 请自行补充。

### 4.1 L3 配置项

所有 L3 Item 支持 `parent_layout`、`callback`、`tag` 三个通用参数。

#### CheckItem — 布尔配置

```python
CheckItem(
    title: str,
    text: str = "",
    config: ConfigBridge = None,
    config_name: str = None,
    callback: Callable[[bool], None] = None,
    default_check: bool = False,
    tag: str = None,
    parent_layout = None,
)
```

#### ComboItem — 下拉选择

```python
ComboItem(
    title: str,
    text: str = "",
    options: list[str] = None,
    config: ConfigBridge = None,
    config_name: str = None,
    callback: Callable[[int], None] = None,
    default_index: int = 0,
    width: int = 120,
    store_index: bool = False,      # False=存原始值, True=存索引
    tag: str = None,
    parent_layout = None,
)
```

#### SliderItem — 滑块+输入框+重置

SliderEntry 和 SpinEntry 共享 config_name，拖动滑块时输入框自动跟变。

```python
SliderItem(
    title: str,
    text: str = "",
    config: ConfigBridge = None,
    config_name: str = None,
    config_range: tuple = None,     # None 时默认 (0, 100)
    step: float = 1,                # 自动推导 int/float + 小数位
    num_type_text: str = "",        # 单位
    live: bool = True,              # True=拖动实时提交, False=松手提交
    callback: Callable = None,
    tag: str = None,
    parent_layout = None,
)
```

#### ColorItem — 颜色选择

```python
ColorItem(
    title: str,
    config: ConfigBridge = None,
    config_name: str = None,
    text: str = "",
    default_color: tuple = (255, 0, 0),
    rgba: bool = False,             # True 支持透明度
    btn_text: str = "设置",
    callback: Callable = None,
    tag: str = None,
    parent_layout = None,
)
```

#### GradientItem — 渐变色编辑

```python
GradientItem(
    title: str,
    config: ConfigBridge = None,
    config_name: str = None,
    text: str = "",
    default: list[dict] | None = None,  # 默认白→黑
    callback: Callable = None,
    tag: str = None,
    parent_layout = None,
)
```

#### BottomItem — 操作按钮

动作按钮，不绑定配置值，仅触发 callback。支持 设置/取消 状态切换和独立重置回调。

```python
BottomItem(
    title: str,
    text: str = "",
    btn_text: str = "设置",
    callback: Callable = None,
    cancel_callback: Callable = None,  # 设置后按钮可切换 设置/取消
    btn_cancel_text: str = None,
    reset_callback: Callable = None,   # 重置按钮回调
    tag: str = None,
    parent_layout = None,
)
```

#### KeyItem — 热键绑定

需要 `xiaoe_keyboard` 库。

```python
from xiaoe_ui import KeyItem

KeyItem("快捷键", config=key_cfg, config_name="my_hotkey",
        text="设置快捷键", keyboard=kb, parent_layout=page)
```

#### 配置项闪烁

```python
from xiaoe_ui import flash_config_widget, register_tag, SliderItem

SliderItem("速度", config=config, config_name="speed", tag="demo", ...)
flash_config_widget("demo", times=5)     # 按 tag 闪烁

register_tag("demo", some_click_frame)   # 手动注册任意 ClickFrame
flash_config_widget("demo")
```

### 4.2 L2 表单 Entry + make_form_row

Entry 只做 config 绑定，不带标题。可配合 `make_form_row(title, entry)` 使用制作表单页面，也可以自行自由排版：

```python
from xiaoe_ui import make_form_row, SpinEntry, TextEntry, MultiEntry, ImagePicker, DatePicker

page.addWidget(make_form_row("年龄", SpinEntry(config, "age", config_range=(0,150))))
page.addWidget(make_form_row("姓名", TextEntry(config, "name", placeholder="请输入")))
page.addWidget(make_form_row("简介", MultiEntry(config, "intro", height=80)))
page.addWidget(make_form_row("头像", ImagePicker(config, "avatar", size=80)))
page.addWidget(make_form_row("生日", DatePicker(config, "birthday")))
```

#### SpinEntry — 数字输入

```python
SpinEntry(
    config: ConfigBridge = None,
    config_name: str = None,
    step: float = 1,                # 自动推导 int/float 模式 + 小数位
    config_range: tuple = None,
    prefix: str = "",
    suffix: str = "",
    default = 0,
    live: bool = False,             # True=每次按键提交
    validate: Callable = None,
    callback: Callable = None,
    width: int = 80,
)
```

#### TextEntry — 文本输入

```python
TextEntry(
    config: ConfigBridge = None,
    config_name: str = None,
    placeholder: str = "",
    value_type: Callable = str,     # str/int/float 或自定义函数校验，抛出异常校验失败，或在内写入逻辑，帮助用户修正数值
    default: str = "",
    callback: Callable = None,
    width: int = 150,
)
```

#### MultiEntry — 多行文本

```python
MultiEntry(
    config: ConfigBridge = None,
    config_name: str = None,
    height: int = 80,
    default: str = "",
    callback: Callable = None,
)
```

#### 其他 Entry (紧凑写法)

```python
from xiaoe_ui import ImagePicker, DatePicker, ColorEntry, SliderEntry, CheckEntry, ComboEntry

ImagePicker(config, config_name, size=80, callback=...)
DatePicker(config, config_name, fmt="yyyy-MM-dd")
ColorEntry(config, config_name, rgba=False, callback=...)
SliderEntry(config, config_name, config_range=(0,100), step=1, live=True, callback=...)
CheckEntry(config, config_name, callback=...)
ComboEntry(config, config_name, options=["A","B"], callback=...)
```

### 4.3 L1 裸组件（需要你自己对接逻辑）

直接使用，无 config 绑定。

#### CustomSpinBox

StatusLineEdit + ▲/▼ 按钮，长按连发。替代 QSpinBox。

```python
from xiaoe_ui import CustomSpinBox
box = CustomSpinBox(min_val=0, max_val=100, value=50, step=1, live=False)
box.valueChanged.connect(lambda v: ...)
```

#### GradientBar

QPainter 渐变预览 + 可拖拽色标。

```python
from xiaoe_ui.widgets.gradient import GradientBar
bar = GradientBar(stops=[{"pos": 0.0, "color": (255,0,0,255)}, ...], live=True)
bar.valueChanged.connect(lambda stops: ...)
```

#### ColorPickerButton

```python
from xiaoe_ui.widgets.status_widgets import ColorPickerButton

btn = ColorPickerButton(color=(255, 0, 0), rgba=True, tooltip_text="设置")
btn.colorChanged.connect(lambda c: ...)
print(btn.color())    # → (r,g,b) 或 (r,g,b,a)
btn.setColor((0,255,0))  # 不触发 colorChanged 信号
```

#### DateTimePickerDialog

继承 `Dialog(WinManager)`，年/月/日/时/分/秒 SpinBox + 可折叠日历。

```python
from PySide6.QtCore import QDateTime
from xiaoe_ui import DateTimePickerDialog

dlg = DateTimePickerDialog(current=QDateTime.currentDateTime(),
                           fmt="yyyy-MM-dd HH:mm:ss")
if dlg.exec() == QDialog.Accepted:
    print(dlg.result())  # → QDateTime
```

#### StatusLineEdit / StatusDateEdit / StatusTextEdit / StatusImagePicker

带状态边框 (edited黄/success绿/error红)。

```python
from xiaoe_ui import StatusLineEdit

edit = StatusLineEdit(text="初始值", value_type=int)
edit.editingFinished  # 自动校验, success 5秒后回 normal
edit.flash_success()   # 手动显示绿框
```

### 4.4 布局辅助

#### make_form_row

`[title:　<6] [stretch] [widget]`

```python
from xiaoe_ui import make_form_row, TextEntry

row = make_form_row("姓名", TextEntry(config, "name"))
page.addWidget(row)
```

#### make_line / make_tip

```python
from xiaoe_ui import make_line, make_tip

make_line(parent_layout, bold=True)          # 分隔线
make_tip("提示文字", parent_layout=layout)    # 小字提示
```

### 4.5 其他组件

#### ClickFrame

可点击 QFrame，支持左右键回调 + selected/clicked/light 视觉反馈。

```python
from xiaoe_ui import ClickFrame

frame = ClickFrame(
    default_line=True,       # 默认显示边框
    hand_cursor=True,        # 鼠标悬停显示手型
    custom_class="light-line", # QSS class: "light-line" | "light-line disable" | ...
)
frame.on_left_click(lambda: print("左键"))
frame.on_right_click(lambda: print("右键"))

frame.set_selected(True)     # selected 属性高亮
frame.set_light(True)        # light 属性高亮 (闪烁用)
```

#### BigButton

居中大按钮，继承 ClickFrame。多用于页面内操作入口。

```python
from xiaoe_ui import BigButton

btn = BigButton("📝 打开编辑器", click_cb=lambda: ...)
btn = BigButton("🔒 不可交互", custom_class="light-line disable", hand_cursor=False)
```

#### InstantTooltipMixin — 通用即时 Tooltip

可继承在**任意** Qt 控件上，鼠标悬停立即显示自定义 QSS tooltip。`setToolTip()` 被内部接管，不触发 Qt 原生 tooltip。

**必须放在继承列表最左侧**，确保 `__init__` / `enterEvent` / `leaveEvent` 覆盖 Qt 基类行为:

```python
from PySide6.QtWidgets import QLabel, QPushButton, QLineEdit
from xiaoe_ui import InstantTooltipMixin

class MyLabel(InstantTooltipMixin, QLabel): pass
class MyBtn(InstantTooltipMixin, QPushButton): pass

label = MyLabel("悬停看提示")
label.setToolTip("我是提示文字")  # 接管，不走 Qt 原生
```

**可重载方法：**

| 方法 | 说明 |
|------|------|
| `_get_tip_text()` | 返回 tooltip 文本，默认 `self.toolTip()`。子类重载实现动态内容 |
| `_tip_offset()` | 返回相对控件左上角偏移 `QPoint`，默认 `(0,0)` |

**公开方法：**

| 方法 | 说明 |
|------|------|
| `show_tip(text=None)` | 手动弹出，None 用 `_get_tip_text()` |
| `hide_tip()` | 手动隐藏 |
| `update_tip(text)` | 更新已显示 tooltip 的文本，不重新定位（拖拽专用） |
| `bind_tip(other)` | 绑定另一个 mixin，hover self 时也弹出 other 的 tooltip |
| `tip_suppressed` | 属性，设为 True 抑制一切 tooltip 操作 |

#### InstantTipLabel / InstantTipButton — 常用快捷类

框架预置，日常直接用：

```python
from xiaoe_ui import InstantTipLabel, InstantTipButton

label = InstantTipLabel("悬停看提示")
label.setToolTip("我是提示文字")

btn = InstantTipButton("按钮")
btn.setToolTip("按钮提示")
```

#### ABox — 可折叠块

```python
from xiaoe_ui import ABox

box = ABox("标题", parent_layout=page, expanded=True)
box.content_layout.addWidget(...)   # 往展开区添加控件
```

#### HideItem — 可折叠单行

```python
from xiaoe_ui import HideItem

HideItem("高级", "点击展开", show_func=lambda layout: layout.addWidget(...),
         parent_layout=page)
```

---

## 5. 窗口参考

> 以下示例假定已导入相关模块。每个代码块可独立运行，缺少的 import 请自行补充。

### 5.1 MainWin

主窗口基类，继承自 `FramelessWin`，内置标题栏、滚动区、背景/图标加载。

**完整参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `win_title` | str | `"xiaoe_ui"` | 窗口标题 |
| `content_h` | bool | `False` | True=内容区改用横向布局（QHBoxLayout） |
| `scroll` | bool | `True` | True=内容区包裹 QScrollArea |
| `add_bottom_empty` | bool | `True` | True=内容区末尾追加弹簧 |
| `maxsize_btn` | bool | `True` | True=标题栏显示最大化按钮 |
| `hide_btn` | bool | `False` | True=标题栏额外显示隐藏按钮 |
| `auto_set_icon` | bool | `True` | 当前未启用；窗口图标统一由 `set_icon_source` 管理 |
| `add_down_block` | bool | `False` | True=底部添加空白占位块 |

**主窗口：**

```python
class MyApp(MainWin):
    def __init__(self):
        super().__init__(win_title="我的应用", scroll=False)
        self.setup_ui()
        self.resize(1100, 700)
        self.apply_all()

    def add_ui(self):
        ...
```

**子窗口**（仍是 MainWin，需手动 `setup_ui()` + `apply_all()`）：

```python
w = MainWin(win_title="子窗口", scroll=False)
w.add_ui = lambda: ...
w.setup_ui()
w.apply_all()
w.show()
```

**单例窗口** — 混入 `SingletonMixin`，同 key 只保留一个实例：

```python
class MyPopup(MainWin, SingletonMixin):
    def __init__(self):
        MainWin.__init__(self, win_title="弹窗")
        SingletonMixin._singleton_init(self, "my_popup", only_one=True)

    def closeEvent(self, event):
        SingletonMixin._singleton_close(self)
        super().closeEvent(event)
```

### 5.2 WinManager

> 以下 WinManager 代码示例假定已导入 `from xiaoe_ui import WinManager, MainWin`。

WinManager 是 MainWin / Dialog / FramelessWin 的共同基类，把**样式、背景、图标**拆为三个独立模块，各自有设 source → apply 的完整流程。`MainWin` / `Dialog` 构造时自动注册到全局实例列表；裸 `FramelessWin` 仅在 `use_global_style=True` 时注册；`TopBoxWindow` / `NotifyOverlay` 不继承 WinManager。

#### 架构: source → apply

```
set_style_source(fn)  →  apply_style()     →  setStyleSheet(qss)
set_bg_source(fn)     →  apply_bg()        →  设置背景 QPixmap
set_icon_source(path) →  apply_icon()      →  setWindowIcon(icon)
```

source 是全局的（类方法），apply 分实例级和全局级：

| 粒度 | 样式 | 背景 | 图标 | 三者合一 |
|------|------|------|------|----------|
| 当前实例 | `win.apply_style()` | `win.apply_bg()` | `win.apply_icon()` | `win.apply_all()` |
| 全部窗口 | `WinManager.apply_style_all()` | `WinManager.apply_bg_all()` | `WinManager.apply_icon_all()` | `WinManager.apply_all_wins()` |

#### 初始化流程

```python
# ① 窗口创建前 — 设好 source（仅需一次）
WinManager.set_style_source(lambda: engine.make_style(theme_cfg))
WinManager.set_icon_source(resolve_static("xiaoe_ui/demo_static/default_ico.ico"))
WinManager.set_bg_source(lambda: config.get("bg_image"))

# ② 创建窗口 — 构造时自动 _register() 注册到全局列表
win = MainWin(...)

# ③ 应用 — apply_all() 一次注入样式+背景+图标
win.apply_all()
```

`apply_all()` **不会自动调用**：`MainWin` 需手动调（见 5.1 各示例）；`Dialog` 和 `use_global_style=True` 的 `FramelessWin` 会在构造时自动 `apply_all()`。

#### 实例管理

```python
WinManager.apply_style_all()    # 主题切换后 — 只刷新样式
WinManager.apply_bg_all()       # 换背景图后 — 只刷新背景
WinManager.on_top_all_win(True)  # 全局置顶
WinManager.on_top_all_win(False) # 取消置顶
WinManager.close_all_wins()     # 一键关闭全部窗口
```

子类窗口可在构造时传 `on_top_with_global=False` 退出全局置顶管理。

#### 背景图

MainWin 通过 `add_bg()` 在最底层创建 QLabel，自动随窗口 resize 缩放裁剪（保持宽高比）。`apply_bg()` 时重新读取 source 路径并设 QPixmap。

#### 自定义窗口继承 WinManager

不仅仅是框架内置窗口——你也可以让自己写的 QWidget / QDialog 继承 WinManager，享受统一的样式、背景、图标和全局管理：

```python
from PySide6.QtWidgets import QWidget
from xiaoe_ui.core.win_manager import WinManager

class MyCustomWin(WinManager, QWidget):
    def __init__(self):
        super().__init__()
        self._register()           # ① 手动注册到全局列表
        self.add_bg()              # ② 添加背景 QLabel（如需背景图）
        self.apply_all()           # ③ 注入样式+背景+图标
```

三步：`_register()` 入全局列表 → `add_bg()` 建背景层（可选）→ `apply_all()` 注入。之后 `close_all_wins()`、`apply_style_all()` 等全局方法会自动覆盖。

注意 WinManager 须放在继承列表**最左侧**，确保 `__init__` 和 `resizeEvent` 正确覆盖 Qt 基类。

#### 谁不继承？

TopBoxWindow / NotifyOverlay **不继承** WinManager，是独立 QWidget，不受以上任何方法影响。

### 5.3 Dialog

```python
from xiaoe_ui import Dialog
from PySide6.QtWidgets import QLabel

# 阻塞 (默认)
dlg = Dialog(parent, win_title="设置", width=400, height=300)
dlg.root_layout.addWidget(QLabel("内容"))
dlg.exec()

# 非阻塞
dlg = Dialog(parent, win_title="非阻塞", width=300, height=150, modal=False)
dlg.show()
```

**Dialog 是空白容器，不内置任何按钮。所有控件由调用方自行添加。**

### 5.4 SingletonMixin

混入任意 WinManager 子类，结合 `get_singleton()` 实现"同 key 只开一个"。适用于所有窗口和dialog。

分两种情况：

**情况一: `only_one=True` — 全局唯一（key 仍必填）**

```python
from xiaoe_ui import Dialog
from xiaoe_ui.core.singleton_mixin import SingletonMixin

class MyWin(Dialog, SingletonMixin):
    def __init__(self):
        Dialog.__init__(self, modal=False)
        SingletonMixin._singleton_init(self, key="my_win", only_one=True)

    def closeEvent(self, e):
        SingletonMixin._singleton_close(self)
        super().closeEvent(e)

# 直接查 — 全局只有一个
existing = MyWin.get_singleton("my_win")
if existing:
    existing.activateWindow()  # 激活已有，不新建
    return
MyWin().show()
```

> `only_one=True` 时，同 key 已有实例却仍直接构造，会激活已有实例并抛出 `OpenTooManyWin`（可用 `@SingletonMixin.open_too_many_except(...)` 装饰器捕获）。上面的 `get_singleton` 检查是更稳妥的写法。

**情况二: `only_one=False` (默认) — 按 key 分组，本身不阻止同 key 多实例**

```python
from xiaoe_ui import Dialog
from xiaoe_ui.core.singleton_mixin import SingletonMixin

class MyWin(Dialog, SingletonMixin):
    def __init__(self, key):
        Dialog.__init__(self, modal=False)
        SingletonMixin._singleton_init(self, key)  # 按 key 注册，默认 only_one=False

    def closeEvent(self, e):
        SingletonMixin._singleton_close(self)
        super().closeEvent(e)

# 不同 key 可并存；同 key 只开一个需自己先检查
existing = MyWin.get_singleton("file_A")
if existing:
    existing.activateWindow()
    return
MyWin("file_A").show()

MyWin("file_B").show()  # 不同 key，共存
existing = MyWin.get_singleton("file_A")
if existing:
    existing.activateWindow()  # 同 key，激活已有，不新建
```

`only_one=False` 时框架**不会**自动阻止同 key 重复创建，只负责按 key 分组记录，需调用方用 `get_singleton()` 检查后才新建。

场景举例：在同一个创建窗口实例的地方，同一个文件不要重复打开两个编辑窗口（key=文件路径）、同一个设置面板不要弹出两份（key=面板名），等等。

### 5.5 FramelessWin

无边框、可拖拽移动、可 8 方向 resize 的窗口基类。本框架内除了dialog的所有窗口的基类都是它。

```python
from xiaoe_ui import FramelessWin

win = FramelessWin(
    min_w=200, min_h=100,      # 最小宽高
    rsize_margin=6,             # resize 边缘检测宽度 (px)
    main_win=False,             # True=主窗口模式，False=悬浮窗模式
    cuantou=False,              # True=穿透模式，鼠标事件穿透到下层窗口
    use_global_style=False,     # True=应用 WinManager 全局样式（并自动注册+apply_all）
)
```

#### 两种模式

| 模式 | `main_win=True` | `main_win=False` |
|------|----------------|-------------------|
| resize | 需编辑模式（MainWin 由 `setup_ui()` 自动进入） | 需调 `enter_edit_mode()` |
| 移动 | 需编辑模式下拖拽标题栏 | 调 `enter_edit_mode()` 后拖拽任意位置 |
| 典型用途 | MainWin 主窗口就是开启这个模式 | 悬浮窗、穿透窗 |

> 两种模式下，拖拽 / resize 都要求 `is_edit_mode=True`。`MainWin` 在 `setup_ui()` 末尾自动 `enter_edit_mode()`；裸 `FramelessWin(main_win=True)` 需手动调。

#### 编辑模式

子窗口通过编辑模式调整位置和大小，调整完退出时自动保存：

```python
win.enter_edit_mode()   # 进入 — 显示半透明遮罩，允许拖拽/resize
# ... 用户调整窗口 ...
win.exit_edit_mode()    # 退出 — 隐藏遮罩，调用 _save_config() 持久化
```

可传入 `custom_edit_overlay` 替换默认遮罩。子类重写 `_load_config()` / `_save_config()` 实现窗口位置持久化。

#### 穿透模式

`cuantou=True` 时窗口置顶且鼠标事件穿透到下层，仅 `Qt.WindowTransparentForInput` 标记的区域可被点击。需配合 `ClickThroughMixin` 实现部分控件可点。

```python
win.set_cuantou(True)   # 开启穿透
win.set_cuantou(False)  # 关闭穿透
```

#### 宽高比锁定

```python
win.keep_aspect_ratio = True
win.aspect_ratio = 16 / 9  # resize 时保持 16:9
```

### 5.6 ClickThroughMixin

穿透窗口交互混入。配合 `FramelessWin(cuantou=True)` 使用，通过 `mouse` 库的全局钩子对已注册控件做命中测试——窗口整体穿透，但指定的按钮/控件仍可点击。

**依赖**: `pip install mouse`

```python
from xiaoe_ui import FramelessWin, ClickThroughMixin

class MyPanel(ClickThroughMixin, FramelessWin):
    def __init__(self):
        super().__init__(cuantou=True)
        self.register_clickable(
            self.btn,
            on_left=lambda: print("左键点击"),    # 鼠标在控件内释放 → 点击
            on_right=lambda: print("右键点击"),
            on_middle=lambda: print("中键点击"),
            on_press=lambda: print("按下"),       # 鼠标按下瞬间
            on_normal=lambda: print("恢复正常"),  # 释放后恢复到正常状态
        )
        self.register_click_other(lambda: print("点击了空白区域"))

    def showEvent(self, event):
        super().showEvent(event)
        self.start_mouse_hook()    # 启动全局钩子

    def hideEvent(self, event):
        self.stop_mouse_hook()     # 停止钩子
        super().hideEvent(event)
```

要点：

- `register_clickable(widget, on_left, on_right, on_middle, on_press, on_normal)` — 注册可点击控件，按键回调可选
- `register_click_other(func)` — 点击非注册区域（空白区域）的回调
- `start_mouse_hook()` / `stop_mouse_hook()` — 启停全局钩子，放在 `showEvent` / `hideEvent`
- 模拟标准按钮行为：press 记录控件 → release 在同一控件上触发对应按键回调
- `unregister_clickable(widget)` / `unregister_click_other(func)` — 取消注册

### 5.7 OpenGL 变体: FramelessWinOpenGL / MainWinOpenGL / TopBoxWindowOpenGL

常规窗口底层是 `QWidget`，OpenGL 变体底层替换为 `QOpenGLWidget`，用法完全一致。

**为什么要有 OpenGL 变体？** 这是为壁纸模式准备的（见 [5.8 WallpaperWinMixin](#58-wallpaperwinmixin--壁纸模式)）：壁纸模式要求窗口必须是 `QOpenGLWidget`，因为**非 OpenGL 窗口放到桌面壁纸层后不会刷新**（桌面图标下方不触发 Qt 普通重绘）。所以凡是和壁纸模式一起用的窗口，都换成对应的 OpenGL 变体。

| OpenGL 类 | 对应原版 |
|-----------|----------|
| `FramelessWinOpenGL` | `FramelessWin` |
| `MainWinOpenGL` | `MainWin` |
| `TopBoxWindowOpenGL` | `TopBoxWindow` |

```python
from xiaoe_ui import MainWinOpenGL

class MyApp(MainWinOpenGL):
    def __init__(self):
        super().__init__(win_title="OpenGL 窗口")
        self.setup_ui()
        self.apply_all()
```

### 5.8 WallpaperWinMixin — 壁纸模式

将窗口嵌入 Windows 桌面壁纸层（图标下方）。窗口**必须是 OpenGL 窗口**（底层为 `QOpenGLWidget`，构造时框架会 `assert` 校验），否则放到壁纸层后不会刷新。可以用框架提供的 OpenGL 变体（[5.7 OpenGL 变体](#57-opengl-变体-framelesswinopengl--mainwinopengl--topboxwindowopengl) 里的 `FramelessWinOpenGL` / `MainWinOpenGL` / `TopBoxWindowOpenGL`），也可以自己继承 `QOpenGLWidget` 创建窗口。`WallpaperWinMixin` 必须放在继承列表**最左侧**：

```python
from xiaoe_ui import WallpaperWinMixin, FramelessWinOpenGL

class MyWallpaper(WallpaperWinMixin, FramelessWinOpenGL):  # 用框架变体，或换成你自己的 QOpenGLWidget 子类
    def __init__(self):
        super().__init__(cuantou=True)
        self.init_wallpaper(default_show=True)

    def set_config_into_wallpaper_func(self, value):
        config.set("wallpaper_enabled", value)   # 必须重写，否则进入壁纸模式抛 NotImplementedError
```

**必须重写 `set_config_into_wallpaper_func(value)`**：进入壁纸模式时框架回调它，把壁纸状态写进你的 config。不重写且真的进入壁纸模式（`is_wallpaper` 为 True）时会直接抛 `NotImplementedError`。

#### 方法

| 方法 | 参数语义 |
|------|----------|
| `init_wallpaper(default_show=True)` | 初始化并进入壁纸模式：`show()` → `set_as_wallpaper(True)`；`default_show=False` 时进入后再 `hide()`。适合启动时检测到"上次是壁纸"再恢复 |
| `set_as_wallpaper(checked=None, reset=False, first=False, move_open=False, full_screen=False)` | 切换壁纸。`checked=None` 沿用当前状态只重排位置；`move_open=True` 供编辑模式移动窗口时**暂时退出壁纸层**；`reset` / `first` / `full_screen` 是内部对齐屏幕时用的，一般不用传 |
| `enter_edit_mode()` / `exit_edit_mode()` | 解锁/锁定窗口位置。进入编辑模式自动暂退壁纸层，退出时恢复 |
| `set_config_into_wallpaper_func(value)` | **必须重写**：`value` 为壁纸状态布尔，写入你的 config 持久化 |
| `apply_wallpaper_xy_offset(rect)` | 把 Qt 坐标换算到虚拟桌面坐标，多屏时对齐物理屏幕边界 |

#### 真实用法参考

demo 的完整组合（`xiaoe_ui/demo/click_through_demo.py`）可作为组装参考：`WallpaperWinMixin + ClickThroughMixin + FramelessWinOpenGL` 三件套，构造传 `use_global_style=True`、`on_top_with_global=False`；用 `_load_config()` / `_save_config()` 持久化窗口几何；重写 `set_as_wallpaper()` 在进入壁纸后补 `self.on_top(True)`；启动时读配置里的 `is_ct_win_wallpaper` 决定是否 `init_wallpaper(default_show=False)`。

---

## 6. 对话框和通知

> 以下示例假定已导入相关模块。

框架提供三级通知体系：阻塞式 MsgBox（重要确认）、非阻塞 NotifyOverlay（轻量提示）、完全自定义 TopBoxWindow（悬浮窗绘制）。

### 6.1 MsgBox — 消息弹窗

基于 `QMessageBox + WinManager`，自动继承全局样式和图标。全部阻塞，返回用户选择结果。

```python
from xiaoe_ui import ask, info, warn, error, input_dialog

# ── 询问 — 返回 True/False/None ──
ask("确认删除", "此操作不可撤销，确定删除吗？")          # True=是, False=否
ask("保存更改", "是否保存？", with_cancel=True)         # True=是, False=否, None=取消
ask("覆盖文件", "文件已存在，是否覆盖？",
    yes_text="覆盖", no_text="保留")                    # 自定义按钮文字

# ── 信息/警告/错误 — 点确定关闭 ──
info("操作完成", "文件已成功导出到桌面。")
warn("磁盘空间不足", "剩余空间不足 500MB，请清理。")
error("操作失败", "无法连接到服务器，请检查网络。")

# ── 输入框 — 返回用户输入字符串 ──
name = input_dialog("新建文件夹", "请输入文件夹名称", default_text="新建文件夹")
```

节点阻塞式，调用后暂停代码执行直到用户关闭。

### 6.2 NotifyOverlay — 通知横幅

屏幕上方居中通知，非阻塞，自动消失。适合操作反馈、状态提示。

```python
from xiaoe_ui import NotifyOverlay

# 设置 Y 轴位置（屏幕高度占比）
NotifyOverlay.default_y_cb = lambda sh: int(sh * config.get("tz_y"))

notify = NotifyOverlay(
    hide_after=3,        # 默认自动隐藏秒数
    text_font_size=16,   # 字号
)

# 单行通知，默认时长
notify.show("操作成功")

# 自定义超时秒数
notify.show("快速提示", hide_after=0.5)    # 0.5 秒消失
notify.show("重要通知", hide_after=8)      # 8 秒停留

# 多行文本
notify.show("第一行\n第二行\n第三行")
```

### 6.3 TopBoxWindow — 透明悬浮窗

最底层的透明置顶窗口，QPainter 自由绘制。NotifyOverlay 基于它构建。

外观全部通过类级回调控制，主题切换时自动生效：

```python
from xiaoe_ui import TopBoxWindow

# 全局外观（仅需设置一次）
TopBoxWindow.default_color_cb = lambda: (255, 255, 0, 220)          # 线框颜色
TopBoxWindow.default_text_color_cb = lambda: (255, 255, 255, 220)   # 文字颜色
TopBoxWindow.default_text_bg_cb = lambda: (0, 0, 0, 80)             # 文字背景

win = TopBoxWindow(line_width=2, text_font_size=18)

# 矩形框
win.show_box(box=(100, 100, 300, 200))

# 对角线 — "l" 左上→右下, "r" 右上→左下, "lr" 双线
win.show_box(box=(100, 100, 300, 200), diagonal="lr")

# 显示文字（字号默认取 text_font_size，adjustSize 自适应）
win.show_text("hello", box=(100, 100, 300, 200), hide_after=3)

# 文字+边框
win.show_text("hello", box=(100, 100, 300, 200), show_box=True)

# 自定义 QPainter 绘制
def draw_cross(painter, rect):
    painter.drawLine(rect.topLeft(), rect.bottomRight())
    painter.drawLine(rect.topRight(), rect.bottomLeft())

win = TopBoxWindow(custom_draw=draw_cross)
win.show_box(box=(100, 100, 300, 200))
```

### 6.4 Msg — 线程安全日志

线程安全的消息管道，跨线程自动投递到 Qt 主线程。支持 info/ok/warn/err 四种级别。

```python
from xiaoe_ui import Msg

msg = Msg()

# 任意线程可直接调用
msg.info("服务器已启动")
msg.ok("文件保存成功")
msg.warn("内存使用率超过 80%")
msg.err("连接超时")

# 连接 UI 展示
msg.new_msg.connect(log_text_edit.append)
```

典型用法：`QTextEdit` 做日志面板，`msg.new_msg` 信号一端连上，工作线程直接调 `msg.info(...)`。

---

## 7. 主题系统

### 7.1 它解决什么问题

写桌面应用时，颜色通常直接写死在代码或 QSS 里：

```python
btn.setStyleSheet("background: #ff6b9d; color: white;")
```

问题来了——想换个主题？改几十个文件。想给用户提供明暗切换？几乎不可能。

框架的解法：**把颜色从代码里抽出来，变成变量，存在 config 里。**

```
QSS 模板              config 当前值
(写样式，颜色用变量)     (存具体的色值)

"{{accent}}"     +     accent = (255,100,150)
          \              /
       make_style() 遍历替换
              ↓
    "rgb(255,100,150)"   ← 最终 CSS
              ↓
        窗口变色
```

换来三个好处：

1. **换主题不用改代码** — 改 config 里的值就行
2. **主题和样式解耦** — CSS 归 CSS，配色归 config，各改各的
3. **实时预览** — 拖滑块直接看到效果，不用重启

### 7.2 主题预设 vs 单独设置 — 同一条路

主题预设不是"另一套机制"——它只是给 config 批量赋值。

```
点"深空幽蓝"  →  一次性调了 20 个 config.set(变量, 值)  ← 批量覆盖
拖滑块         →  一次调了 1 个 config.set(变量, 值)    ← 单独微调
```

引擎不管你是谁改的，它只认 config 里的当前值。所以你可以先点"深空幽蓝"再手动微调按钮颜色，无缝衔接。

开发者视角：框架的 37 套内置主题是"参考模板"。你的用户审美不同？两种方式：

- **快捷方式**：挑一套接近的 → `apply_theme` → 单独微调几个变量
- **设计专属**：`add_theme` 创建你自己的配色方案 → 一键应用

> 引擎默认指向第一套主题作为默认值。直接在默认主题预设中设置值和调 `set_defaults` 效果一样——因为 `_defaults` 就是默认主题值的引用。想换默认主题？在 `get_defaults()` 之前调 `engine.set_default_theme("企业蓝")`。

### 7.3 怎么用

#### 7.3.1 固定三步 — 所有场景都必须做

引擎 → config（取引擎默认值）→ WinManager 注册。三步之后，你的 app 就接入主题系统了。

```python
from xiaoe_ui import StyleEngine, ConfigBridge, WinManager, resolve_static

# ① 创建引擎（内置 37 套主题 + 十几个变量 + QSS 模板）
engine = StyleEngine()
#    在这里可以自定义你的主题：add_theme / add_var / add_qss 等，详见下方 7.3.2
engine.set_internal_default("bg_image", resolve_static("xiaoe_ui/demo_static/background.png"))  # 背景图，可选

# ② 创建 config — 默认值从引擎获取，建议单独建实例不和业务 config 混用
_defaults = engine.get_defaults()           # 引擎的全部变量默认值
_defaults.update({"my_key": "my_value"})    # 如果你的 config 也存业务值，merge 进去（推荐你单独使用！）
theme_cfg = ConfigBridge(instance=YourConfigManager(default_config=_defaults))

# ③ 接入 WinManager — source 是回调，每次刷新取 config 最新值
WinManager.set_style_source(lambda: engine.make_style(theme_cfg))
WinManager.set_bg_source(lambda: engine.resolve_value(theme_cfg, "bg_image"))
WinManager.set_icon_source("xiaoe_ui/demo_static/default_ico.ico")  # 窗口图标（不归主题管理，纯设置窗口左上角图标）
```

#### 7.3.2 四种使用场景

以下是四种常见需求，按需叠加：

**场景一：只用内置的** — 加 ThemePage 让用户自主换主题

```python
from xiaoe_ui import ThemePage, apply_theme, WinManager

# 放上主题设置面板（一行代码自动生成）
ThemePage(page, engine=engine, config=theme_cfg,
          on_style_changed=WinManager.apply_style_all)

# 或者一行代码切换
apply_theme("深空幽蓝", theme_cfg)
WinManager.apply_style_all()
```

**场景二：加一套自定义配色** — `add_theme` 两层都是 update：组存在则追加，同名覆盖，异名追加

```python
engine.add_theme(
    "品牌",          # 分组名 — ThemePage 里显示的 tab
    "企业蓝",        # 主题名
    {
        "config_background": (245, 248, 255),
        "config_elem_color_1": (30, 100, 200),
        # 只写想覆盖的变量，其余自动用默认值
    }
)
# 换成 set_themes({...}) 则清空全部内置主题
```

效果：ThemePage 多一个”品牌”分组，里面有”企业蓝”按钮。

> 引擎默认取第一套主题作为默认值。想换默认主题？在 `get_defaults()` 之前调 `engine.set_default_theme("企业蓝")`，否则 config 拿到的还是旧默认值。

**场景三：加一个新变量** — 让新控件颜色也能随主题变化。`add_var` 两层也是 update

```python
from xiaoe_ui import ThemeVar

# ① 注册变量
engine.add_var(
    "表格", "table_stripe",
    ThemeVar(label="斑马线色", widget="color", desc="表格斑马纹行颜色",
             transform=lambda v: f"rgb({v[0]},{v[1]},{v[2]})"),
)
# 换成 set_vars({...}) 则清空全部内置变量

# ② 写用到它的 QSS
engine.add_qss("QTableWidget::item:alternate { background: {{table_stripe}}; }")
# 换成 set_qss("...") 则清空全部内置 QSS

# ③ 给默认值。也可直接在默认主题预设里写入该变量，效果和 set_defaults 一样
engine.set_defaults(table_stripe=(240, 245, 250))
```

效果：ThemePage 自动多出”表格”分组，QSS 里的 `{{table_stripe}}` 自动参与替换。

**场景四：全部自己设计** — `set_*` 清空全部内置，从头写

```python
from xiaoe_ui import StyleEngine, resolve_static, ThemeVar

engine = StyleEngine()

engine.set_vars({
    "配色": {
        "bg": ThemeVar(label="背景", widget="color", desc="背景色", transform=...),
        "accent": ThemeVar(label="强调", widget="color", desc="强调色", transform=...),
    },
    "图片": {
        "header_img": ThemeVar(label="顶栏背景图", widget="image", desc="顶栏背景图",
                               transform=lambda p: f"image: url('{p}');" if p else ""),
    },
})

engine.set_themes({
    "风格": {
        "明亮": {"bg": (255,255,255), "accent": (0,120,255), "header_img": None},
        "暗黑": {"bg": (30,30,30),   "accent": (0,180,255), "header_img": None},
    }
})

# 示例路径，换成你自己的图片即可
engine.set_internal_default("header_img", resolve_static("xiaoe_ui/demo_static/background.png"))
engine.set_qss("QWidget { background: {{bg}}; } QPushButton { background: {{accent}}; }"
               "#header { {{header_img}} }")
```

> “明亮”在这组第一个位置，所以是默认值。想让”暗黑”作为默认？`engine.set_default_theme("暗黑")`。

之后仍走 7.3.1 的 config + WinManager 三步，数据链路一致。

#### 7.3.3 图片变量

图片变量 (`bg_image` / `check_img`) 默认值为 `None`——表示"未设置"。值为 `None` 时，引擎会尝试用 `set_internal_default()` 注册的内部默认路径解析实际文件：

- **`check_img`**（复选框图标）：框架已内置默认图标（`xiaoe_ui/static/yes.png`），用户即使不设置也能正常显示勾选效果。
- **`bg_image`**（背景图）：需要你手动注册一张默认图（demo 就是这样做的），否则不显示背景：

```python
from xiaoe_ui import resolve_static

engine.set_internal_default("bg_image", resolve_static("xiaoe_ui/demo_static/background.png"))  # 用户未设置时使用的默认图
```

用户在 ThemePage 中更换图片后，新值会覆盖你的默认设置；设为 `None` 会回到内部默认图。

> 注意：若某图片变量既没设值、又没注册内部默认路径，而你的自定义 QSS 里又引用了它，`make_style()` 会抛 `KeyError`（与普通变量行为一致）。

自定义图片变量和其他变量一样走 `add_var`，只是 `widget="image"`，上面场景四中的 `header_img` 就是一个完整例子。

### 7.4 框架提供的内置变量和主题

#### 37 套内置主题

| 分类 | 主题名 |
|------|--------|
| 默认 | 小娥樱花 |
| 亮色主题 | 清晨薄雾 薄荷晨露 秋日暖阳 淡紫薰衣 宁静海洋 森林绿意 柔光灰蓝 樱花浅粉 极简银灰 琥珀时光 科技蓝光 |
| 暗色主题 | 深空幽蓝 暗夜星辰 墨绿森林 暗金奢华 深紫星空 暗红古典 暗夜科技 石墨灰 |
| 明亮炫彩 | 糖果乐园 彩虹幻想 夏日海洋 热带雨林 阳光沙滩 马卡龙甜点 霓虹未来 电光紫蓝 水果乐园 彩虹之梦 泡泡糖乐园 彩虹糖果 |
| 暗黑炫彩 | 霓虹炫彩 梦幻渐变 海洋之心 日落黄昏 赛博朋克 |

#### 内置变量

引擎内置 27 个变量，分 8 组。默认值取自"小娥樱花"主题：

| 分组 | 变量名 | 含义 | 控件 | 默认值 |
|------|--------|------|------|--------|
| 透明度 | `widget_alpha` | 背景前元素模糊度 | Slider(0.0~1.0) | 0 |
| | `block_alpha` | 配置块模糊度 | Slider(0.0~1.0) | 0.85 |
| 图片 | `bg_image` | 背景图片 | 图片选择 | None (1) |
| | `check_img` | 复选框勾选图标 | 图片选择 | None (2) |
| 主题颜色 | `config_background` | 内容区背景色 | 颜色选择 | (255, 246, 246) |
| | `config_title_color` | 区块主标题颜色 | 颜色选择 | (255, 154, 162) |
| | `config_item_title_color` | 配置项标题颜色 | 颜色选择 | (122, 91, 96) |
| | `config_elem_color_1` | 组件默认态 | 颜色选择 | (255, 154, 162) |
| | `config_elem_color_2` | 组件鼠标悬停 | 颜色选择 | (255, 182, 193) |
| | `config_elem_color_3` | 组件鼠标按下/闪烁 | 颜色选择 | (255, 125, 135) |
| | `top_win_default_main_color` | 悬浮窗边框/文字色 | 颜色选择 | (255, 120, 180) |
| 表单颜色 | `status_edited` | 编辑中状态边框色 | 颜色选择 | (255, 165, 0) |
| | `status_success` | 成功状态边框色 | 颜色选择 | (0, 200, 83) |
| | `status_error` | 错误状态边框色 | 颜色选择 | (213, 0, 0) |
| 字体 | `app_font` | 应用全局字体 | 字体选择 | Microsoft YaHei |
| | `default_text_size` | 基础文字大小 | Slider | 12pt |
| | `section_title_size` | 区块标题大小 | Slider | 18px |
| | `tip_text_size` | 提示文字大小 | Slider | 12px |
| 容器边框 | `block_border_radius` | 容器圆角 | Slider | 3px |
| | `block_border_width` | 容器边框宽度 | Slider | 1px |
| 按钮边框 | `reaction_border_radius` | 按钮圆角 | Slider | 5px |
| | `reaction_small_border_radius` | 小按钮圆角 | Slider | 5px |
| | `reaction_default_border_width` | 默认边框宽度 | Slider | 1px |
| | `reaction_2x_border_width` | 双倍边框宽度 | Slider | 2px |
| | `reaction_4x_border_width` | 四倍边框宽度 | Slider | 4px |
| 文本组件边框 | `edit_border_radius` | 输入框圆角 | Slider | 4px |
| | `edit_border_width` | 输入框边框宽度 | Slider | 2px |

### 7.5 ThemePage — 自动主题设置页

直接在你的 app 里调用，即可自动生成一个让用户自定义外观的专业设置界面。滑块/颜色变量自动变成 `SliderItem` / `ColorItem`，字体/图片变量变成 `BottomItem`，按分组排列。

```python
from xiaoe_ui import ThemePage, WinManager

page = left.add_page("theme", "主题设置", icon="🎨")
ThemePage(page, engine=engine, config=theme_cfg,
          on_style_changed=WinManager.apply_style_all,  # 每次改值 → 刷新全部窗口
          on_theme_selected=lambda name, vals: ...,     # 自定义主题应用逻辑（可选）
          show_description=True)                         # 显示变量说明
```

`on_theme_selected` 提供时**取代**默认行为，回调拿到 `(theme_name, merged_values)`。不提供则默认只写主题自有值（`get_theme_raw`），不会覆盖主题未定义的变量。

效果：透明度滑块 + 背景图片选择 + 字体选择 + 10 个颜色选择器 + 37 套主题预设下拉，全部自动生成。你在主题系统中自定义的变量也能在这里自动识别展示。

**自定义主题**：设置页还有一行"自定主题"下拉——把当前所有变量值保存为一个自定义主题（数据存于 `config["custom_themes"]`），支持新增、删除、拖拽排序，可随时一键应用。注意 `engine.get_defaults()` 会额外返回一个 `custom_themes` 键；若你把默认值整体 merge 进业务 config，需要留意不要和业务键冲突。

---

## 8. 热键绑定

依赖 [xiaoe_keyboard](https://pypi.org/project/xiaoe-keyboard/) 库，提供全局热键绑定 + 长按检测 + UI 配置项。详细用法见 [xiaoe_keyboard 文档](https://pypi.org/project/xiaoe-keyboard/)。

### 8.1 安装（安装框架时会自动安装）

```bash
pip install xiaoe_keyboard
```

### 8.2 基本用法

```python
from typing import List
from xiaoe_keyboard import Keyboard, HotkeyType
from xiaoe_ui import ConfigBridge, KeyItem, run_in_main

# ① 创建热键专用 config（持久化用户设置的键位）
key_cfg = ConfigBridge(instance=KeyConfig(       # 你的配置管理器
    default_config={
        "screenshot": ["Q"],                     # 默认键位
        "quick_search": ["ctrl_l", "F"],         # 默认组合键
        "translate": ["T"],                     # 默认翻译键
    }
))

# ② 定义热键列表 — value 从 config 读取，set() 兜底
hotkey_list: List[HotkeyType] = [
    {
        "name": "screenshot",
        "value": set(key_cfg.get("screenshot")),         # 单键
        "down_fun": lambda: take_screenshot(),
    },
    {
        "name": "quick_search",
        "value": set(key_cfg.get("quick_search")),       # 组合键 {"ctrl_l", "F"}
        "down_fun": lambda: open_search(),
    },
    {
        "name": "translate",
        "value": set(key_cfg.get("translate")),          # 按下 + 松开的例子
        "down_fun": lambda: print("开始翻译"),            # 按下触发
        "up_fun":   lambda: print("翻译完成"),            # 松手触发
    },
]

# ③ 创建键盘管理器 — 回调建议投递到主线程
kb = Keyboard(
    hotkey_list,
    save_fun=lambda name, value: key_cfg.set(name, list(value)),
    run_fun_callback=run_in_main,           # 回调投递到主线程
)

# ④ 添加 UI 配置项
KeyItem("截图热键", config=key_cfg, config_name="screenshot",
        text="点击设置快捷键", keyboard=kb, parent_layout=page)
KeyItem("搜索热键", config=key_cfg, config_name="quick_search",
        text="组合键 Ctrl+F 搜索", keyboard=kb, parent_layout=page)
KeyItem("翻译热键", config=key_cfg, config_name="translate",
        text="按下翻译，松手完成", keyboard=kb, parent_layout=page)
```

**键位格式**: `value` 是 `set` 类型。单键 `{"Q"}`，组合键 `{"ctrl_l", "F"}`。支持鼠标按键 `mouse_left`、`mouse_right` 等。

**KeyItem 右键菜单**: 设置按钮上右键 → 解绑 / 重置 / 取消。

### 8.3 长按检测

`LongPressDetector` 是框架内置工具（顶层导出，`from xiaoe_ui import LongPressDetector`），用于区分钟按和长按。套路和 8.2 一样，`down_fun` 启动长按计时，`up_fun` 在松手时判断长/短按：

```python
from typing import List
from xiaoe_keyboard import Keyboard, HotkeyType
from xiaoe_ui import ConfigBridge, KeyItem, run_in_main
from xiaoe_ui import LongPressDetector

# ① 创建 config — 和 8.2 一样，此处省略 key_cfg 创建代码
key_cfg = ConfigBridge(instance=KeyConfig(
    default_config={"long_press_demo": ["R"]}
))

# ② 创建长按检测器
lp = LongPressDetector()

# ③ 定义热键 — down_fun 启动计时，up_fun 松手判定
hotkey_list: List[HotkeyType] = [
    {
        "name": "long_press_demo",
        "value": set(key_cfg.get("long_press_demo")),
        "down_fun": lambda: lp.key_down("demo", 1.0,             # 按下 → 启动 1 秒计时
                                       lambda: print("长按 1 秒触发")),
        "up_fun":   lambda: lp.key_up("demo",                    # 松手 → 未满 1 秒 = 短按
                                       lambda: print("松手，短按")),
    },
]

# ④ 创建 Keyboard + UI
kb = Keyboard(hotkey_list,
              save_fun=lambda name, value: key_cfg.set(name, list(value)),
              run_fun_callback=run_in_main)
KeyItem("长按热键", config=key_cfg, config_name="long_press_demo",
        text="长按 1 秒触发，短按松手触发", keyboard=kb, parent_layout=page)
```

### 8.4 KeyboardUI — 一键接入框架的全局鼠标钩子

`KeyboardUI`（`xiaoe_ui.utils.xiaoe_keyboard_with_ui`）是 `xiaoe_keyboard.Keyboard` 的子类，构造时自动把 `mouse_hook_func` 接到框架的全局鼠标钩子（见 [9 节](#9-工具函数)的 mouse_manage）。这样鼠标键热键（如 `mouse_left`、`mouse_right`）会与 ClickThroughMixin 的穿透交互**共用同一个全局钩子，互不冲突**。

```python
from xiaoe_ui import KeyboardUI, KeyItem, run_in_main

kb = KeyboardUI(
    hotkey_list,                             # 和 8.2 一样的热键列表
    save_fun=lambda name, value: key_cfg.set(name, list(value)),
    run_fun_callback=run_in_main,
    is_read_mouse=True,                      # 开启鼠标按键作为热键
)
KeyItem("截图热键", config=key_cfg, config_name="screenshot",
        keyboard=kb, parent_layout=page)
```

其余参数和用法与 8.2 的 `Keyboard` 完全一致。

---

## 9. 工具函数

### run_in_main / run_in_main_block — 线程调度

Qt 要求所有 UI 操作在主线程执行。这些函数将回调和返回值安全地投递到主线程。

```python
from xiaoe_ui import run_in_main, run_in_main_block, in_main, in_main_block

# 异步投递：不阻塞调用线程，立即返回
run_in_main(lambda: label.setText("更新完成"))

# 同步投递：阻塞等待主线程执行完毕，返回结果
result = run_in_main_block(lambda: heavy_computation())

# 装饰器 —— 异步版本
@in_main
def update_ui(text):
    label.setText(text)

# 装饰器 —— 同步版本
@in_main_block
def read_config(key):
    return config.get(key)
```

异步适合"通知 UI 更新"，同步适合"从主线程读取数据后继续计算"。工作线程直接调，不用关心 Qt 事件循环。

### flash_style — 强制样式刷新

Qt 不会自动检测 `setProperty()` 后的 QSS 变化。调此函数强制重算。

```python
from xiaoe_ui import flash_style

widget.setProperty("status", "success")
flash_style(widget)  # 立即应用 QSS 中 [status="success"] 的样式
```

### resize_elem / de_resize_elem — 分辨率缩放

以 1920×1080 为基准等比缩放像素值，适配不同分辨率。你在代码里写 1080p 下的 px 值，它自动换算成当前屏幕的实际像素。`de_resize_elem` 是逆运算。

```python
from xiaoe_ui import resize_elem, de_resize_elem

w = resize_elem(100)    # 1080p 下 100px → 当前屏幕的实际 px
h = de_resize_elem(50)  # 实际 px → 1080p 下的等效 px
```

大多数情况 Qt 会自动处理缩放，极少情况才需要手动调。框架内目前仅用于 MainWin 标题栏内边距自适应（`de_resize_elem(10)` 等）。

### resolve_static — 静态资源路径

解析相对项目根目录的资源路径，依次尝试：PyInstaller 打包后的 `sys._MEIPASS` / `sys._internal` → 当前工作目录 → 包内回退（`site-packages/xiaoe_ui`）。三个位置都找不到时抛 `FileNotFoundError`。

```python
from xiaoe_ui import resolve_static
path = resolve_static("xiaoe_ui/demo_static/background.png")
```

### get_short_path — 路径截断

长路径中间截断，保留首尾。

```python
from xiaoe_ui import get_short_path
get_short_path("E:/very/long/path/to/file.png", max_len=25)
# → "E:/.../file.png"
```

### to_china_text — 界面中文翻译

让 Qt 内置控件（对话框按钮、右键菜单、日期选择器等）显示中文。**框架不会自动调用，需要你在应用里自行执行**：

```python
from PySide6.QtWidgets import QApplication
from xiaoe_ui import to_china_text

app = QApplication(sys.argv)
to_china_text(app, "translations")   # 在创建主窗口之前调用
```

- `trans_dir`：`.qm` 翻译文件所在目录。开发时通常解析不到，自动回退到 PySide6 自带的翻译路径；打包后指向包内的 `translations/`。
- **打包注意**：`.qm` 翻译文件默认不会自动进 exe，必须把 `get_china_qm_file_list_map_to_spec()` 的返回值加进 spec 的 `datas` 才会随包分发——见[第 10 节 打包发布](#10-打包发布-pyinstaller)。

### mouse_manage — 全局鼠标钩子

`xiaoe_ui.utils.mouse_manage` 是全局鼠标钩子的**中央分发器**：模块加载时只安装一次 `mouse.hook`，各子系统通过 `resign_mouse_callback(func)` 注册回调、`unresign_mouse_callback(func)` 注销回调，共用一个钩子，避免互相覆盖。

```python
from xiaoe_ui import resign_mouse_callback, unresign_mouse_callback

resign_mouse_callback(lambda e: print("全局鼠标事件", e))
```

框架内部的两处使用：
- **ClickThroughMixin**（穿透窗口交互）：`start_mouse_hook()` 注册、`stop_mouse_hook()` 注销（见 5.6）
- **KeyboardUI**（鼠标键热键）：构造时把 `mouse_hook_func` 接到这里（见 8.4）

> 副作用提醒：`import xiaoe_ui` 顶层就会导入本模块，因此**只要导入框架，全局鼠标钩子就会装上**。

### 其它小工具

- `clear_layout(layout)` — 递归清空一个 QLayout 的所有项（`from xiaoe_ui import clear_layout`）
- `font_picker_dialog(default_family=...)` — 字体选择弹窗，返回选中字体族或 `None`（`from xiaoe_ui import font_picker_dialog`）
- `set_item_margins((l, t, r, b))` — 修改全局配置项内边距（`from xiaoe_ui import set_item_margins`）
- `title_min_width(chars=8)` — 配置项标题最小宽度，按字符数换算（`from xiaoe_ui import title_min_width`）
- `empty_frame(width, is_H=False, class_text="block")` — 定宽/定高的空白占位块（`from xiaoe_ui import empty_frame`）
- `get_china_qm_file_list_map_to_spec()` — 打包时收集 PySide6 中文 `.qm`（见[第 10 节 打包发布](#10-打包发布-pyinstaller)）；`to_china_text` 见上方独立小节
- `get_static_files_to_spec()` — 返回静态资源清单，供 PyInstaller spec 使用

---

## 10. 打包发布 (PyInstaller)

打包 exe 时，框架的静态资源需要显式收集进 `datas`。用两个工具函数生成清单：

```python
import xiaoe_ui

a = Analysis(
    ['your_app.py'],
    datas=[
        *xiaoe_ui.get_static_files_to_spec(),             # 框架内置资源
        *xiaoe_ui.get_china_qm_file_list_map_to_spec(),   # PySide6 中文翻译
    ],
    hiddenimports=['mouse'],     # 用了穿透窗口/鼠标热键则必加
    ...
)
```

### 10.1 get_static_files_to_spec — 框架内置资源

`from xiaoe_ui import get_static_files_to_spec`，返回 `datas` 清单，**只包含框架自带的资源**：

- `xiaoe_ui/static/` — 框架内置图标（如 `yes.png`）
- `xiaoe_ui/demo_static/` — demo 用背景图 / 图标
- `xiaoe_ui/theme/global_style.qss` — 主题 QSS 模板

> 注意：它**不包含你自行新增**的图片/图标/QSS，这些需要你自己额外加进 `datas`；`demo_static/` 是 demo 专用资源，不需要的话可只保留 `static/` 和 QSS 两项。

### 10.2 get_china_qm_file_list_map_to_spec — 中文翻译

`from xiaoe_ui import get_china_qm_file_list_map_to_spec`，自动搜集 PySide6 的中文翻译 `.qm`（`qt_zh_CN.qm`、`qtbase_zh_CN.qm` 等）到包内 `translations/` 目录。运行时配合 `to_china_text(app, "translations")` 加载界面中文（调用方式见[第 9 节 工具函数](#9-工具函数)）。

### 10.3 资源路径

打包后 `resolve_static()` 经 `sys._MEIPASS` / `sys._internal` 自动定位资源，背景图/图标/主题 QSS 的代码无需改动。

---

## 11. 附录: 架构树

```
xiaoe_ui/
├── core/                # 窗口/管理
│   ├── win_manager.py       # WinManager: 样式+背景+图标三者解耦 + 实例注册
│   ├── main_win.py          # MainWin / MainWinOpenGL: 主窗口基类
│   ├── dialog.py            # Dialog: 对话框基类
│   ├── frameless_win.py     # FramelessWin / FramelessWinOpenGL
│   ├── click_through.py     # ClickThroughMixin: 穿透窗口交互混入
│   ├── singleton_mixin.py   # SingletonMixin: 单例窗口混入
│   ├── wallpaper_win.py     # WallpaperWinMixin: 壁纸模式混入
│   ├── layout.py            # MainLayout: 双栏布局
│   ├── top_win.py           # TopBoxWindow / TopBoxWindowOpenGL
│   └── notify.py            # NotifyOverlay: 通知横幅
├── config/
│   └── bridge.py            # ConfigBridge: 配置桥接 + value_changed + on/off + memory
├── nav/
│   └── left_list.py         # LeftList / LeftGroup: 侧栏导航
├── theme/
│   ├── engine.py            # StyleEngine: 主题引擎 (QSS+变量+预设+默认值)
│   ├── defaults.py          # ThemeVar + 内置变量注册表 + 37套预设主题
│   ├── style.py             # make_style / apply_theme 便捷函数
│   ├── global_style.qss     # QSS 模板
│   └── theme_page.py        # ThemePage: 自动生成主题设置页
├── widgets/
│   ├── item.py              # L3 配置项: HideItem/CheckItem/ComboItem/SliderItem/ColorItem/
│   │                        #   BottomItem/KeyItem/GradientItem + make_line/make_tip
│   ├── entry.py             # L2 config绑定: SpinEntry/TextEntry/MultiEntry/
│   │                        #   ImagePicker/DatePicker/ColorEntry/SliderEntry/
│   │                        #   CheckEntry/ComboEntry
│   ├── basic.py             # HandCursorMixin / IgnoreWheelMixin / flash_style
│   ├── use_mixin_fast_widget.py # QPushButtonHandCursor/QCheckBoxHandCursor/
│   │                        #   CustomComboBox/CustomSlider/InstantTipLabel/InstantTipButton
│   ├── spin_box.py          # L1 CustomSpinBox: StatusLineEdit + ▲/▼ 长按连发
│   ├── gradient.py          # L1 GradientBar: QPainter 渐变条 + 拖拽色标
│   ├── click_frame.py       # ClickFrame/BigButton
│   ├── instant_tip.py       # _TooltipPopup / InstantTooltipMixin
│   ├── a_box.py             # ABox 动画显隐容器
│   ├── status_widgets.py    # StatusLineEdit/StatusDateEdit/StatusTextEdit/
│   │                        #   StatusImagePicker/ColorPickerButton/DateTimePickerDialog
│   ├── form_layout.py       # make_form_row: [标题] [组件] 表单行
│   └── theme_btn.py         # ThemeChoiceButton/ThemePopup
├── utils/
│   ├── static_path.py       # resolve_static: 通用静态资源解析 (PyInstaller兼容)
│   ├── msg_box.py           # MsgBox: ask/info/warn/error/input_dialog
│   ├── font_picker.py       # font_picker_dialog: 自定义字体选择弹窗
│   ├── wallpaper_tools.py   # set_windows_as_wallpaper: Win32 壁纸层
│   ├── msg.py               # Msg: 线程安全日志
│   ├── qt_run.py            # run_in_main/run_in_main_block/in_main/in_main_block
│   ├── long_press.py        # LongPressDetector
│   ├── get_short_path.py    # get_short_path: 路径截断显示
│   ├── dpi.py               # resize_elem/de_resize_elem/title_min_width
│   ├── clear_layout.py      # clear_layout: 递归清空布局
│   ├── create_empty_frame.py# empty_frame: 定宽/定高占位块
│   ├── get_static_files_to_spec.py # get_static_files_to_spec: 静态资源收集 (PyInstaller spec)
│   ├── mouse_manage.py      # 全局鼠标钩子分发（resign/unresign_mouse_callback）
│   ├── to_china_text.py     # to_china_text: 应用中文翻译 (QTranslator)
│   └── xiaoe_keyboard_with_ui.py # KeyboardUI: 热键+UI 封装
├── static/                  # 框架内置图标
├── demo_static/             # demo 用背景/图标
├── demo/                    # 完整演示 (demo 子包)
│   ├── __init__.py          # 启动入口 (xiaoe_ui-demo / python -m xiaoe_ui.demo)
│   ├── _demo_configs.py     # ConfigBridge + 引擎组装
│   ├── app.py               # DemoApp 主窗口
│   ├── about_demo.py        # 关于页
│   ├── home.py              # 首页
│   ├── theme_demo.py        # 主题设置页
│   ├── widgets_demo.py      # 配置控件演示
│   ├── form_demo.py         # L2 表单 Entry 演示
│   ├── click_demo.py        # ClickFrame/BigButton/InstantTip 演示
│   ├── click_through_demo.py# 穿透窗口演示 (FramelessWin + ClickThroughMixin)
│   ├── dialog_demo.py       # Dialog/MsgBox 演示
│   ├── jump_demo.py         # 侧栏跳转 + 闪烁演示
│   ├── key_demo.py          # 热键绑定演示
│   ├── log_demo.py          # Msg 日志管道演示
│   ├── main_win_demo.py     # MainWin 变体/单例/侧栏演示
│   ├── notify_demo.py       # NotifyOverlay 通知演示
│   ├── overlay_demo.py      # TopBoxWindow 悬浮窗演示
│   ├── sync_demo.py         # 配置同步演示
│   └── callback_demo.py     # 纯 callback 模式演示
└── demo.py                  # pip 入口 (转发 demo 包 main)
```
