"""XHCY AI image node — Nano Banana family.

一个节点覆盖文生图与多图参考：不接参考图就是文生图，接 image1~image16 就是多图参考。
各变体支持的画幅和档位不同，选错时节点会在提交前说明。
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

# nano-banana-2、gemini-nano-banana-2.1、nano-banana-pro
# 都用 aspect_ratio + image_size 表达输出，1K / 2K / 4K 三档全部生效。
_IMAGE_SIZES = ["1K", "2K", "4K"]

# ---------------------------------------------------------------- #
# 各模型真正能用的 (画幅, 档位) -> 像素
# ---------------------------------------------------------------- #

# ── 比例 + 档位 ──
#   · nano-banana-2、gemini-nano-banana-2.1、nano-banana-pro
#     非 auto 提交 aspect_ratio + image_size，不再把 pro 折成像素 size。
#   · auto 只传 image_size，不传 aspect_ratio
#     （传 auto 可能被 aspect_ratio_not_supported 拒），
#     也不再折成 size=1024x1024。
#   · 覆盖 auto + 10 种常用比 × 1K / 2K / 4K。
#     不再用下面仅 1K 的像素表判断 nano-banana-pro「不支持」。
#   · 控件选了 nano-banana-pro 就必须提交 pro；解析失败直接报错，不静默换模。
#
# 服务器直连源站实测（每张都下载图片读 PNG / JPEG 头）：
#   nano-banana-2          aspect 9:16 + 4K -> 3072x5504
#   nano-banana-2          aspect 16:9 + 2K -> 2752x1536
#   gemini-nano-banana-2.1 aspect 9:16 + 4K -> 3072x5504
#   gemini-nano-banana-2.1 aspect 2:3  + 2K -> 1696x2528
#   gemini-2.5-flash-image size  1344x768   -> 1344x768；传 2048x2048 被 400 拒
#
# 只能吃像素框的变体（gemini-2.5-flash-image），白名单是 Gemini 官方 10 个 1K 框。
_GEMINI_10_BOXES = {
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
}

# 走 aspect 形式的变体不进这张表（resolve_size 会提前返回「比例@档位」）。
# nano-banana-pro 同样走比例+档位，不能再用这张仅 1K 的表判定不支持。
_MODEL_SIZES = {
    "gemini-2.5-flash-image": _GEMINI_10_BOXES,
}

# 兼容基类的老字段：任一变体支持的最大像素集合
_SIZE_MAP = dict(_GEMINI_10_BOXES)


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
        "按比例 + 档位提交（不再用 1K 像素框判断 nano-banana-pro）：\n"
        "· nano-banana-2 —— 10 种比例 × 1K / 2K / 4K。"
        "实测 9:16+4K 出 3072x5504，16:9+2K 出 2752x1536\n"
        "· gemini-nano-banana-2.1 —— 同样 10 种比例 × 1K / 2K / 4K\n"
        "· nano-banana-pro —— 同样 10 种比例 × 1K / 2K / 4K。"
        "非 auto 提交 aspect_ratio + image_size；auto 只传 image_size。"
        "选 2K/4K 仍提交 nano-banana-pro，不会自动换成 nano-banana-2\n"
        "· gemini-2.5-flash-image —— 10 种比例，只有 1K 像素框"
    )

    RATIOS = _ASPECT_RATIOS
    RESOLUTIONS = _IMAGE_SIZES
    SIZE_FIELD = "image_size"
    SIZE_MAP = _SIZE_MAP
    # 走「比例 + 档位」形式的变体：站点直接把这两个字段交给上游。
    # 覆盖 auto + 10 种常用比 × 1K / 2K / 4K，不再用 _GEMINI_10_BOXES 判断 pro。
    # 非 auto 发 aspect_ratio + image_size；auto 只发 image_size
    # （传 auto 可能被 aspect_ratio_not_supported 拒）。
    # nano-banana-2 放在前面，gemini-2.5-flash-image 做不到时仍优先回退到它。
    ASPECT_PARAM_MODELS = [
        "nano-banana-2",
        "gemini-nano-banana-2.1",
        "nano-banana-pro",
    ]
    MODEL_SIZES = _MODEL_SIZES

    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1K"

    RATIO_TOOLTIP = (
        "画面比例。\n"
        "· 常用 10 种：1:1 2:3 3:2 3:4 4:3 4:5 5:4 9:16 16:9 21:9\n"
        "· nano-banana-pro / nano-banana-2 / gemini-nano-banana-2.1："
        "非 auto 提交 aspect_ratio + image_size；auto 只提交 image_size\n"
        "· gemini-2.5-flash-image 只有 1K。"
        "选到它做不到的组合时，节点会自动换一个能做的变体并在输出里写明。\n"
        "选 nano-banana-pro 时不会自动换模；组合无法解析会直接报错。"
    )
    RESOLUTION_TOOLTIP = (
        "分辨率档位。\n"
        "· nano-banana-pro / nano-banana-2 / gemini-nano-banana-2.1 —— 1K / 2K / 4K 全开，"
        "按 image_size 提交，不再把 pro 折成像素 size\n"
        "· gemini-2.5-flash-image —— 只有 1K\n"
        "选 nano-banana-pro 时保持 nano-banana-pro，不会因为 2K/4K 自动换成其它模型。"
    )

    REPLY_TYPES = ["async", "sync"]
    DEFAULT_REPLY_TYPE = "async"

    QUALITIES = []          # 本家族传 quality 会 HTTP 400 param_not_supported

    RETURN_NAMES = ("image", "response_text", "local_image_paths")

    # 默认用能力最全的变体：10 种比例 × 1K / 2K / 4K
    DEFAULT_MODEL = "nano-banana-2"
    NODE_ID = "xhcy_nano_banana"
    OUTPUT_PREFIX = "xhcy_nano_banana"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · Nano Banana 家族：不接参考图 = 文生图，"
        "接 image1~image16 = 多图参考。不同变体的尺寸能力不同，见 model 提示"
    )

    @classmethod
    def resolve_size(cls, aspect_ratio: str, resolution: str, model: str | None = None) -> str:
        """像素框变体的 auto 落到 1024x1024（站点 size 必填）。

        比例+档位变体（含 nano-banana-pro）不折成像素：
        auto 只留给 image_size，不传 aspect_ratio，也不再写成 size=1024x1024。
        """
        if aspect_ratio == "auto" and not (model and model in cls.ASPECT_PARAM_MODELS):
            return "1024x1024"
        return super().resolve_size(aspect_ratio, resolution, model)

    def allows_model_fallback(self, model: str) -> bool:
        """控件选了 nano-banana-pro 就必须提交 pro。解析失败直接报错，不静默换模。"""
        return model != "nano-banana-pro"


NODE_CLASS_MAPPINGS = {
    "xhcy_nano_banana": XHCYNanoBanana,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_nano_banana": "XHCY Nano Banana（文生图 / 多图参考）",
}
