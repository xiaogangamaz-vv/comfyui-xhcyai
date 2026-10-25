"""XHCY AI image node — Nano Banana family.

一个节点覆盖文生图与多图参考：不接参考图就是文生图，接 image1~image16 就是多图参考。

尺寸能力
--------
站点的尺寸白名单是**逐模型**的（源码 relay/billing/ratio/image.go 的
ImageSizeRatios，以及 image_nano_banana_params.go 的 NanoBananaSizeParams）：

    nano-banana-2            只认 1024x1024
    nano-banana-pro          只认 1024x1024
    gemini-nano-banana-2.1   认八种像素框（见下）
    nano-banana-fast         不校验，原样转发上游
    nano-banana               不校验，原样转发上游

gemini-nano-banana-2.1 的八种（上游不接受 size 字段，站点会把它换算成
「比例 + 档位」再发出去；非正方框统一走 4K 档）:

    1:1  @ 1K  -> 1024x1024   （走旧的 size 形式，一直是生产在用的）
    1:1  @ 4K  -> 4096x4096
    2:3  @ 1K  -> 1024x1536
    3:2  @ 1K  -> 1536x1024
    16:9 @ 1K  -> 1280x720
    9:16 @ 1K  -> 720x1280
    16:9 @ 4K  -> 2752x1536
    9:16 @ 4K  -> 1536x2752

数字来自后端对上游的实测：4K 档八种比例全部一次通过；1K 档八种里只有五种
能过、且要重试，16:9 在 1K 档始终失败——所以非正方框都放在 4K 档。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_image_base import XHCYImageBase  # type: ignore


# 画幅候选（取各模型声明过的并集；auto 交给服务端）
_ASPECT_RATIOS = [
    "auto", "1:1", "2:3", "3:2", "3:4", "4:3",
    "4:5", "5:4", "9:16", "16:9", "21:9",
]

_IMAGE_SIZES = ["1K", "2K", "4K"]

# ---------------------------------------------------------------- #
# 各模型真正能用的 (画幅, 档位) -> 像素
# ---------------------------------------------------------------- #

# 严格白名单：站点只接受 1024x1024
_ONLY_SQUARE = {
    ("1:1", "1K"): "1024x1024",
}

# gemini-2.5-flash-image：站点白名单里最全的一个，按 Gemini 官方尺寸表
# 逐档给出。以下组合均于 2026-10-25 实测出图：
#   1K  1:1 / 16:9 / 2:3 / 3:2
#   2K  1:1 / 16:9 / 21:9 / 2:3
#   4K  1:1 / 16:9 / 21:9 / 2:3
# 其余条目来自同一份官方尺寸表（同模型同档位，未被站点限制）。
_FLASH_IMAGE_SIZES = {
    # ---- 1K ----
    ("1:1", "1K"): "1024x1024",
    ("2:3", "1K"): "848x1264",
    ("3:2", "1K"): "1264x848",
    ("3:4", "1K"): "896x1200",
    ("4:3", "1K"): "1200x896",
    ("4:5", "1K"): "928x1152",
    ("5:4", "1K"): "1152x928",
    ("9:16", "1K"): "768x1344",
    ("16:9", "1K"): "1344x768",
    ("21:9", "1K"): "1536x672",
    # ---- 2K ----
    ("1:1", "2K"): "2048x2048",
    ("2:3", "2K"): "1696x2528",
    ("3:2", "2K"): "2528x1696",
    ("3:4", "2K"): "1792x2400",
    ("4:3", "2K"): "2400x1792",
    ("4:5", "2K"): "1856x2304",
    ("5:4", "2K"): "2304x1856",
    ("9:16", "2K"): "1536x2688",
    ("16:9", "2K"): "2688x1536",
    ("21:9", "2K"): "3072x1344",
    # ---- 4K ----
    ("1:1", "4K"): "4096x4096",
    ("2:3", "4K"): "3392x5056",
    ("3:2", "4K"): "5056x3392",
    ("3:4", "4K"): "3584x4800",
    ("4:3", "4K"): "4800x3584",
    ("4:5", "4K"): "3712x4608",
    ("5:4", "4K"): "4608x3712",
    ("9:16", "4K"): "3072x5376",
    ("16:9", "4K"): "5376x3072",
    ("21:9", "4K"): "6144x2688",
}

# gemini-nano-banana-2.1：站点只开了八种像素框（同上游的另一个名）
_GEMINI_SIZES = {
    ("1:1", "1K"): "1024x1024",
    ("1:1", "4K"): "4096x4096",
    ("2:3", "1K"): "1024x1536",
    ("3:2", "1K"): "1536x1024",
    ("16:9", "1K"): "1280x720",
    ("9:16", "1K"): "720x1280",
    ("16:9", "4K"): "2752x1536",
    ("9:16", "4K"): "1536x2752",
}

_MODEL_SIZES = {
    "gemini-2.5-flash-image": _FLASH_IMAGE_SIZES,
    "nano-banana-2": _ONLY_SQUARE,
    "nano-banana-pro": _ONLY_SQUARE,
    "gemini-nano-banana-2.1": _GEMINI_SIZES,
}

# 兼容基类的老字段：任一变体支持的最大像素集合
_SIZE_MAP = dict(_FLASH_IMAGE_SIZES)


class XHCYNanoBanana(XHCYImageBase):
    """Nano Banana family — text-to-image and multi-reference in one node."""

    # 只保留 2026-10-25 实测真的能出图的三个变体。
    # 已移除：
    #   nano-banana-fast —— HTTP 503「no available channel」，站点没有可用渠道
    #   nano-banana      —— HTTP 400「upstream provider rejected the request」
    VARIANT_MODELS = [
        "gemini-2.5-flash-image",
        "nano-banana-2",
        "nano-banana-pro",
        "gemini-nano-banana-2.1",
    ]

    MODEL_TOOLTIP = (
        "尺寸能力差别很大（2026-10-25 逐个打真接口实测）：\n"
        "· gemini-2.5-flash-image —— 最全：10 种画幅 × 1K / 2K / 4K 三档，"
        "按 Gemini 官方尺寸表。要什么比例都选它\n"
        "· nano-banana-2 —— 站点白名单只放 1:1 @ 1K（1024×1024）\n"
        "· nano-banana-pro —— 同上，只有方图\n"
        "· gemini-nano-banana-2.1 —— 8 种固定像素框（1:1 / 2:3 / 3:2 / 16:9 / 9:16）\n"
        "选到当前变体做不到的组合时，节点会自动换成本家族里能做到的那个变体，"
        "不会卡在报错上。"
    )

    RATIOS = _ASPECT_RATIOS
    RESOLUTIONS = _IMAGE_SIZES
    SIZE_FIELD = "image_size"
    SIZE_MAP = _SIZE_MAP
    MODEL_SIZES = _MODEL_SIZES

    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1K"

    RATIO_TOOLTIP = (
        "画面比例。不同变体支持的比例不同：\n"
        "· 1:1 —— 所有变体都支持\n"
        "· 2:3 / 3:2 / 16:9 / 9:16 —— 只有 gemini-nano-banana-2.1、"
        "nano-banana-fast、nano-banana 支持\n"
        "选到当前模型不支持的比例时，会直接告诉你它能用什么。"
    )
    RESOLUTION_TOOLTIP = (
        "分辨率档位。\n"
        "· 1K —— 所有变体都支持\n"
        "· 4K —— 只有 gemini-nano-banana-2.1 / nano-banana-fast / nano-banana 支持\n"
        "注意：非正方形框在站点内部统一按 4K 档出图（这是上游实测最稳的一档）。"
    )

    REPLY_TYPES = ["async", "sync"]
    DEFAULT_REPLY_TYPE = "async"

    QUALITIES = []          # 本家族没有画质档

    RETURN_NAMES = ("image", "response_text", "local_image_paths")

    # 默认用能力最全的：10 种画幅 × 1K / 2K / 4K，全部实测出图
    DEFAULT_MODEL = "gemini-2.5-flash-image"
    NODE_ID = "xhcy_nano_banana"
    OUTPUT_PREFIX = "xhcy_nano_banana"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · Nano Banana 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考。不同变体的尺寸能力不同，见 model 提示"
    )

    @classmethod
    def resolve_size(cls, aspect_ratio: str, resolution: str, model: str | None = None) -> str:
        """auto 统一落到 1024x1024 —— 站点的 size 字段必填，不能真的不传。"""
        if aspect_ratio == "auto":
            return "1024x1024"
        return super().resolve_size(aspect_ratio, resolution, model)


NODE_CLASS_MAPPINGS = {
    "xhcy_nano_banana": XHCYNanoBanana,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_nano_banana": "XHCY Nano Banana（文生图 / 多图参考）",
}
