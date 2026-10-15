"""XHCY AI image node — GPT Image 2 family.

一个节点覆盖整个家族，同时支持两种模式：

    * 不接参考图          -> 文生图
    * 接 image1..image16  -> 多图参考生成

公共逻辑（参考图压缩、提交、轮询、落盘、报错）都在
xhcy_image_base.XHCYImageBase；这里只声明本家族特有的参数。

变体差异（来源：站点 ``/api/model_provider_meta`` 的 usage 字段）：

    ==================  ==================  ==================================
    变体                分辨率              说明
    ==================  ==================  ==================================
    gpt-image-2         1K                  站点定价模型，尺寸白名单只有
                                            1024x1024
    gpt-image-2-all     1K / 2K / 4K        能力对标 nano banana 2，任意比例
    gpt-image-2-vip     1K / 2K / 4K        任意比例
    ==================  ==================  ==================================

关于尺寸：站点只对**定价模型**（nano-banana-2 / nano-banana-pro /
gpt-image-2）做尺寸预校验，``-all`` / ``-vip`` 是直接转发上游、不校验。
所以后两者的像素表沿用 GPT Image 2.5 那一套已验证的约束（长边 ≤ 3840、
边长为 16 的倍数、比例不超过 3:1），但**尚未逐个实测**。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_image_base import XHCYImageBase  # type: ignore


_RATIOS = [
    "auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
    "16:9", "9:16", "2:1", "1:2", "21:9", "9:21",
]

_RESOLUTIONS = ["1k", "2k", "4k"]

# 无后缀的 gpt-image-2 是站点定价模型，只开放 1K
_RESOLUTION_LIMITS = {
    "gpt-image-2": ["1k"],
    "gpt-image-2-all": ["1k", "2k", "4k"],
    "gpt-image-2-vip": ["1k", "2k", "4k"],
}

# 与 GPT Image 2.5 家族共用同一套像素表。
# 约束：长边 ≤ 3840、边长 16 的倍数、单边比例 ≤ 3:1。
_SIZE_MAP: dict[tuple[str, str], str] = {
    ("1:1", "1k"): "1024x1024",
    ("1:1", "2k"): "2048x2048",
    ("1:1", "4k"): "2880x2880",
    ("16:9", "1k"): "1280x720",
    ("16:9", "2k"): "2560x1440",
    ("16:9", "4k"): "3840x2160",
    ("9:16", "1k"): "720x1280",
    ("9:16", "2k"): "1440x2560",
    ("9:16", "4k"): "2160x3840",
    ("4:3", "1k"): "1152x864",
    ("4:3", "2k"): "2304x1728",
    ("4:3", "4k"): "3264x2448",
    ("3:4", "1k"): "864x1152",
    ("3:4", "2k"): "1728x2304",
    ("3:4", "4k"): "2448x3264",
    ("3:2", "1k"): "1248x832",
    ("3:2", "2k"): "2496x1664",
    ("3:2", "4k"): "3504x2336",
    ("2:3", "1k"): "832x1248",
    ("2:3", "2k"): "1664x2496",
    ("2:3", "4k"): "2336x3504",
    ("5:4", "1k"): "1120x896",
    ("5:4", "2k"): "2240x1792",
    ("5:4", "4k"): "3200x2560",
    ("4:5", "1k"): "896x1120",
    ("4:5", "2k"): "1792x2240",
    ("4:5", "4k"): "2560x3200",
    ("21:9", "1k"): "1456x624",
    ("21:9", "2k"): "3024x1296",
    ("21:9", "4k"): "3696x1584",
    ("9:21", "1k"): "624x1456",
    ("9:21", "2k"): "1296x3024",
    ("9:21", "4k"): "1584x3696",
    ("2:1", "1k"): "2048x1024",
    ("2:1", "2k"): "2688x1344",
    ("2:1", "4k"): "3840x1920",
    ("1:2", "1k"): "1024x2048",
    ("1:2", "2k"): "1344x2688",
    ("1:2", "4k"): "1920x3840",
}


class XHCYGPTImage2(XHCYImageBase):
    """GPT Image 2 family — text-to-image and multi-reference in one node."""

    VARIANT_MODELS = ["gpt-image-2", "gpt-image-2-all", "gpt-image-2-vip"]

    MODEL_TOOLTIP = (
        "同一家族的变体。gpt-image-2 只支持 1:1 + 1K（本站尺寸白名单）；"
        "gpt-image-2-all / gpt-image-2-vip 支持 1K / 2K / 4K 与任意画幅。"
    )

    RATIOS = _RATIOS
    RESOLUTIONS = _RESOLUTIONS
    SIZE_MAP = _SIZE_MAP
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS

    QUALITIES = []          # 本站未给出该家族的画质档，不显示

    DEFAULT_MODEL = "gpt-image-2-all"
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1k"
    NODE_ID = "xhcy_gpt_image_2"
    OUTPUT_PREFIX = "xhcy_gpt_image_2"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · GPT Image 2 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考生成"
    )

    @classmethod
    def resolve_size(cls, aspect_ratio: str, resolution: str, model: str | None = None) -> str:
        # 无后缀的 gpt-image-2 是站点定价模型，站点对它做了尺寸白名单：
        # 只接受 1024x1024。选到别的比例时直接讲清楚，别让它去撞
        # size_not_supported。
        if model == "gpt-image-2" and aspect_ratio not in ("auto", "1:1"):
            raise XHCYError(
                "gpt-image-2 在本站只接受 1024×1024（即 1:1 + 1K），"
                f"你选的是 {aspect_ratio}。"
                "需要其它画幅或更高分辨率，请把 model 换成 gpt-image-2-all "
                "或 gpt-image-2-vip。"
            )
        return super().resolve_size(aspect_ratio, resolution, model)


NODE_CLASS_MAPPINGS = {
    "xhcy_gpt_image_2": XHCYGPTImage2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_gpt_image_2": "XHCY GPT Image 2（文生图 / 多图参考）",
}
