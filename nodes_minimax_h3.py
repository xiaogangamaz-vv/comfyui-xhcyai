"""XHCY AI video node — MiniMax H3 family, text-to-video.

规格（分辨率 / 时长 / 比例）统一放在 xhcy_h3_specs.py，三个 H3 节点共用。

相关节点：
    * nodes_minimax_h3_frames.py  - 首尾帧 / 图生视频
    * nodes_minimax_h3_ref.py     - 图片 / 视频 / 音频参考
"""

from __future__ import annotations

try:
    from .xhcy_h3_specs import (
        DEFAULT_DURATION as _DEFAULT_DURATION,
    )
    from .xhcy_h3_specs import (
        DEFAULT_MODEL as _DEFAULT_MODEL,
    )
    from .xhcy_h3_specs import (
        DEFAULT_RATIO as _DEFAULT_RATIO,
    )
    from .xhcy_h3_specs import (
        DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION,
    )
    from .xhcy_h3_specs import (
        DURATION_LIMITS as _DURATION_LIMITS,
    )
    from .xhcy_h3_specs import (
        MODELS as _MODELS,
    )
    from .xhcy_h3_specs import (
        RATIO_LIMITS as _RATIO_LIMITS,
    )
    from .xhcy_h3_specs import (
        RESOLUTION_LIMITS as _RESOLUTION_LIMITS,
    )
    from .xhcy_video_base import XHCYVideoBase
except ImportError:  # 允许单文件直接运行调试
    from xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION  # type: ignore
    from xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL  # type: ignore
    from xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO  # type: ignore
    from xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION  # type: ignore
    from xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS  # type: ignore
    from xhcy_h3_specs import MODELS as _MODELS  # type: ignore
    from xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS  # type: ignore
    from xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS  # type: ignore
    from xhcy_video_base import XHCYVideoBase  # type: ignore


class XHCYMiniMaxH3(XHCYVideoBase):
    """MiniMax H3 family — text-to-video."""

    VARIANT_MODELS = list(_MODELS)
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    RATIO_LIMITS = _RATIO_LIMITS
    DURATION_LIMITS = _DURATION_LIMITS

    DEFAULT_MODEL = _DEFAULT_MODEL
    DEFAULT_RESOLUTION = _DEFAULT_RESOLUTION
    DEFAULT_DURATION = _DEFAULT_DURATION
    DEFAULT_RATIO = _DEFAULT_RATIO
    NODE_ID = "xhcy_minimax_h3"
    OUTPUT_PREFIX = "xhcy_minimax_h3"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = "XHCY AI · MiniMax H3 家族文生视频（480P / 768P / 1080P）"


NODE_CLASS_MAPPINGS = {
    "xhcy_minimax_h3": XHCYMiniMaxH3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_minimax_h3": "XHCY MiniMax H3（文生视频）",
}
