"""XHCY AI image node — Nano Banana family.

Same shape as the GPT Image 2.5 node: text-to-image when nothing is connected
to image1..image16, multi-reference generation when something is.

Compared with GPT Image 2.5 this family is more restricted, so the node hides
the controls that do not apply:
    * only 1024x1024 is accepted (2048x2048 answers `size_not_supported`),
      hence FIXED_SIZE instead of a ratio/resolution picker
    * there is no quality tier, hence an empty QUALITIES list

Everything else (reference handling, submission, polling, saving, errors)
comes from XHCYImageBase untouched.
"""

from __future__ import annotations

try:
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_image_base import XHCYImageBase  # type: ignore


class XHCYNanoBanana(XHCYImageBase):
    """Nano Banana family — text-to-image and multi-reference in one node."""

    VARIANT_MODELS = [
        "nano-banana-2",
        "gemini-nano-banana-2.1",
        "nano-banana-pro",
        "nano-banana-fast",
    ]

    MODEL_TOOLTIP = (
        "同一家族的变体。"
        "实测 gemini-nano-banana-2.1 带参考图约 106 秒，比同族慢不少、容易贴近网关超时上限，"
        "参考图多时优先用 nano-banana-2。"
    )

    # 实测：本家族只接受 1024x1024，传 2048x2048 会返回 size_not_supported，
    # 因此不显示画幅 / 分辨率下拉，固定用这个尺寸。
    # gemini-nano-banana-2.1 同样是只吃 1024x1024。
    FIXED_SIZE = "1024x1024"

    # 本家族没有画质档，空列表 = 节点上不显示 quality
    QUALITIES = []

    DEFAULT_MODEL = "nano-banana-2"
    NODE_ID = "xhcy_nano_banana"
    OUTPUT_PREFIX = "xhcy_nano_banana"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · Nano Banana 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考（固定 1024x1024）"
    )


NODE_CLASS_MAPPINGS = {
    "xhcy_nano_banana": XHCYNanoBanana,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_nano_banana": "XHCY Nano Banana（文生图 / 多图参考）",
}
