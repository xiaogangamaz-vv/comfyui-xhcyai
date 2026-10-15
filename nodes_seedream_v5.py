"""XHCY AI image node — Seedream 5.0 family.

一个节点覆盖整个家族：

    * 不接参考图          -> 文生图
    * 接 image1..image10  -> 多图参考（主体保持 / 局部改绘 / 多图融合）
    * 图层拆分变体        -> 必须**恰好**接 1 张图，输出 1 张底图 + 最多 16 个图层

参数来源（不是猜的）：
    1. 站点 ``/api/model_provider_meta`` 的 usage 字段 —— 给出各变体的能力与档位；
    2. 随站点一起分发的官方节点 ``comfyui-xinghuo-seedream/nodes.py``
       —— 里面就是这套 ``比例 + 档位 -> 像素`` 的映射表，本文件照抄其
       ``_SIZE_MAP_PRO``（1K / 1.5K / 2K，8 种画幅）；
    3. 站点后端源码 ``relay/billing/ratio/image.go`` —— 确认 size 传的是**像素**
       （``seedreamSizePixels`` 同时认 "1k"/"1.5k"/"2k" 与 "2048x2048" 这类写法，
       而 capability 策略把该家族标为 UnvalidatedPassThrough，即原样透传上游）。

变体差异：

    ==================================  ================  ====================
    变体                                档位              参考图上限
    ==================================  ================  ====================
    seedream-v5-flash                   1K / 1.5K / 2K    10
    seedream-v5-pro                     1K / 1.5K / 2K    10
    seedream-v5-flash/layer-decomposition  1K / 1.5K / 2K  1（固定）
    seedream-v5-pro/layer-decomposition    1K / 1.5K / 2K  1（固定）
    ==================================  ================  ====================

注意：图层拆分返回的图层通常带透明通道。落盘的 PNG 保留原始数据，
但传给下游 ComfyUI 节点的张量会统一转成 RGB（ComfyUI IMAGE 类型不含 alpha）。
"""

from __future__ import annotations

try:
    from .xhcy_client import XHCYError
    from .xhcy_image_base import XHCYImageBase
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import XHCYError  # type: ignore
    from xhcy_image_base import XHCYImageBase  # type: ignore


_RATIOS = ["auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]

_RESOLUTIONS = ["1K", "1.5K", "2K"]

# 与官方节点 _SIZE_MAP_PRO 完全一致
_SIZE_MAP: dict[tuple[str, str], str] = {
    ("1:1", "1K"): "1024x1024", ("4:3", "1K"): "1152x864",
    ("3:4", "1K"): "864x1152", ("16:9", "1K"): "1424x800",
    ("9:16", "1K"): "800x1424", ("3:2", "1K"): "1248x832",
    ("2:3", "1K"): "832x1248", ("21:9", "1K"): "1568x672",
    ("1:1", "1.5K"): "1536x1536", ("4:3", "1.5K"): "1792x1344",
    ("3:4", "1.5K"): "1344x1792", ("16:9", "1.5K"): "2048x1152",
    ("9:16", "1.5K"): "1152x2048", ("3:2", "1.5K"): "1872x1248",
    ("2:3", "1.5K"): "1248x1872", ("21:9", "1.5K"): "2352x1008",
    ("1:1", "2K"): "2048x2048", ("4:3", "2K"): "2368x1776",
    ("3:4", "2K"): "1776x2368", ("16:9", "2K"): "2816x1584",
    ("9:16", "2K"): "1584x2816", ("3:2", "2K"): "2496x1664",
    ("2:3", "2K"): "1664x2496", ("21:9", "2K"): "3136x1344",
}

_ALL_VARIANTS = [
    "seedream-v5-flash",
    "seedream-v5-pro",
    "seedream-v5-flash/layer-decomposition",
    "seedream-v5-pro/layer-decomposition",
]

_RESOLUTION_LIMITS = {name: list(_RESOLUTIONS) for name in _ALL_VARIANTS}

_LAYER_SUFFIX = "/layer-decomposition"


class XHCYSeedreamV5(XHCYImageBase):
    """Seedream 5.0 family — text-to-image, multi-reference and layer decomposition."""

    VARIANT_MODELS = list(_ALL_VARIANTS)

    MODEL_TOOLTIP = (
        "同一家族的变体。flash 单价更低；pro 偏向细节与像素级重绘。"
        "带 /layer-decomposition 后缀的两个变体是**图层拆分**："
        "必须且只需接 1 张图，输出 1 张底图加最多 16 个图层。"
    )

    # 站点给出该家族的参考图上限是 10 张（图层拆分固定 1 张）
    MAX_REFERENCES = 10

    RATIOS = _RATIOS
    RESOLUTIONS = _RESOLUTIONS
    SIZE_MAP = _SIZE_MAP
    RESOLUTION_LIMITS = _RESOLUTION_LIMITS

    QUALITIES = []          # 本家族没有画质档

    DEFAULT_MODEL = "seedream-v5-flash"
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1K"
    NODE_ID = "xhcy_seedream_v5"
    OUTPUT_PREFIX = "xhcy_seedream_v5"
    CATEGORY = "XHCY/Image"
    DESCRIPTION = (
        "XHCY AI · Seedream 5.0 家族：不接参考图 = 文生图，接 image1~image10 = 多图参考；"
        "layer-decomposition 变体做图层拆分（需接 1 张图）"
    )

    @classmethod
    def check_references(cls, model: str, references: list) -> None:
        # 图层拆分是「一张图进去、一层层出来」，上游只接受单张输入。
        # 与其让它到上游才报错，不如在这里就讲清楚。
        if model.endswith(_LAYER_SUFFIX) and len(references) != 1:
            raise XHCYError(
                "图层拆分（layer-decomposition）需要且只需要 1 张输入图片，"
                f"当前接了 {len(references)} 张。"
                "请把要拆分的图只连到 image1，其余参考图入口留空。"
            )


NODE_CLASS_MAPPINGS = {
    "xhcy_seedream_v5": XHCYSeedreamV5,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_seedream_v5": "XHCY Seedream 5.0（文生图 / 多图参考 / 图层拆分）",
}
