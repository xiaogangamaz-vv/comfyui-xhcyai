"""Seedance 2.0（火山引擎方舟）的规格表。

数据来源：站点 `/api/video/models` 的返回（2026-10-21 实测），
以及后端文档 `docs/33-seedance-2-0-ark.md`。

三个变体
--------
    doubao-seedance-2-0        480P / 720P / 1080P / 4K     4–15 秒
    doubao-seedance-2-0-fast   480P / 720P                  4–15 秒
    doubao-seedance-2-0-mini   480P / 720P                  4–15 秒

⚠️ 注意分辨率的写法与 H3 不同：
    Seedance 用 **720P**（H3 是 768P）、**4K**（H3 是 2K）。
    别把两套表混用，站点会直接拒。

价格（按输出秒数，2026-10-21 站点公示）
-------------------------------------
                       480P        720P        1080P       4K


"""

from __future__ import annotations

MODELS = [
    "doubao-seedance-2-0",
    "doubao-seedance-2-0-fast",
    "doubao-seedance-2-0-mini",
]

# 各模型支持的分辨率（注意是 720P 与 4K，不是 768P / 2K）
RESOLUTION_LIMITS = {
    "doubao-seedance-2-0": ["480P", "720P", "1080P", "4K"],
    "doubao-seedance-2-0-fast": ["480P", "720P"],
    "doubao-seedance-2-0-mini": ["480P", "720P"],
}

# 三个变体都是 4–15 秒
DURATION_LIMITS = {
    "doubao-seedance-2-0": (4, 15),
    "doubao-seedance-2-0-fast": (4, 15),
    "doubao-seedance-2-0-mini": (4, 15),
}

# 7 种比例（adaptive 由服务端决定）
RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
RATIO_LIMITS = {model: list(RATIOS) for model in MODELS}

DEFAULT_MODEL = "doubao-seedance-2-0"
DEFAULT_RESOLUTION = "720P"
DEFAULT_DURATION = 5
DEFAULT_RATIO = "16:9"

# 素材上限（站点 limits 字段）
MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3

# 首帧/尾帧（IMAGE），与参考素材互斥
HAS_FRAME_INPUTS = True



