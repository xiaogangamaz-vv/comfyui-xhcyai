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
import os
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
        extract_status,
        extract_task_id,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        STATUS_SUCCESS,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_image_urls,
        extract_status,
        extract_task_id,
    )


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


class XHCYImageBase:
    """Base class shared by every XHCY image node.

    Subclasses declare the model family (VARIANT_MODELS), the ratio/resolution
    to pixel map and the per-model limits. Everything else — reference-image
    handling, submission, polling, saving and error reporting — lives here.
    """

    # --- to be declared by subclasses ---
    VARIANT_MODELS: list[str] = []
    SIZES: list[str] = ["auto", "1024x1024", "1536x1024", "1024x1536"]
    QUALITIES: list[str] = ["auto", "low", "medium", "high"]
    RATIOS: list[str] = [
        "auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
        "16:9", "9:16", "2:1", "1:2", "21:9", "9:21",
    ]
    RESOLUTIONS: list[str] = ["1k", "2k", "4k"]
    SIZE_MAP: dict[tuple[str, str], str] = {}
    RESOLUTION_LIMITS: dict[str, list[str]] = {}
    DEFAULT_MODEL = ""
    DEFAULT_SIZE = "1024x1024"
    DEFAULT_RATIO = "1:1"
    DEFAULT_RESOLUTION = "1k"
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
            for i in range(1, MAX_REFERENCE_IMAGES + 1)
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
                        "tooltip": "同一家族的变体，切换即可换模型。",
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
                "aspect_ratio": (
                    list(cls.RATIOS),
                    {"default": cls.DEFAULT_RATIO, "tooltip": "auto 表示交给服务端决定画幅。"},
                ),
                "resolution": (
                    list(cls.RESOLUTIONS),
                    {"default": cls.DEFAULT_RESOLUTION, "tooltip": "分辨率档位，节点会换算成接口要求的像素尺寸。"},
                ),
                "quality": (
                    list(cls.QUALITIES),
                    {"default": "auto", "tooltip": "画质档位；auto 表示不指定。"},
                ),
                "max_poll_attempts": (
                    "INT",
                    {"default": 60, "min": 1, "max": 600, "tooltip": "最多查询多少次结果。"},
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
    def resolve_size(cls, aspect_ratio: str, resolution: str) -> str:
        if aspect_ratio == "auto":
            return "auto"
        if not cls.SIZE_MAP:
            return "auto"
        size = cls.SIZE_MAP.get((aspect_ratio, resolution))
        if size is None:
            raise XHCYError(f"不支持的画幅组合：{aspect_ratio} × {resolution}")
        return size

    @classmethod
    def allowed_resolutions(cls, model: str) -> list[str]:
        return cls.RESOLUTION_LIMITS.get(model, cls.RESOLUTIONS)

    @classmethod
    def collect_reference_images(cls, kwargs: dict) -> list[str]:
        """Turn every connected IMAGE input into a data URI (batches expanded)."""
        collected: list[str] = []
        total = 0
        for index in range(1, MAX_REFERENCE_IMAGES + 1):
            batch = kwargs.get(f"image{index}")
            if batch is None:
                continue
            if not isinstance(batch, torch.Tensor) or batch.ndim != 4:
                raise XHCYError(f"image{index} 必须是 ComfyUI 的 IMAGE 输入")
            for item in batch:
                if len(collected) >= MAX_REFERENCE_IMAGES:
                    raise XHCYError(f"参考图最多 {MAX_REFERENCE_IMAGES} 张")
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

    def generate(self, prompt, model, api_key, aspect_ratio, resolution, quality,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL, **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        if self.VARIANT_MODELS and model not in self.VARIANT_MODELS:
            raise XHCYError(f"未知的模型：{model}")

        allowed = self.allowed_resolutions(model)
        if aspect_ratio != "auto" and resolution not in allowed:
            raise XHCYError(
                f"{model} 不支持 {resolution} 分辨率；可选：{'、'.join(allowed)}"
            )

        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)
        size = self.resolve_size(aspect_ratio, resolution)

        check_interrupt()
        references = self.collect_reference_images(kwargs)

        client = XHCYClient(api_key, base_url)
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "response_format": "url",
        }
        if size != "auto":
            payload["size"] = size
        if quality and quality != "auto":
            payload["quality"] = quality
        if references:
            # Multi-reference mode: this is what makes it image-to-image.
            payload["image"] = references

        first = client.submit_image(payload)
        result = self._resolve_result(client, first, attempts, interval)

        urls = extract_image_urls(result)
        if not urls:
            raise XHCYError("生成完成，但返回里没有找到图片地址")

        tensors, paths = [], []
        for index, url in enumerate(urls, start=1):
            check_interrupt()
            raw = client.download(url)
            tensor, path = self._save_image(raw, index)
            tensors.append(tensor)
            paths.append(path)

        if len({tuple(t.shape) for t in tensors}) > 1:
            raise XHCYError("服务端返回了尺寸不一致的多张图片，无法合并成一批")

        mode_text = f"多图参考（{len(references)} 张）" if references else "文生图"
        task_id = extract_task_id(result) or extract_task_id(first) or "-"
        summary = (
            f"XHCY 生成成功\n"
            f"模式：{mode_text}\n"
            f"模型：{model}\n"
            f"画幅：{aspect_ratio} @ {resolution}（{size}）\n"
            f"任务：{task_id}\n"
            f"张数：{len(paths)}\n"
            f"文件：\n" + "\n".join(paths)
        )
        return (torch.stack(tensors), summary, "\n".join(paths))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_result(client: XHCYClient, first: dict, attempts: int, interval: int) -> dict:
        """Use a synchronous answer directly, otherwise poll by task id."""
        status = extract_status(first)
        if extract_image_urls(first) and status not in STATUS_FAILURE:
            return first

        task_id = extract_task_id(first)
        if not task_id:
            raise XHCYError("服务端既没直接返回图片，也没返回任务 ID")

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
            if not status and extract_image_urls(current):
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
