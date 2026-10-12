"""MiniMax H3 家族规格表。

数据来源：`GET https://ai.xhcyai.org/api/video/models`（2026-10-12 实测）。
三个 H3 节点（文生 / 首尾帧 / 多模态参考）共用这一份，改参数只需改这里。

站点在 2026-10-12 调整过规格：
    * MiniMax-H3 的分辨率由「768P / 2K」变为 **480P / 768P / 1080P**
    * MiniMax-H3 的时长上限由 15 秒放宽到 **30 秒**（超过 15 秒生成与素材费用翻倍）
    * MiniMax-H3 新增模式：`regeneration_768p_to_2k`、`context_ir`
    * 出现了 MiniMax-H3-Lite（480P / 768P，1–15 秒，无再生成/Context-IR）
    * MiniMax-H3-Max 不在 model 广场列表里，但密钥仍可调用，故按旧规格保留
"""

from __future__ import annotations

MODELS = ["MiniMax-H3", "MiniMax-H3-Max", "MiniMax-H3-Lite"]

# 站点给的比例（H3 与 Max 一致）
_FULL_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
_LITE_RATIOS = ["adaptive", "16:9", "9:16", "1:1"]

RESOLUTION_LIMITS = {
    "MiniMax-H3": ["480P", "768P", "1080P"],
    "MiniMax-H3-Max": ["768P", "480P"],
    "MiniMax-H3-Lite": ["480P", "768P"],
}

DURATION_LIMITS = {
    "MiniMax-H3": (4, 30),
    "MiniMax-H3-Max": (5, 15),
    "MiniMax-H3-Lite": (1, 15),
}

RATIO_LIMITS = {
    "MiniMax-H3": _FULL_RATIOS,
    "MiniMax-H3-Max": _FULL_RATIOS,
    "MiniMax-H3-Lite": _LITE_RATIOS,
}

# 各模型开放的生成模式（暂时只用于提示，节点按功能拆分）
MODES = {
    "MiniMax-H3": ["text", "first_last_frame", "reference", "regeneration_768p_to_2k", "context_ir"],
    "MiniMax-H3-Max": ["text", "first_last_frame", "reference"],
    "MiniMax-H3-Lite": ["text", "first_last_frame", "reference"],
}

# 素材数量上限（站点给出）
REFERENCE_LIMITS = {
    "MiniMax-H3": {"reference_images": 9, "reference_videos": 3, "reference_audio": 3, "mixed_media": 12},
    "MiniMax-H3-Max": {"reference_images": 9, "reference_videos": 3, "reference_audio": 3, "mixed_media": 12},
    "MiniMax-H3-Lite": {"reference_images": 9, "reference_audio": 3},
}

# 下拉里出现的全部候选（各模型取并集；某个模型具体能不能用由 RESOLUTION_LIMITS 判定）
RESOLUTIONS = ["480P", "768P", "1080P"]
RATIOS = _FULL_RATIOS

DEFAULT_MODEL = "MiniMax-H3"
DEFAULT_RESOLUTION = "768P"
DEFAULT_DURATION = 5
DEFAULT_RATIO = "16:9"
