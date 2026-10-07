"""XHCY AI video node — MiniMax H3 family, multimodal reference.

Reference material is optional; connect whichever is available:
    image1..image9  -> role "reference_image"
    video1..video3  -> role "reference_video"
    audio1..audio3  -> role "reference_audio"
With nothing connected it degrades to plain text-to-video.

Verified against the live service for images (data URI + role), matching the
documented content.role values.
"""

from __future__ import annotations

try:
    from .xhcy_video_base import (
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_video_base import (  # type: ignore
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )


_H3_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
_LITE_RATIOS = ["adaptive", "16:9", "9:16", "1:1"]

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3


class XHCYMiniMaxH3Reference(XHCYVideoBase):
    """MiniMax H3 family — image / video / audio reference to video."""

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
    PROMPT_TOOLTIP = "描述你要生成的视频。留空会直接报错，不会白白扣费。"
    NODE_ID = "xhcy_minimax_h3_ref"
    OUTPUT_PREFIX = "xhcy_h3_ref"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = "XHCY AI · MiniMax H3 多模态参考生视频（参考图 / 参考视频 / 参考音频）"

    @classmethod
    def material_inputs(cls):
        inputs: dict = {}
        for i in range(1, MAX_REF_IMAGES + 1):
            inputs[f"image{i}"] = (
                "IMAGE",
                {"tooltip": f"参考图 #{i}。不接任何素材就是纯文生视频。"},
            )
        for i in range(1, MAX_REF_VIDEOS + 1):
            inputs[f"video{i}"] = (
                "VIDEO",
                {"tooltip": f"参考视频 #{i}。素材以数据流内嵌上传，体积越大越慢。"},
            )
        for i in range(1, MAX_REF_AUDIOS + 1):
            inputs[f"audio{i}"] = (
                "AUDIO",
                {"tooltip": f"参考音频 #{i}（用于声音/口型参考）。"},
            )
        return inputs

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> list:
        content: list = [{"type": "text", "text": prompt}]

        for i in range(1, MAX_REF_IMAGES + 1):
            batch = kwargs.get(f"image{i}")
            if batch is None:
                continue
            if not hasattr(batch, "ndim"):
                raise ValueError(f"image{i} 必须是 ComfyUI 的 IMAGE 输入")
            items = batch if batch.ndim == 4 else batch.unsqueeze(0)
            for item in items:
                content.append(
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": image_tensor_to_uri(item)},
                    }
                )

        for i in range(1, MAX_REF_VIDEOS + 1):
            video = kwargs.get(f"video{i}")
            if video is None:
                continue
            content.append(
                {
                    "type": "video_url",
                    "role": "reference_video",
                    "video_url": {"url": video_input_to_uri(video)},
                }
            )

        for i in range(1, MAX_REF_AUDIOS + 1):
            audio = kwargs.get(f"audio{i}")
            if audio is None:
                continue
            content.append(
                {
                    "type": "audio_url",
                    "role": "reference_audio",
                    "audio_url": {"url": audio_input_to_uri(audio)},
                }
            )

        return content


NODE_CLASS_MAPPINGS = {
    "xhcy_minimax_h3_ref": XHCYMiniMaxH3Reference,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_minimax_h3_ref": "XHCY MiniMax H3（多模态参考）",
}
