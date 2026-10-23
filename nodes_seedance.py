"""XHCY AI video node — Seedance 2.0（火山引擎方舟）。

一个节点覆盖四种用法，靠「接了什么素材」自动判断：

    什么都不接                     → 纯文生视频
    只接 first_frame               → 以这张图开头的图生视频
    接 first_frame + last_frame    → 首尾帧过渡
    接 image1~9 / video1~3 / audio1~3 → 多模态参考

首尾帧与参考素材**互斥**（Ark 的硬约束），同时接会直接报中文错误。

规格（分辨率 / 时长 / 比例）取自 xhcy_seedance_specs.py，
数据源是站点 /api/video/models 的实测返回。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_seedance_specs import DEFAULT_DURATION as _DEFAULT_DURATION
    from .xhcy_seedance_specs import DEFAULT_MODEL as _DEFAULT_MODEL
    from .xhcy_seedance_specs import DEFAULT_RATIO as _DEFAULT_RATIO
    from .xhcy_seedance_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION
    from .xhcy_seedance_specs import DURATION_LIMITS as _DURATION_LIMITS
    from .xhcy_seedance_specs import MAX_REF_AUDIOS
    from .xhcy_seedance_specs import MAX_REF_IMAGES
    from .xhcy_seedance_specs import MAX_REF_VIDEOS
    from .xhcy_seedance_specs import MEDIA_LIMITS as _MEDIA_LIMITS
    from .xhcy_seedance_specs import MODELS as _MODELS
    from .xhcy_seedance_specs import PROMPT_MAX_CHARS as _PROMPT_MAX_CHARS
    from .xhcy_seedance_specs import RATIO_LIMITS as _RATIO_LIMITS
    from .xhcy_seedance_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS
    from .xhcy_v3 import as_v3_node
    from .xhcy_video_base import (
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )
except ImportError:  # 允许单文件直接运行调试
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_seedance_specs import DEFAULT_DURATION as _DEFAULT_DURATION  # type: ignore
    from xhcy_seedance_specs import DEFAULT_MODEL as _DEFAULT_MODEL  # type: ignore
    from xhcy_seedance_specs import DEFAULT_RATIO as _DEFAULT_RATIO  # type: ignore
    from xhcy_seedance_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION  # type: ignore
    from xhcy_seedance_specs import DURATION_LIMITS as _DURATION_LIMITS  # type: ignore
    from xhcy_seedance_specs import MAX_REF_AUDIOS  # type: ignore
    from xhcy_seedance_specs import MAX_REF_IMAGES  # type: ignore
    from xhcy_seedance_specs import MAX_REF_VIDEOS  # type: ignore
    from xhcy_seedance_specs import MEDIA_LIMITS as _MEDIA_LIMITS  # type: ignore
    from xhcy_seedance_specs import MODELS as _MODELS  # type: ignore
    from xhcy_seedance_specs import PROMPT_MAX_CHARS as _PROMPT_MAX_CHARS  # type: ignore
    from xhcy_seedance_specs import RATIO_LIMITS as _RATIO_LIMITS  # type: ignore
    from xhcy_seedance_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS  # type: ignore
    from xhcy_v3 import as_v3_node  # type: ignore
    from xhcy_video_base import (  # type: ignore
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )


class XHCYSeedance2(XHCYVideoBase):
    """Seedance 2.0 —— 文生 / 首帧 / 首尾帧 / 多模态参考，一个节点搞定。"""

    VARIANT_MODELS = list(_MODELS)
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    RATIO_LIMITS = _RATIO_LIMITS
    DURATION_LIMITS = _DURATION_LIMITS
    # 素材数量按站点 limits 校验（9 图 + 3 视频 + 3 音频，合计 ≤ 15）
    MEDIA_LIMITS = _MEDIA_LIMITS
    PROMPT_MAX_CHARS = _PROMPT_MAX_CHARS

    DEFAULT_MODEL = _DEFAULT_MODEL
    DEFAULT_RESOLUTION = _DEFAULT_RESOLUTION
    DEFAULT_DURATION = _DEFAULT_DURATION
    DEFAULT_RATIO = _DEFAULT_RATIO

    # Seedance 用 720P / 4K，和 H3 的 768P / 2K 不是一套写法
    RESOLUTIONS = ["480P", "720P", "1080P", "4K"]

    PROMPT_TOOLTIP = (
        "描述你要生成的视频。接了多张参考图时，按顺序用「Image 1」「Image 2」引用它们。"
        "首尾帧模式请描述「从什么画面过渡到什么画面」。留空会直接报错，不会白白扣费。"
    )
    NODE_ID = "xhcy_seedance2"
    OUTPUT_PREFIX = "xhcy_seedance2"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = (
        "XHCY AI · Seedance 2.0（文生 / 首帧 / 首尾帧 / 多模态参考）"
        "｜480P~4K，4–15 秒，可生成同步音频"
    )

    # ------------------------------------------------------------------ #

    @classmethod
    def INPUT_TYPES(cls):
        # 必须走 super()：用基类名调用会把 cls 绑死成基类，
        # 子类的规格表（720P / 4K）就被绕过了。
        types = super().INPUT_TYPES()

        types["required"]["generate_audio"] = (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": "打开后视频会带原生同步音频（人声/环境音/音效）。不影响价格。",
            },
        )
        types["required"]["watermark"] = (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": "打开后视频右下角会有平台水印。一般保持关闭。",
            },
        )
        types["required"]["web_search"] = (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": "打开后允许模型联网检索现实资料再生成（适合真实地点/时事元素）。",
            },
        )
        return types

    @classmethod
    def material_inputs(cls):
        inputs: dict = {
            "first_frame": (
                "IMAGE",
                {"tooltip": "起始画面。只接这一张 = 以它为开头的图生视频。"},
            ),
            "last_frame": (
                "IMAGE",
                {
                    "tooltip": "结束画面。与 first_frame 一起接 = 首尾帧过渡。"
                    "⚠️ 它与参考素材（image*/video*/audio*）不能同时使用。"
                },
            ),
        }
        for i in range(1, MAX_REF_IMAGES + 1):
            inputs[f"image{i}"] = (
                "IMAGE",
                {
                    "tooltip": f"参考图 #{i}（最多 {MAX_REF_IMAGES} 张）。"
                    f"提示词里用「Image {i}」引用它。"
                    "⚠️ 参考素材与首尾帧不能同时使用。"
                },
            )
        for i in range(1, MAX_REF_VIDEOS + 1):
            inputs[f"video{i}"] = (
                "VIDEO",
                {
                    "tooltip": f"参考视频 #{i}（最多 {MAX_REF_VIDEOS} 段）。"
                    "素材以数据流内嵌上传，体积越大越慢；参考视频按输出分辨率同样计费。"
                },
            )
        for i in range(1, MAX_REF_AUDIOS + 1):
            inputs[f"audio{i}"] = (
                "AUDIO",
                {
                    "tooltip": f"参考音频 #{i}（最多 {MAX_REF_AUDIOS} 段，免费）。"
                    "⚠️ 音频不能是唯一素材，至少要配一张参考图或一段参考视频。"
                },
            )
        return inputs

    # ------------------------------------------------------------------ #

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> list:
        content: list = [{"type": "text", "text": prompt}]

        first = kwargs.get("first_frame")
        last = kwargs.get("last_frame")

        ref_images = [kwargs.get(f"image{i}") for i in range(1, MAX_REF_IMAGES + 1)]
        ref_videos = [kwargs.get(f"video{i}") for i in range(1, MAX_REF_VIDEOS + 1)]
        ref_audios = [kwargs.get(f"audio{i}") for i in range(1, MAX_REF_AUDIOS + 1)]

        has_frame = first is not None or last is not None
        has_ref = (
            any(x is not None for x in ref_images)
            or any(x is not None for x in ref_videos)
            or any(x is not None for x in ref_audios)
        )

        # --- 互斥与前置校验（都在提交前拦下，不花钱）------------------- #
        if has_frame and has_ref:
            raise XHCYError(
                "首尾帧（first_frame / last_frame）和参考素材（image* / video* / audio*）"
                "不能同时使用。\n请二选一："
                "① 想控制开头结尾 → 只接 first_frame（可加 last_frame）；"
                "② 想给参考图/视频/音频 → 断开 first_frame / last_frame。"
            )

        if last is not None and first is None:
            raise XHCYError(
                "只接 last_frame（尾帧）没有意义——首尾帧模式必须先给 first_frame。\n"
                "请补上 first_frame，或把 last_frame 断开。"
            )

        has_audio = any(x is not None for x in ref_audios)
        has_visual_ref = any(x is not None for x in ref_images) or any(
            x is not None for x in ref_videos
        )
        if has_audio and not has_visual_ref:
            raise XHCYError(
                "参考音频不能是唯一素材——至少还要接一张参考图或一段参考视频。\n"
                "请补一张 image，或把 audio 断开改走文生视频。"
            )

        # --- 首帧 / 尾帧 --------------------------------------------- #
        for value, role, label in (
            (first, "first_frame", "first_frame"),
            (last, "last_frame", "last_frame"),
        ):
            if value is None:
                continue
            if not hasattr(value, "ndim"):
                raise XHCYError(f"{label} 必须是 ComfyUI 的 IMAGE 输入")
            frame = value[0] if value.ndim == 4 else value
            content.append(
                {
                    "type": "image_url",
                    "role": role,
                    "image_url": {"url": image_tensor_to_uri(frame)},
                }
            )

        # --- 参考图 --------------------------------------------------- #
        for batch in ref_images:
            if batch is None:
                continue
            if not hasattr(batch, "ndim"):
                raise XHCYError("image* 必须是 ComfyUI 的 IMAGE 输入")
            items = batch if batch.ndim == 4 else batch.unsqueeze(0)
            for item in items:
                content.append(
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": image_tensor_to_uri(item)},
                    }
                )

        # --- 参考视频 ------------------------------------------------- #
        for video in ref_videos:
            if video is None:
                continue
            content.append(
                {
                    "type": "video_url",
                    "role": "reference_video",
                    "video_url": {"url": video_input_to_uri(video)},
                }
            )

        # --- 参考音频 ------------------------------------------------- #
        for audio in ref_audios:
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

    @classmethod
    def build_payload_extra(cls, kwargs: dict) -> dict:
        extra: dict = {}

        if kwargs.get("generate_audio"):
            extra["generate_audio"] = True
        if kwargs.get("watermark"):
            extra["watermark"] = True
        if kwargs.get("web_search"):
            # Ark 只支持 web_search 这一种工具，且是数组形式
            extra["tools"] = [{"type": "web_search"}]

        return extra


NODE_CLASS_MAPPINGS = {
    "xhcy_seedance2": as_v3_node(
        XHCYSeedance2, "xhcy_seedance2", "XHCY Seedance 2.0（文生 / 首尾帧 / 多模态参考）"
    ),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_seedance2": "XHCY Seedance 2.0（文生 / 首尾帧 / 多模态参考）",
}
