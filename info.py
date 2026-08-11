"""应用与作者信息，统一在此维护。"""

import os
import re

# 应用
APP_NAME = "RVC实时变声-小娥UI版"
APP_VERSION = "1.1.5"

# 适配的 RVC 打包版本（随 RVC 打包更新）
ADAPTED_RVC_VERSION = "RVC 20260718"

# 链接
RVC_GITHUB_URL = (
    "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI"
)
RVC_AUTHOR_BILIBILI_URL = "https://space.bilibili.com/5760446"
APP_GITHUB_URL = "https://github.com/sakura-0v0/xiaoe-rvc-ui"
AUTHOR_BILIBILI_URL = "https://space.bilibili.com/327250702"


def detect_rvc_version():
    """运行时识别当前 RVC 打包版本：从项目根目录名提取日期。

    例如目录 RVC20260718Nvidia → "RVC 20260718"。
    """
    rvc_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = re.search(r"(\d{8})", os.path.basename(rvc_root))
    return f"RVC {m.group(1)}" if m else "RVC（未识别）"
