"""XHCY AI image node — GPT Image 2.5 family.

One node covers the whole family and both modes:

    * no reference image connected -> text-to-image
    * image1..image16 connected    -> multi-reference generation

The shared machinery (reference handling, submission, polling, saving) lives
in xhcy_image_base.XHCYImageBase; this file only declares what is specific to
the gpt-image-2.5 family. Building the next image model should mean copying
this file and editing the constants below.
"""

from __future__ import annotations

try:
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_image_base import XHCYImageBase  # type: ignore


_RATIOS = [
    "auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
    "16:9", "9:16", "2:1", "1:2", "21:9", "9:21",
]

_RESOLUTIONS = ["1k", "2k", "4k"]

# Base variant is documented as 1K-only; the two premium variants go to 4K.
_RESOLUTION_LIMITS = {
    "gpt-image-2.5": ["1k"],
    "gpt-image-2.5-flare": ["1k", "2k", "4k"],
    "gpt-image-2.5-sunburst": ["1k", "2k", "4k"],
}

# auto = 不指定；xhigh / max 仅 -sunburst 支持
_QUALITIES = ["auto", "low", "medium", "high", "xhigh", "max"]

# (aspect_ratio, resolution) -> pixel size.
# Constraints baked in: long edge <= 3840, both sides multiples of 16,
# side ratio <= 3:1, total pixels within 655,360 .. 8,294,400.
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


class XHCYGPTImage25(XHCYImageBase):
    """GPT Image 2.5 family — text-to-image and multi-reference in one node."""

    VARIANT_MODELS = ["gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]
    RATIOS = _RATIOS
    RESOLUTIONS = _RESOLUTIONS
    SIZE_MAP = _SIZE_MAP
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS
    QUALITIES = _QUALITIES
    DEFAULT_MODEL = "gpt-image-2.5"
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1k"
    NODE_ID = "xhcy_gpt_image_25"
    OUTPUT_PREFIX = "xhcy_gpt_image_25"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · GPT Image 2.5 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考生成"
    )


NODE_CLASS_MAPPINGS = {
    "xhcy_gpt_image_25": XHCYGPTImage25,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_gpt_image_25": "XHCY GPT Image 2.5（文生图 / 多图参考）",
}
