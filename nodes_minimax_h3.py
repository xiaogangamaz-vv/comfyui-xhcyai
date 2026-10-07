"""XHCY AI video node — MiniMax H3 family, text-to-video.

Plain text-to-video. Related nodes:
    * nodes_minimax_h3_frames.py  - first/last frame driven
    * nodes_minimax_h3_ref.py     - image / video / audio reference driven
"""

from __future__ import annotations

try:
    from .xhcy_video_base import XHCYVideoBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_video_base import XHCYVideoBase  # type: ignore


_H3_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
_LITE_RATIOS = ["adaptive", "16:9", "9:16", "1:1"]


class XHCYMiniMaxH3(XHCYVideoBase):
    """MiniMax H3 family — text-to-video."""

    VARIANT_MODELS = ["MiniMax-H3", "MiniMax-H3-Max", "MiniMax-H3-Lite"]

    RESOLUTION_LIMITS = {
        "MiniMax-H3": ["768P", "2K"],
        "MiniMax-H3-Max": ["768P", "480P"],
        "MiniMax-H3-Lite": ["768P", "480P"],
    }
    RATIO_LIMITS = {
        "MiniMax-H3": _H3_RATIOS,
        "MiniMax-H3-Max": _H3_RATIOS,
        "MiniMax-H3-Lite": _LITE_RATIOS,
    }
    DURATION_LIMITS = {
        "MiniMax-H3": (4, 15),
        "MiniMax-H3-Max": (5, 15),
        "MiniMax-H3-Lite": (1, 15),
    }

    DEFAULT_MODEL = "MiniMax-H3"
    DEFAULT_RESOLUTION = "768P"
    DEFAULT_DURATION = 5
    DEFAULT_RATIO = "16:9"
    NODE_ID = "xhcy_minimax_h3"
    OUTPUT_PREFIX = "xhcy_minimax_h3"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = "XHCY AI · MiniMax H3 家族文生视频（MiniMax-H3 / -Max / -Lite）"


NODE_CLASS_MAPPINGS = {
    "xhcy_minimax_h3": XHCYMiniMaxH3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_minimax_h3": "XHCY MiniMax H3（文生视频）",
}
