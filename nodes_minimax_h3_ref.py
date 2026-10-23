"""XHCY AI video node — MiniMax H3 family, multimodal reference.

插槽是**动态**的：接一个就自动长出一个新插槽，最多长到上限。
不用再面对一堆固定空着的 image1~image9。

三组素材（都可以不接，不接就退化为纯文生视频）：

    ref_images.ref_image_0 / ref_image_1 …   最多 9 张    role "reference_image"
    ref_videos.ref_video_0 / ref_video_1 …   最多 3 段    role "reference_video"
    ref_audios.ref_audio_0 / ref_audio_1 …   最多 3 段    role "reference_audio"

规格（分辨率 / 时长 / 比例）统一取自 xhcy_h3_specs.py。

实现说明
--------
这是原生 v3 节点（``io.ComfyNode`` 在前、``XHCYVideoBase`` 在后），
靠 MRO 顺序让 ``INPUT_TYPES`` 用 v3 从 schema 生成，同时还能复用基类的
``generate()`` 逻辑。动态插槽靠 ``io.Autogrow.TemplatePrefix``。
"""

from __future__ import annotations

try:
    from .xhcy_h3_specs import DEFAULT_DURATION as _DEFAULT_DURATION
    from .xhcy_h3_specs import DEFAULT_MODEL as _DEFAULT_MODEL
    from .xhcy_h3_specs import DEFAULT_RATIO as _DEFAULT_RATIO
    from .xhcy_h3_specs import DEFAULT_RESOLUTION as _DEFAULT_RESOLUTION
    from .xhcy_h3_specs import DURATION_LIMITS as _DURATION_LIMITS
    from .xhcy_h3_specs import MODELS as _MODELS
    from .xhcy_h3_specs import PROMPT_MAX_CHARS as _PROMPT_MAX_CHARS
    from .xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS
    from .xhcy_h3_specs import REFERENCE_LIMITS as _REFERENCE_LIMITS
    from .xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS
    from .xhcy_video_base import DEFAULT_BASE_URL
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
    from xhcy_h3_specs import PROMPT_MAX_CHARS as _PROMPT_MAX_CHARS  # type: ignore
    from xhcy_h3_specs import RATIO_LIMITS as _RATIO_LIMITS  # type: ignore
    from xhcy_h3_specs import REFERENCE_LIMITS as _REFERENCE_LIMITS  # type: ignore
    from xhcy_h3_specs import RESOLUTION_LIMITS as _RESOLUTION_LIMITS  # type: ignore
    from xhcy_video_base import DEFAULT_BASE_URL  # type: ignore
    from xhcy_video_base import (  # type: ignore
        XHCYVideoBase,
        audio_input_to_uri,
        image_tensor_to_uri,
        video_input_to_uri,
    )

try:
    from comfy_api.latest import io
except Exception:  # pragma: no cover
    io = None

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3

NODE_ID = "xhcy_minimax_h3_ref"
DISPLAY_NAME = "XHCY MiniMax H3（多模态参考）"

# 动态插槽组 → 基类认识的命名前缀
# Autogrow 传进来的是 {"ref_image_0": 张量, "ref_image_1": 张量}，
# 基类 build_content 读的是 kwargs["image1"]。这里做一次映射，
# 基类逻辑就完全不用改。
_AUTOGROW_GROUPS = (
    ("ref_images", "image"),
    ("ref_videos", "video"),
    ("ref_audios", "audio"),
)


def expand_autogrow(groups: dict) -> dict:
    """把 Autogrow 的三组字典展开成 image1 / video1 / audio1 形式。

    ``{"ref_images": {"ref_image_0": a, "ref_image_2": b}}``
        → ``{"image1": a, "image3": b}``

    序号从 0 开始（前端就这么排），这里 +1 对齐「Image 1」「Image 2」的
    提示词说法。
    """
    out: dict = {}
    for group_key, target_prefix in _AUTOGROW_GROUPS:
        group = groups.get(group_key)
        if not group:
            continue
        if isinstance(group, dict):
            items = group.items()
        else:  # 兜底：万一拿到的是 list
            items = (("", v) for v in group)
        for name, value in items:
            if value is None:
                continue
            try:
                slot = int(str(name).rsplit("_", 1)[-1]) + 1
            except (ValueError, IndexError):
                continue
            out[f"{target_prefix}{slot}"] = value
    return out


class XHCYMiniMaxH3Reference(io.ComfyNode, XHCYVideoBase):
    """MiniMax H3 family — image / video / audio reference to video."""

    VARIANT_MODELS = list(_MODELS)
    # 这三张表基类 generate() 要用：校验分辨率 / 时长 / 比例，缺了会退化成
    # 基类默认值（H3 的 4~30 秒会变成 1~15），所以必须保留。
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    RATIO_LIMITS = _RATIO_LIMITS
    DURATION_LIMITS = _DURATION_LIMITS
    # 素材数量上限按站点 limits 逐模型校验（Lite 没有参考视频）
    MEDIA_LIMITS = _REFERENCE_LIMITS
    PROMPT_MAX_CHARS = _PROMPT_MAX_CHARS
    DEFAULT_MODEL = _DEFAULT_MODEL
    DEFAULT_RESOLUTION = _DEFAULT_RESOLUTION
    DEFAULT_DURATION = _DEFAULT_DURATION
    DEFAULT_RATIO = _DEFAULT_RATIO

    NODE_ID = NODE_ID
    OUTPUT_PREFIX = "xhcy_h3_ref"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = "XHCY AI · MiniMax H3 多模态参考生视频（参考图 / 参考视频 / 参考音频）"

    # ⚠️ 不要在这里声明 FUNCTION = "generate"。
    #
    # io.ComfyNode 用 classproperty 把 FUNCTION 算成 "EXECUTE_NORMALIZED"，
    # 而 ComfyUI 的 execution.py 会执行：
    #     getattr(type_obj, obj.FUNCTION).__func__
    # 只有 classmethod 才有 __func__。如果本类把 FUNCTION 写死成 "generate"，
    # 上面那行拿到的是普通函数，直接抛
    #     AttributeError: 'function' object has no attribute '__func__'
    # 2026-10-23 就是这么炸的。执行逻辑由 execute() 里显式调 generate 完成，
    # 不需要靠 FUNCTION 传方法名。
    # ------------------------------------------------------------------ #

    @classmethod
    def define_schema(cls):
        # 分辨率 / 比例的下拉候选来自基类方法（读的是 xhcy_h3_specs 的表）
        resolutions = cls.all_resolutions()
        ratios = cls.all_ratios()

        return io.Schema(
            node_id=NODE_ID,
            display_name=DISPLAY_NAME,
            category="XHCY/Video",
            description=cls.DESCRIPTION,
            inputs=[
                io.String.Input(
                    "prompt",
                    multiline=True,
                    default="",
                    tooltip=(
                        "描述你要生成的视频。多张参考图时，在提示词里按顺序用"
                        "「Image 1」「Image 2」引用它们，例如：让 Image 1 里的女孩穿上 Image 2 的裙子。"
                        "留空会直接报错，不会白白扣费。"
                    ),
                ),
                io.Combo.Input(
                    "model",
                    options=list(_MODELS),
                    default=_DEFAULT_MODEL,
                    tooltip="同一家族的变体，切换即可换模型。",
                ),
                io.String.Input(
                    "api_key",
                    default="",
                    tooltip="XHCY AI 访问密钥。每个节点单独填。",
                ),
                io.Combo.Input(
                    "resolution",
                    options=resolutions,
                    default=_DEFAULT_RESOLUTION,
                    tooltip="输出分辨率，按所选模型自动校验。",
                ),
                io.Int.Input(
                    "duration",
                    default=_DEFAULT_DURATION,
                    min=1,
                    max=60,
                    tooltip="时长（秒），按秒计费。超出所选模型范围时会自动收进合法区间并提示。",
                ),
                io.Combo.Input(
                    "ratio",
                    options=ratios,
                    default=_DEFAULT_RATIO,
                    tooltip="画面比例，adaptive 由服务端决定。",
                ),
                io.Int.Input(
                    "max_poll_attempts",
                    default=120,
                    min=1,
                    max=600,
                    tooltip="最多查询多少次结果。",
                ),
                io.Int.Input(
                    "poll_interval",
                    default=5,
                    min=1,
                    max=60,
                    tooltip="每次查询之间等几秒。",
                ),
                io.String.Input(
                    "base_url",
                    default=DEFAULT_BASE_URL,
                    tooltip="站点地址，一般不用改。",
                ),
                # ---- 动态插槽：接一个长一个 ---------------------------- #
                io.Autogrow.Input(
                    "ref_images",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input(
                            "ref_image",
                            tooltip=(
                                "参考图。提示词里按顺序用「Image 1」「Image 2」引用它。"
                                "接一张就自动多出一个插槽，最多 9 张。"
                            ),
                        ),
                        prefix="ref_image_",
                        min=0,
                        max=MAX_REF_IMAGES,
                    ),
                ),
                io.Autogrow.Input(
                    "ref_videos",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Video.Input(
                            "ref_video",
                            tooltip=(
                                "参考视频。素材以数据流内嵌上传，体积越大越慢。最多 3 段。"
                            ),
                        ),
                        prefix="ref_video_",
                        min=0,
                        max=MAX_REF_VIDEOS,
                    ),
                ),
                io.Autogrow.Input(
                    "ref_audios",
                    optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input(
                            "ref_audio",
                            tooltip="参考音频（用于声音 / 口型参考）。最多 3 段。",
                        ),
                        prefix="ref_audio_",
                        min=0,
                        max=MAX_REF_AUDIOS,
                    ),
                ),
            ],
            outputs=[
                io.Video.Output(display_name="video"),
                io.String.Output(display_name="status"),
                io.String.Output(display_name="video_path"),
            ],
        )

    # ------------------------------------------------------------------ #

    @classmethod
    def execute(cls, **kwargs):
        """把动态插槽收到的字典，展开成基类认识的 image1/2/3 形式。"""
        merged = dict(kwargs)
        for group_key, _ in _AUTOGROW_GROUPS:
            merged.pop(group_key, None)
        merged.update(expand_autogrow(kwargs))

        instance = cls.__new__(cls)
        # 这里必须写死 "generate"，不能读 cls.FUNCTION。
        #
        # 原因：io.ComfyNode 用 classproperty 把 FUNCTION 算成
        # "EXECUTE_NORMALIZED"，ComfyUI 的 execution.py 会拿它去做
        #   getattr(type_obj, obj.FUNCTION).__func__
        # 只有 classmethod 才有 __func__。一旦在本类里把 FUNCTION 写死成
        # "generate"（普通方法），上面那行就会抛
        #   AttributeError: 'function' object has no attribute '__func__'
        # —— 2026-10-23 线上报的就是这个。
        return getattr(instance, "generate")(**merged)

    # ------------------------------------------------------------------ #

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> list:
        """组装 content 数组：文字 + 参考图 / 参考视频 / 参考音频。

        ``kwargs`` 里的键是展开后的 image1..image9 / video1..video3 /
        audio1..audio3（由 execute 的 expand_autogrow 生成）。
        """
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
    NODE_ID: XHCYMiniMaxH3Reference,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    NODE_ID: DISPLAY_NAME,
}
