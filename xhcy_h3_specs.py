"""MiniMax H3 家族规格表。

数据来源（2026-10-15 核对）：
    * ``GET https://ai.xhcyai.org/api/video/models``
    * 站点后端源码 ``relay/adaptor/minimax/video.go`` 里的 VideoResolutions /
      VideoDurationRange / AllowedVideoRatiosFor / VideoInputLimitsFor
三个 H3 节点（文生 / 首尾帧 / 多模态参考）共用这一份，改参数只需改这里。

站点当前（2026-10-15）的规格：

    MiniMax-H3          480P / 768P / 1080P / 2K    4–30 秒   7 种比例
    MiniMax-H3-Lite     480P / 768P                 1–15 秒   4 种比例

相比上一版有两点必须注意：
    * **MiniMax-H3-Max 已下线。** 后端 IsVideoModel 的白名单只有 H3 与
      H3-Lite，继续用 Max 会被直接拒绝（unsupported video model），
      所以它从下拉里移除了。
    * **H3 新增 2K 分辨率**，时长上限也从 15 秒放宽到 30 秒
      （站点注明：超过 15 秒时输出与素材费用翻倍）。

另有两条独立能力，走各自的接口，不由本文件的三个节点覆盖，见：
    * 768P→2K 再生成   ``POST /v1/video/regenerations``
    * Context-IR 增强  ``POST /v1/video/context-ir``
"""

from __future__ import annotations

# 后端白名单：只有这两个模型名是被承认的
MODELS = ["MiniMax-H3", "MiniMax-H3-Lite"]

_FULL_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
_LITE_RATIOS = ["adaptive", "16:9", "9:16", "1:1"]

RESOLUTION_LIMITS = {
    "MiniMax-H3": ["480P", "768P", "1080P", "2K"],
    "MiniMax-H3-Lite": ["480P", "768P"],
}

DURATION_LIMITS = {
    "MiniMax-H3": (4, 30),
    "MiniMax-H3-Lite": (1, 15),
}

RATIO_LIMITS = {
    "MiniMax-H3": _FULL_RATIOS,
    "MiniMax-H3-Lite": _LITE_RATIOS,
}

# 各模型开放的生成模式（仅用于提示；节点按功能拆分）
MODES = {
    "MiniMax-H3": ["text", "first_last_frame", "reference", "regeneration_768p_to_2k", "context_ir"],
    "MiniMax-H3-Lite": ["text", "first_last_frame", "reference"],
}

# 素材数量上限（站点给出）
REFERENCE_LIMITS = {
    "MiniMax-H3": {
        "reference_images": 9,
        "reference_videos": 3,
        "reference_audio": 3,
        "mixed_media": 12,
    },
    "MiniMax-H3-Lite": {
        "reference_images": 9,
        "reference_audio": 3,
        # 该档的首尾帧工作流要求首尾都给，且音频必须搭配至少一张图
        "first_last_frame_pair_required": 1,
        "audio_requires_image": 1,
    },
}

# 下拉候选的兜底值（正常路径由 XHCYVideoBase.all_resolutions() 取并集）
RESOLUTIONS = ["480P", "768P", "1080P", "2K"]
RATIOS = _FULL_RATIOS

DEFAULT_MODEL = "MiniMax-H3"
DEFAULT_RESOLUTION = "768P"
DEFAULT_DURATION = 5
DEFAULT_RATIO = "16:9"
