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

_MODEL_SIZES = {
    "gpt-image-2": _GEMINI_10_BOXES,
    # vip 的白名单也换成了这套框，但它的上游仍是 GPT 系，只认 1280x720 这类
    # GPT 尺寸——实测 1344x768 会被上游拒（upstream_request_rejected）。
    # 这里按站点白名单配，实际可用性等站点修正后再验证。
    "gpt-image-2-vip": _GEMINI_10_BOXES,
}

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
        "同一家族的变体，尺寸能力差别很大：\n"
        "· gpt-image-2 —— 站点尺寸白名单只有 1024×1024（1:1 + 1K），选别的会被拒\n"
        "· gpt-image-2-all —— 上游**不接受 size 参数**，只能把画幅设为 auto，"
        "由模型自己决定尺寸\n"
        "· gpt-image-2-vip —— 站点不校验尺寸，十四种画幅 × 1K/2K/4K 全开\n"
        "要自由画幅请用 -vip。"
    )

    RATIOS = _RATIOS
    RESOLUTIONS = _RESOLUTIONS
    SIZE_MAP = _SIZE_MAP
    # 站点 2026-10-25 新契约：逐模型固定框，优先于 SIZE_MAP
    MODEL_SIZES = _MODEL_SIZES
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS

    # gpt-image-2-all 由 resolve_size 单独拦（上游拒收 size，只能 auto）。

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
        # -all 的上游拒收 size 字段，站点把它标记为直通模型。这里只能返回
        # "auto"（基类据此不往请求体里塞 size），选具体画幅反而会失败。
        if model == "gpt-image-2-all":
            if aspect_ratio != "auto":
                raise XHCYError(
                    "gpt-image-2-all 的上游不接受 size 参数，只能由模型自己决定尺寸。\n"
                    f"请把画幅改成 auto（你现在选的是 {aspect_ratio}）。\n"
                    "需要指定画幅，请换 gpt-image-2-vip。"
                )
            return "auto"
        return super().resolve_size(aspect_ratio, resolution, model)


NODE_CLASS_MAPPINGS = {
    "xhcy_gpt_image_2": XHCYGPTImage2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_gpt_image_2": "XHCY GPT Image 2（文生图 / 多图参考）",
}
