"""XHCY AI image node — Nano Banana family.

参数布局与参考节点保持一致：
    image1~image16 / prompt / model / api_key /
    aspect_ratio / image_size / reply_type / max_poll_attempts / poll_interval

但本站（ai.xhcyai.org）对尺寸有硬限制，实测确认：
    * nano-banana 系列只接受 1024x1024，其它尺寸返回 size_not_supported
    * 站点禁用了异步图像生成（async:true 会 400），所以 reply_type 选什么都不影响
因此下拉按参考节点给全量选项，但真正可用的只有 1:1 + 1K；选到别的会给出明确提示，
而不是让用户对着 size_not_supported 猜。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_image_base import XHCYImageBase  # type: ignore


# 与参考节点一致的画幅选项
_ASPECT_RATIOS = [
    "auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "5:4", "4:5", "21:9", "1:4", "4:1", "1:8", "8:1",
]

_IMAGE_SIZES = ["1K", "2K", "4K"]

# 本站唯一在用的组合
_SIZE_MAP = {("1:1", "1K"): "1024x1024"}


class XHCYNanoBanana(XHCYImageBase):
    """Nano Banana family — text-to-image and multi-reference in one node."""

    VARIANT_MODELS = [
        "nano-banana-2",
        "gemini-nano-banana-2.1",
        "nano-banana-pro",
        "nano-banana-fast",
    ]

    MODEL_TOOLTIP = (
        "同一家族的变体。实测 gemini-nano-banana-2.1 带参考图约 106 秒，"
        "比同族慢不少、容易贴近网关超时上限，参考图多时优先用 nano-banana-2。"
    )

    RATIOS = _ASPECT_RATIOS
    RESOLUTIONS = _IMAGE_SIZES
    SIZE_FIELD = "image_size"
    SIZE_MAP = _SIZE_MAP
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1K"
    RATIO_TOOLTIP = "画面比例。本站实测只支持 1:1，选其它比例会被站点拒绝。"
    RESOLUTION_TOOLTIP = "分辨率档位。本站实测只支持 1K（即 1024×1024）。"

    REPLY_TYPES = ["async", "sync"]
    DEFAULT_REPLY_TYPE = "async"

    QUALITIES = []          # 本家族没有画质档

    RETURN_NAMES = ("image", "response_text", "local_image_paths")

    DEFAULT_MODEL = "nano-banana-2"
    NODE_ID = "xhcy_nano_banana"
    OUTPUT_PREFIX = "xhcy_nano_banana"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · Nano Banana 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考（本站固定 1024x1024）"
    )

    @classmethod
    def resolve_size(cls, aspect_ratio: str, resolution: str) -> str:
        """本站的 nano-banana 只认 1024x1024，其余组合给出明确提示。"""
        if aspect_ratio == "auto":
            return "1024x1024"
        size = cls.SIZE_MAP.get((aspect_ratio, resolution))
        if size is None:
            raise XHCYError(
                "本站的 Nano Banana 系列只支持 1:1 + 1K（即 1024×1024）。"
                "实测其它尺寸会被站点拒绝（size_not_supported），"
                f"你选的是 {aspect_ratio} + {resolution}。"
            )
        return size


NODE_CLASS_MAPPINGS = {
    "xhcy_nano_banana": XHCYNanoBanana,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_nano_banana": "XHCY Nano Banana（文生图 / 多图参考）",
}
