"""XHCY AI video node — MiniMax H3 family, first/last frame driven.

接 first_frame、last_frame 或两张都接：视频从该画面开始、到该画面结束。
规格（分辨率 / 时长 / 比例）统一取自 xhcy_h3_specs.py。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION
    from .xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL
    from .xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO
    from .xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION
    from .xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS
    from .xhcy_h3_specs import MODELS as _MODELS
    from .xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS
    from .xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS
    from .xhcy_video_base import XHCYVideoBase, image_tensor_to_uri
except ImportError:  # 允许单文件直接运行调试
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION  # type: ignore
    from xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL  # type: ignore
    from xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO  # type: ignore
    from xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION  # type: ignore
    from xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS  # type: ignore
    from xhcy_h3_specs import MODELS as _MODELS  # type: ignore
    from xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS  # type: ignore
    from xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS  # type: ignore
    from xhcy_video_base import XHCYVideoBase, image_tensor_to_uri  # type: ignore


class XHCYMiniMaxH3Frames(XHCYVideoBase):
    """MiniMax H3 family — first/last frame to video."""

    VARIANT_MODELS = list(_MODELS)
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    RATIO_LIMITS = _RATIO_LIMITS
    DURATION_LIMITS = _DURATION_LIMITS

    DEFAULT_MODEL = _DEFAULT_MODEL
    DEFAULT_RESOLUTION = _DEFAULT_RESOLUTION
    DEFAULT_DURATION = _DEFAULT_DURATION
    DEFAULT_RATIO = _DEFAULT_RATIO
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
