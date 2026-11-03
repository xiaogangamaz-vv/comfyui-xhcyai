"""XHCY AI image node — GPT Image 2 family.

一个节点覆盖整个家族，同时支持两种模式：

    * 不接参考图          -> 文生图
    * 接 image1..image16  -> 多图参考生成

公共逻辑（参考图压缩、提交、轮询、落盘、报错）都在
xhcy_image_base.XHCYImageBase；这里只声明本家族特有的参数。

变体差异（2026-10-29 按站点实测重写）：

    ==================  ==================  ==================================
    变体                分辨率              说明
    ==================  ==================  ==================================
    gpt-image-2         1K / 2K / 4K        与 -vip 能力一致，价格更低
    gpt-image-2-vip     1K / 2K / 4K        同上
    ==================  ==================  ==================================

关于尺寸：站点对整个 GPT-Image 家族声明的是 **SizeRange**——
边长必须是 16 的倍数、长边 ≤ 3840、总像素 ≤ 8.3MP。
在范围内任意像素框都可以，1K / 2K / 4K 实测都出图；
超范围（如 4096x4096 = 16.7MP）会被 400 size_not_supported 拒。
``gpt-image-2-all`` 已从站点公开模型列表下线，本节点不再提供。
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

# 站点 2026-10-25 的 image-contract 版本：gpt-image-2 与 -vip 改用 Gemini 的
# 10 个比例框（代码里叫 geminiAspectBoxes，全部是 1K 档）。
# 原表里的 1280x720 / 2048x2048 等已不在白名单内，会被拒。
_GEMINI_10_BOXES = {
    ("1:1", "1k"): "1024x1024",
    ("2:3", "1k"): "848x1264",
    ("3:2", "1k"): "1264x848",
    ("3:4", "1k"): "896x1200",
    ("4:3", "1k"): "1200x896",
    ("4:5", "1k"): "928x1152",
    ("5:4", "1k"): "1152x928",
    ("9:16", "1k"): "768x1344",
    ("16:9", "1k"): "1344x768",
    ("21:9", "1k"): "1536x672",
}

# 站点 2026-10-29（tag 20261029-dashboard-topmodels）给整个 GPT-Image 家族
# 声明的是 SizeRange，而不是固定框：
#   边长必须是 16 的倍数、长边 ≤ 3840、总像素 ≤ 8.3MP。
# 实测（服务器直连源站，下载后量像素）：
#   gpt-image-2      2048x2048 -> 2048x2048 ✅
#   gpt-image-2      4096x4096 -> 400 size_not_supported（16.7MP 超上限）
#   gpt-image-2      3840x2160 -> 3840x2160 ✅
#   gpt-image-2-vip  3840x2160 -> 3840x2160 ✅
# 所以不再按「逐模型固定框」限制，直接用下面那张全表（它已经满足 SizeRange）。
# 注意：gpt-image-2-all 已从站点公开模型列表下线，本节点不再提供。
_MODEL_SIZES: dict[str, dict] = {}

# 两个变体都能出 1K / 2K / 4K
_RESOLUTION_LIMITS = {
    "gpt-image-2": ["1k", "2k", "4k"],
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

    # gpt-image-2-all 已从站点公开模型列表下线（/api/public-models 里没有），
    # 选了只会报「无可用渠道」，所以从下拉里移除。
    VARIANT_MODELS = ["gpt-image-2", "gpt-image-2-vip"]

    MODEL_TOOLTIP = (
        "2026-10-29 实测：两个变体都是「任意合规像素框」，能力一致。\n"
        "· 站点契约：边长必须是 16 的倍数、长边 ≤ 3840、总像素 ≤ 8.3MP\n"
        "· 1K / 2K / 4K 三档都实测出图（如 2048x2048、3840x2160、2160x3840）\n"
        "· 14 种画幅全开；4096x4096 这类超过 8.3MP 的会被站点拒\n"
        "两个变体只差价格与渠道，按需选；要最稳就选 -vip。"
    )

    RATIOS = _RATIOS
    RESOLUTIONS = _RESOLUTIONS
    SIZE_MAP = _SIZE_MAP
    MODEL_SIZES = _MODEL_SIZES
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS

    QUALITIES = []          # 本站未给出该家族的画质档，不显示

    DEFAULT_MODEL = "gpt-image-2-vip"
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
        return super().resolve_size(aspect_ratio, resolution, model)


NODE_CLASS_MAPPINGS = {
    "xhcy_gpt_image_2": XHCYGPTImage2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_gpt_image_2": "XHCY GPT Image 2（文生图 / 多图参考）",
}
