"""XHCY AI video node — MiniMax H3 family, first/last frame driven.

Connect first_frame, last_frame, or both: the video starts and/or ends on those
images. Verified against the live service — content entries use role
"first_frame" / "last_frame" carrying a base64 data URI.
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_video_base import XHCYVideoBase, image_tensor_to_uri
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_video_base import XHCYVideoBase, image_tensor_to_uri  # type: ignore


_H3_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
_LITE_RATIOS = ["adaptive", "16:9", "9:16", "1:1"]


class XHCYMiniMaxH3Frames(XHCYVideoBase):
    """MiniMax H3 family — first/last frame to video."""

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
    PROMPT_TOOLTIP = "描述画面怎么动起来。留空会直接报错，不会白白扣费。"
    NODE_ID = "xhcy_minimax_h3_frames"
    OUTPUT_PREFIX = "xhcy_h3_frames"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = "XHCY AI · MiniMax H3 首尾帧生视频（接 first_frame / last_frame）"

    @classmethod
    def material_inputs(cls):
        return {
            "first_frame": (
                "IMAGE",
                {"tooltip": "起始画面。只接这一张 = 以它为开头的图生视频。"},
            ),
            "last_frame": (
                "IMAGE",
                {"tooltip": "结束画面。与 first_frame 一起接 = 首尾帧过渡。"},
            ),
        }

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> list:
        content = [{"type": "text", "text": prompt}]
        for input_name, role in (("first_frame", "first_frame"), ("last_frame", "last_frame")):
            batch = kwargs.get(input_name)
            if batch is None:
                continue
            if not hasattr(batch, "ndim"):
                raise XHCYError(f"{input_name} 必须是 ComfyUI 的 IMAGE 输入")
            frame = batch[0] if batch.ndim == 4 else batch
            content.append(
                {
                    "type": "image_url",
                    "role": role,
                    "image_url": {"url": image_tensor_to_uri(frame)},
                }
            )
        if len(content) == 1:
            raise XHCYError("请至少连接 first_frame 或 last_frame 中的一张图")
        return content


NODE_CLASS_MAPPINGS = {
    "xhcy_minimax_h3_frames": XHCYMiniMaxH3Frames,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_minimax_h3_frames": "XHCY MiniMax H3（首尾帧 / 图生视频）",
}
