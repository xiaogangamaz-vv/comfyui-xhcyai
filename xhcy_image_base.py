"""Reusable base for XHCY image nodes: text-to-image *and* multi-reference editing.

The same node handles both modes automatically:
    * no reference image connected  -> pure text-to-image
    * one or more images connected  -> multi-reference generation

Reference images are sent as base64 data URIs in the `image` array of
POST /v1/images/generations — verified against the live service:
    * `image: ["data:image/..."]`  -> 200 OK
    * a public http(s) URL in that field -> 400 upstream_request_rejected

Adding a new image model later should only require subclassing XHCYImageBase
and declaring its variant list, size map and limits.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid

import numpy as np
import torch
from PIL import Image

try:  # provided by ComfyUI
    import folder_paths  # type: ignore
except ImportError:
    folder_paths = None  # type: ignore

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        STATUS_SUCCESS,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_image_urls,
        extract_inline_images,
        extract_status,
        extract_task_id,
    )
    from .xhcy_credentials import resolve_credentials as _resolve_credentials
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        STATUS_SUCCESS,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_image_urls,
        extract_inline_images,
        extract_status,
        extract_task_id,
    )
    from xhcy_credentials import resolve_credentials as _resolve_credentials  # type: ignore


# ---------------------------------------------------------------------- #
# Reference-image limits
#
# Measured on the live service: a 512x512 PNG data URI made the request blow
# through the gateway timeout (HTTP 524), while a small JPEG returned in ~80s.
# Multi-reference requests are therefore kept deliberately compact.
# ---------------------------------------------------------------------- #

MAX_REFERENCE_IMAGES = 16
MAX_REFERENCE_EDGE = 1536          # longest side after downscale
REFERENCE_JPEG_QUALITY = 90
MAX_REFERENCE_BYTES = 6 * 1024 * 1024    # per image, after encoding
MAX_REFERENCE_TOTAL = 24 * 1024 * 1024   # whole request


def _comfy_manager():
    try:
        import comfy.model_management as manager  # type: ignore
    except Exception:
        return None
    return manager


def check_interrupt() -> None:
    """Honour the Cancel button while polling."""
    manager = _comfy_manager()
    if manager is not None:
        manager.throw_exception_if_processing_interrupted()


def sleep_interruptible(seconds: float) -> None:
    deadline = time.time() + max(0.0, float(seconds))
    while True:
        check_interrupt()
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


def _output_dir() -> str:
    if folder_paths is not None:
        try:
            return folder_paths.get_output_directory()
        except Exception:
            pass
    return os.getcwd()


def _int_param(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise XHCYError(f"{name} 必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise XHCYError(f"{name} 必须是整数") from exc
    if not low <= number <= high:
        raise XHCYError(f"{name} 必须在 {low} 到 {high} 之间")
    return number


def tensor_to_data_uri(tensor: torch.Tensor) -> str:
    """ComfyUI IMAGE tensor -> compact base64 data URI (the only form the API accepts)."""
    array = (tensor.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    if array.ndim == 3 and array.shape[2] == 4:
        image = Image.fromarray(array, "RGBA").convert("RGB")
    elif array.ndim == 3 and array.shape[2] == 3:
        image = Image.fromarray(array, "RGB")
    elif array.ndim == 2:
        image = Image.fromarray(array, "L").convert("RGB")
    else:
        raise XHCYError(f"参考图格式无法识别，shape={getattr(array, 'shape', '?')}")

    if max(image.size) > MAX_REFERENCE_EDGE:
        scale = MAX_REFERENCE_EDGE / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=REFERENCE_JPEG_QUALITY, optimize=True)
    raw = buffer.getvalue()
    if len(raw) > MAX_REFERENCE_BYTES:
        raise XHCYError(
            "参考图压缩后仍超过 %.0f MiB，请先缩小后再连接"
            % (MAX_REFERENCE_BYTES / 1024 / 1024)
        )
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def payload_snippet(payload: dict, limit: int = 400) -> str:
    """把服务端原始返回压成一行短文本，附在报错里。

    没有这一段的时候，凡是「200 但没有图片也没有任务 ID」都会被压成同一句话，
    线上出了事只能靠猜。base64 一律省略，避免把报错刷成几百 KB。
    """
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload)
    marker = "base64,"
    if marker in text:
        text = text[: text.index(marker) + len(marker)] + "…<base64 已省略>"
    # data[].b64_json 这类字段没有 data-URI 前缀，靠长度判断：真正的图片
    # base64 一定很长，短字符串（模型名、task id）不会被误伤。
    text = re.sub(r'"([A-Za-z0-9+/=]{200,})"', '"…<base64 已省略>"', text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "（空响应）"


def resolve_credentials(api_key, base_url) -> tuple[str, str]:
    """兼容旧调用点：实现在 xhcy_credentials 里，图片/视频节点共用同一份。"""
    return _resolve_credentials(api_key, base_url)


class XHCYImageBase:
    """Base class shared by every XHCY image node.

    Subclasses declare the model family (VARIANT_MODELS), the ratio/resolution
    to pixel map and the per-model limits. Everything else — reference-image
    handling, submission, polling, saving and error reporting — lives here.
    """

    # --- to be declared by subclasses ---
    VARIANT_MODELS: list[str] = []
    # 节点上出现几个参考图入口；子类可按模型上限调小（例如 seedream 只吃 10 张）
    MAX_REFERENCES = MAX_REFERENCE_IMAGES
    # 选的组合当前变体做不到时，是否自动换成本家族里能做到的变体。
    # 开着是为了不让工作流卡在报错上；关掉就退回「直接报错」的严格模式。
    AUTO_MODEL_FALLBACK = True
    # 哪些变体用站点的「比例 + 档位」形式（aspect_ratio + image_size）
    # 而不是像素框（size）。这些变体因此能出 2K / 4K，不受 10 个 1K 框限制。
    # 站点 2026-10-26 实测：2:3@2K、9:16@2K、16:9@4K 均 200 出图。
    ASPECT_PARAM_MODELS: list[str] = []
    SIZES: list[str] = ["auto", "1024x1024", "1536x1024", "1024x1536"]
    QUALITIES: list[str] = ["auto", "low", "medium", "high"]
    RATIOS: list[str] = [
        "auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
        "16:9", "9:16", "2:1", "1:2", "21:9", "9:21",
    ]
    RESOLUTIONS: list[str] = ["1k", "2k", "4k"]
    SIZE_MAP: dict[tuple[str, str], str] = {}
    RESOLUTION_LIMITS: dict[str, list[str]] = {}
    # 按模型精确声明「哪些 (画幅, 分辨率) 真的能用」以及对应像素。
    #
    # 为什么需要它：站点的尺寸白名单是**逐模型**的，同一个家族里有的变体只认
    # 一个尺寸、有的变体认八种。只用 SIZE_MAP 一张全量表，会让用户选到某个
    # 变体根本不接受的组合，撞上 size_not_supported。
    #
    # 结构：{模型名: {(画幅, 分辨率): "宽x高"}}
    # 模型不在表里时退回 SIZE_MAP（视作不限制）。
    MODEL_SIZES: dict[str, dict[tuple[str, str], str]] = {}
    DEFAULT_MODEL = ""
    DEFAULT_SIZE = "1024x1024"
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1k"
    # 参数开关，由子类决定节点上出现哪些尺寸控件：
    #   FIXED_SIZE 非空 -> 不显示 aspect_ratio / resolution，固定使用该像素尺寸
    #   QUALITIES 为空列表 -> 不显示 quality
    FIXED_SIZE = ""
    MODEL_TOOLTIP = "同一家族的变体，切换即可换模型。"
    # 尺寸档位控件的字段名（有的站叫 resolution，有的叫 image_size）
    SIZE_FIELD = "resolution"
    RATIO_TOOLTIP = "auto 表示交给服务端决定画幅。"
    RESOLUTION_TOOLTIP = "分辨率档位，节点会换算成接口要求的像素尺寸。"
    # 非空则在节点上追加 reply_type 下拉
    REPLY_TYPES: list[str] = []
    DEFAULT_REPLY_TYPE = "async"
    REPLY_TOOLTIP = "提交方式；本站不支持异步图像生成，实际都会按同步执行。"
    NODE_ID = "xhcy_image_base"
    OUTPUT_PREFIX = "xhcy_image"

    CATEGORY = "XHCY/Image"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "status", "saved_paths")
    FUNCTION = "generate"
    OUTPUT_NODE = False

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #

    @classmethod
    def INPUT_TYPES(cls):
        # image1..image16 are optional: leave them unconnected for
        # text-to-image, connect one or more for multi-reference generation.
        optional = {
            f"image{i}": (
                "IMAGE",
                {
                    "tooltip": (
                        "参考图 #%d。不连任何参考图 = 文生图；连了就按多图参考生成。"
                        "参考图越多越慢，建议不超过 3～4 张。" % i
                    )
                },
            )
            for i in range(1, cls.MAX_REFERENCES + 1)
        }
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "提示词。留空会直接报错，不会白白扣费。",
                    },
                ),
                "model": (
                    list(cls.VARIANT_MODELS),
                    {
                        "default": cls.DEFAULT_MODEL or (cls.VARIANT_MODELS[0] if cls.VARIANT_MODELS else ""),
                        "tooltip": cls.MODEL_TOOLTIP,
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "defaultInput": True,
                        "tooltip": "XHCY AI 访问密钥。每个节点单独填。",
                    },
                ),
                **cls.shape_inputs(),
                "max_poll_attempts": (
                    "INT",
                    {"default": 300, "min": 1, "max": 2000, "tooltip": "最多查询多少次结果。"},
                ),
                "poll_interval": (
                    "INT",
                    {"default": 5, "min": 1, "max": 60, "tooltip": "每次查询之间等几秒。"},
                ),
                "base_url": (
                    "STRING",
                    {
                        "default": DEFAULT_BASE_URL,
                        "multiline": False,
                        "tooltip": "站点地址，一般不用改。",
                    },
                ),
            },
            "optional": optional,
        }

    # ------------------------------------------------------------------ #
    # Helpers subclasses may override
    # ------------------------------------------------------------------ #

    @classmethod
    def shape_inputs(cls) -> dict:
        """节点上要出现哪些尺寸控件；子类用 FIXED_SIZE / QUALITIES 关掉。

        有些模型只接受一个固定尺寸（例如 nano-banana 系列只吃 1024x1024），
        这种节点就不该摆一堆用不上的下拉。
        """
        inputs: dict = {}
        if not cls.FIXED_SIZE:
            inputs["aspect_ratio"] = (
                cls.ratio_choices(),
                {"default": cls.DEFAULT_RATIO, "tooltip": cls.RATIO_TOOLTIP},
            )
            inputs[cls.SIZE_FIELD] = (
                cls.resolution_choices(),
                {"default": cls.DEFAULT_RESOLUTION, "tooltip": cls.RESOLUTION_TOOLTIP},
            )
        if cls.REPLY_TYPES:
            inputs["reply_type"] = (
                list(cls.REPLY_TYPES),
                {"default": cls.DEFAULT_REPLY_TYPE, "tooltip": cls.REPLY_TOOLTIP},
            )
        if cls.QUALITIES:
            inputs["quality"] = (
                list(cls.QUALITIES),
                {"default": "auto", "tooltip": "画质档位；auto 表示不指定。"},
            )
        return inputs

    @classmethod
    def resolve_size(cls, aspect_ratio: str, resolution: str, model: str | None = None) -> str:
        """(画幅, 分辨率) -> 接口要求的像素尺寸。

        model 用于按变体做精确限制：站点对同一家族里的不同变体给出的尺寸
        白名单并不一样（有的只认 1024x1024，有的认八种）。子类把逐模型的表
        放在 MODEL_SIZES 里，这里统一校验。
        """
        if aspect_ratio == "auto":
            return "auto"

        # 用「比例 + 档位」形式的变体不查像素表——站点按比例换算，
        # 档位就是 1K / 2K / 4K。返回一个说明串只用于日志与摘要。
        if model and model in cls.ASPECT_PARAM_MODELS:
            return f"{aspect_ratio}@{resolution}"

        # 该模型单独声明过尺寸表 -> 只认表里的组合
        table = cls.MODEL_SIZES.get(model) if model else None
        if table:
            size = table.get((aspect_ratio, resolution))
            if size is None:
                supported = [f"{r} @ {s}" for (r, s) in sorted(table)]
                # 直接算出「换哪个变体就能用」，别让人自己猜
                alternatives = cls.suggest_models(aspect_ratio, resolution)
                tip = ""
                if alternatives:
                    tip = (
                        f"\n想用「{aspect_ratio} + {resolution}」，"
                        f"请把 model 换成：{' 或 '.join(alternatives)}"
                    )
                raise XHCYError(
                    f"{model} 不支持「{aspect_ratio} + {resolution}」。\n"
                    f"它在本站可用的组合只有：{'、'.join(supported)}{tip}"
                )
            return size

        if not cls.SIZE_MAP:
            return "auto"
        size = cls.SIZE_MAP.get((aspect_ratio, resolution))
        if size is None:
            raise XHCYError(f"不支持的画幅组合：{aspect_ratio} × {resolution}")
        return size

    @classmethod
    def suggest_models(cls, aspect_ratio: str, resolution: str) -> list[str]:
        """哪些变体支持这个 (画幅, 档位)。用于报错时直接给出可选项。"""
        hits: list[str] = []
        for model, table in (cls.MODEL_SIZES or {}).items():
            if (aspect_ratio, resolution) in table:
                hits.append(model)
        # 走「比例 + 档位」形式的变体不查像素表：只要档位合法就算支持。
        # 少了这段，回退会找不到候选（2026-10-26 踩到）。
        for model in (cls.ASPECT_PARAM_MODELS or []):
            if model not in hits and str(resolution).upper() in ("1K", "2K", "4K"):
                hits.append(model)
        return hits

    @classmethod
    def ratio_choices(cls) -> list[str]:
        """画幅下拉的候选：把所有模型声明过的画幅取并集。

        ComfyUI 的下拉不能跟着 model 联动，所以这里给全量并集，
        选了当前模型不支持的时候由 resolve_size 给出明确提示。
        """
        # 先把类声明的画幅全放进去（否则 -flare 这类「只查像素范围、不限具体框」
        # 的变体会被 MODEL_SIZES 收窄，下拉里看不到 21:9 / 2:1 等）。
        seen: list[str] = []
        source = cls.RATIOS
        for ratio in source:
            if ratio not in seen:
                seen.append(ratio)
        if cls.MODEL_SIZES:
            for table in cls.MODEL_SIZES.values():
                for (ratio, _res) in table:
                    if ratio not in seen:
                        seen.append(ratio)
        if seen:
            # 保留 auto 在最前面（如果原本有）
            if "auto" in source and "auto" not in seen:
                seen.insert(0, "auto")
            elif "auto" in seen:
                seen.remove("auto")
                seen.insert(0, "auto")
            return seen
        return list(source)

    @classmethod
    def resolution_choices(cls) -> list[str]:
        """分辨率下拉的候选：把所有模型声明过的档位取并集。"""
        seen: list[str] = []
        if cls.MODEL_SIZES:
            for table in cls.MODEL_SIZES.values():
                for (_ratio, res) in table:
                    if res not in seen:
                        seen.append(res)
        # 逐模型的档位限制也要并进来：gpt-image-2.5 的 MODEL_SIZES 只登记了基版
        # 的 1k 框，而 -flare / -sunburst 靠 RESOLUTION_LIMITS 声明 2k/4k。
        # 少了这段，下拉里只剩 1k（2026-10-29 踩到）。
        if cls.RESOLUTION_LIMITS:
            for tiers in cls.RESOLUTION_LIMITS.values():
                for tier in tiers:
                    if tier not in seen:
                        seen.append(tier)
        # 走「比例 + 档位」的变体支持 1K/2K/4K，但像素表里只有 1K 框，
        # 少了这段档位下拉会缺 2K（2026-10-26 踩到）。
        if cls.ASPECT_PARAM_MODELS:
            for tier in ("1K", "2K", "4K"):
                if tier not in seen:
                    seen.append(tier)
        if seen:
            # 统一成 1K → 2K → 4K 的顺序（大小写混用也能排对）
            order = {"1K": 0, "2K": 1, "4K": 2}
            seen.sort(key=lambda t: order.get(t.upper(), 99))
            return seen
        return list(cls.RESOLUTIONS)

    @classmethod
    def allowed_resolutions(cls, model: str) -> list[str]:
        if model and model in cls.ASPECT_PARAM_MODELS:
            return ["1K", "2K", "4K"]
        return cls.RESOLUTION_LIMITS.get(model, cls.RESOLUTIONS)

    @classmethod
    def check_references(cls, model: str, references: list) -> None:
        """子类可覆盖：按所选模型校验参考图数量。默认不限制。"""
        return None

    @classmethod
    def collect_reference_images(cls, kwargs: dict) -> list[str]:
        """Turn every connected IMAGE input into a data URI (batches expanded)."""
        collected: list[str] = []
        total = 0
        for index in range(1, cls.MAX_REFERENCES + 1):
            batch = kwargs.get(f"image{index}")
            if batch is None:
                continue
            if not isinstance(batch, torch.Tensor) or batch.ndim != 4:
                raise XHCYError(f"image{index} 必须是 ComfyUI 的 IMAGE 输入")
            for item in batch:
                if len(collected) >= cls.MAX_REFERENCES:
                    raise XHCYError(f"参考图最多 {cls.MAX_REFERENCES} 张")
                uri = tensor_to_data_uri(item)
                total += len(uri)
                if total > MAX_REFERENCE_TOTAL * 1.4:  # base64 体积约为原始 1.34 倍
                    raise XHCYError(
                        "参考图总体积过大，请减少张数或先缩小分辨率再连接"
                    )
                collected.append(uri)
        return collected

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def generate(self, prompt, model, api_key, max_poll_attempts, poll_interval,
                 base_url=DEFAULT_BASE_URL,
                 aspect_ratio=None, resolution=None, quality="auto", **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        api_key, base_url = resolve_credentials(api_key, base_url)
        if self.VARIANT_MODELS and model not in self.VARIANT_MODELS:
            raise XHCYError(f"未知的模型：{model}")

        # 尺寸档位字段名可能被改过（resolution / image_size），ComfyUI 是按名字传参的。
        # 缺省时回落到子类声明的默认值，避免沿用小写的 "1k"（nano-banana 用的是大写 "1K"）。
        resolution = kwargs.get(self.SIZE_FIELD) or resolution or self.DEFAULT_RESOLUTION
        aspect_ratio = aspect_ratio or self.DEFAULT_RATIO

        self._fallback_note = ""

        if self.FIXED_SIZE:
            # 该模型只有一个固定尺寸（例如 nano-banana 只吃 1024x1024）
            size = self.FIXED_SIZE
        else:
            def _resolve_for(name: str) -> str:
                allowed = self.allowed_resolutions(name)
                if aspect_ratio != "auto" and resolution not in allowed:
                    raise XHCYError(
                        f"{name} 不支持 {resolution} 分辨率；可选：{'、'.join(allowed)}"
                    )
                return self.resolve_size(aspect_ratio, resolution, name)

            try:
                size = _resolve_for(model)
            except XHCYError:
                # 自动回退：同家族里换一个真能出这个组合的变体。
                #
                # 目的是不让工作流卡死。model 一旦固定成某个变体，换画幅或
                # 档位是很自然的事；直接报错就得手动改下拉，批量跑尤其难受。
                # 这里自动挑一个支持的变体，并把「换成了谁」写进输出，保持透明。
                fallback = None
                if self.AUTO_MODEL_FALLBACK:
                    candidates = [
                        m
                        for m in self.suggest_models(aspect_ratio, resolution)
                        if m in (self.VARIANT_MODELS or [])
                    ]
                    if candidates:
                        fallback = candidates[0]
                if fallback is None:
                    raise
                size = _resolve_for(fallback)
                self._fallback_note = (
                    f"已自动把 model 从 {model} 换成 {fallback}"
                    f"（{model} 不支持 {aspect_ratio} + {resolution}）"
                )
                model = fallback

        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)

        check_interrupt()
        references = self.collect_reference_images(kwargs)
        self.check_references(model, references)

        client = XHCYClient(api_key, base_url)
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "response_format": "url",
        }
        # 走「比例 + 档位」的变体（站点侧的 Gemini 原生协议模型）：
        # 直接发 aspect_ratio + image_size，站点会把它们写进上游的 imageConfig。
        # 站点只接受公开集合里的值（1:1 3:2 2:3 3:4 4:3 4:5 5:4 9:16 16:9 21:9
        # 与 1K / 2K / 4K），所以 auto 必须不传，否则会被 aspect_ratio_not_supported 拒。
        if model in self.ASPECT_PARAM_MODELS:
            if aspect_ratio and aspect_ratio != "auto":
                payload["aspect_ratio"] = aspect_ratio
            if resolution:
                payload["image_size"] = str(resolution).upper()
        elif size != "auto":
            payload["size"] = size
        if quality and quality != "auto":
            payload["quality"] = quality
        if references:
            # Multi-reference mode: this is what makes it image-to-image.
            payload["image"] = references

        first = client.submit_image(payload)
        result = self._resolve_result(client, first, attempts, interval)

        urls = extract_image_urls(result)
        inline = extract_inline_images(result)
        if not urls and not inline:
            raise XHCYError("生成完成，但返回里没有找到图片地址")

        tensors, paths = [], []
        if inline and not urls:
            # ai.xhcyai.org 的 /v1/images/generations 即使请求里写了
            # response_format=url，仍然把图片以 data[].b64_json 内嵌返回。
            # 这类响应用户侧是成功的（也已经计费），直接解码保存，不再发下载请求。
            for index, raw in enumerate(inline, start=1):
                check_interrupt()
                tensor, path = self._save_image(raw, index)
                tensors.append(tensor)
                paths.append(path)
        else:
            for index, url in enumerate(urls, start=1):
                check_interrupt()
                raw = client.download(url)
                tensor, path = self._save_image(raw, index)
                tensors.append(tensor)
                paths.append(path)

        if len({tuple(t.shape) for t in tensors}) > 1:
            raise XHCYError("服务端返回了尺寸不一致的多张图片，无法合并成一批")

        mode_text = f"多图参考（{len(references)} 张）" if references else "文生图"
        size_text = (
            f"尺寸：{size}"
            if self.FIXED_SIZE
            else f"画幅：{aspect_ratio} @ {resolution}（{size}）"
        )
        task_id = extract_task_id(result) or extract_task_id(first) or "-"
        note = getattr(self, "_fallback_note", "")
        summary = (
            f"XHCY 生成成功\n"
            f"模式：{mode_text}\n"
            f"模型：{model}\n"
            f"{size_text}\n"
            f"任务：{task_id}\n"
            f"张数：{len(paths)}\n"
            + (f"提示：{note}\n" if note else "")
            + f"文件：\n" + "\n".join(paths)
        )
        if note:
            print(f"[XHCY] {note}")
        return (torch.stack(tensors), summary, "\n".join(paths))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_result(client: XHCYClient, first: dict, attempts: int, interval: int) -> dict:
        """Use a synchronous answer directly, otherwise poll by task id."""
        status = extract_status(first)
        # The gateway may link the result or embed it as base64; both mean "done".
        if (extract_image_urls(first) or extract_inline_images(first)) and status not in STATUS_FAILURE:
            return first

        task_id = extract_task_id(first)
        if not task_id:
            hint = ""
            if isinstance(first.get("data"), list) and not first.get("data"):
                hint = (
                    "服务端返回了空的图片列表（这一单在平台侧可能已经计费，"
                    "需要去后台核对这笔请求是否要退款）；"
                )
            raise XHCYError(
                "服务端既没直接返回图片，也没返回任务 ID。"
                + hint
                + "服务端原始返回：" + payload_snippet(first)
            )

        last_status = status or "处理中"
        for _ in range(attempts):
            sleep_interruptible(interval)
            check_interrupt()
            current = XHCYImageBase._poll_with_retry(client, task_id)
            status = extract_status(current)
            if status:
                last_status = status
            if status in STATUS_SUCCESS:
                return current
            if status in STATUS_FAILURE:
                raise XHCYError(f"生成失败：{extract_failure_reason(current) or '服务端未给出原因'}")
            if not status and (extract_image_urls(current) or extract_inline_images(current)):
                return current
        raise XHCYError(f"等待超时，已查询 {attempts} 次，最后状态：{last_status}")

    @staticmethod
    def _poll_with_retry(client: XHCYClient, task_id: str, retries: int = 2) -> dict:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return client.poll_image(task_id)
            except XHCYError as exc:
                message = str(exc)
                if "HTTP 401" in message or "HTTP 403" in message:
                    raise
                last_error = exc
                if attempt < retries:
                    sleep_interruptible(2)
        raise last_error if last_error else XHCYError("结果查询失败")

    def _save_image(self, raw: bytes, index: int) -> tuple[torch.Tensor, str]:
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception as exc:
            raise XHCYError("服务端返回的内容不是有效图片") from exc

        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}.get(
            (image.format or "").upper(), "png"
        )
        directory = _output_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(
            directory, f"{self.OUTPUT_PREFIX}_{index}_{uuid.uuid4().hex[:8]}.{ext}"
        )
        with open(path, "wb") as handle:
            handle.write(raw)

        tensor = torch.from_numpy(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
        return tensor, path
