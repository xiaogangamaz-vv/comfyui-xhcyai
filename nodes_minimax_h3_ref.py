"""XHCY AI video node — MiniMax H3 family, multimodal reference.

素材都可选，接哪个用哪个：
    image1..image9  -> role "reference_image"
    video1..video3  -> role "reference_video"
    audio1..audio3  -> role "reference_audio"
什么都不接就退化为纯文生视频。

规格（分辨率 / 时长 / 比例）统一取自 xhcy_h3_specs.py。
"""

from __future__ import annotations

try:
    from .xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION
    from .xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL
    from .xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO
    from .xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION
    from .xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS
    from .xhcy_h3_specs import MODELS as _MODELS
    from .xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS
    from .xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS
    from .xhcy_video_base import (
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )
except ImportError:  # 允许单文件直接运行调试
    from xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION  # type: ignore
    from xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL  # type: ignore
    from xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO  # type: ignore
    from xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION  # type: ignore
    from xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS  # type: ignore
    from xhcy_h3_specs import MODELS as _MODELS  # type: ignore
    from xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS  # type: ignore
    from xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS  # type: ignore
    from xhcy_video_base import (  # type: ignore
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3


class XHCYMiniMaxH3Reference(XHCYVideoBase):
    """MiniMax H3 family — image / video / audio reference to video."""

    VARIANT_MODELS = list(_MODELS)
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    RATIO_LIMITS = _RATIO_LIMITS
    DURATION_LIMITS = _DURATION_LIMITS

    DEFAULT_MODEL = _DEFAULT_MODEL
    DEFAULT_RESOLUTION = _DEFAULT_RESOLUTION
    DEFAULT_DURATION = _DEFAULT_DURATION
    DEFAULT_RATIO = _DEFAULT_RATIO
    PROMPT_TOOLTIP = (
        "描述你要生成的视频。多张参考图时，在提示词里按顺序用「Image 1」「Image 2」引用它们，"
        "例如：让 Image 1 里的女孩穿上 Image 2 的裙子。留空会直接报错，不会白白扣费。"
    )
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
                {"tooltip": f"参考图 #{i}。提示词里用「Image {i}」引用它。不接任何素材就是纯文生视频。"},
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
