"""XHCY AI image node — GPT Image 2.5 family.

One node covers the whole family; the `model` dropdown switches between the
variants that live under the same name on ai.xhcyai.org:

    gpt-image-2.5 / gpt-image-2.5-flare / gpt-image-2.5-sunburst

Aspect ratio and resolution are picked in the UI and converted to the pixel
`size` string the API actually wants (1k/2k/4k are presentation-level concepts
only). The site currently rejects async submissions ("async image generation is
disabled"), so requests go out synchronously; if the server ever answers with a
task id, the polling path below takes over automatically.
"""

from __future__ import annotations

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


# ====================================================================== #
# Constants
# ====================================================================== #

_MODEL_LIST = ["gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]

_RATIOS = [
    "auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
    "16:9", "9:16", "2:1", "1:2", "21:9", "9:21",
]
_RESOLUTIONS = ["1k", "2k", "4k"]

# auto = 不指定；xhigh / max 仅 -sunburst 支持
_QUALITIES = ["auto", "low", "medium", "high", "xhigh", "max"]

# Only the base variant is documented as 1K-only.
_RESOLUTION_LIMITS = {
    "gpt-image-2.5": ["1k"],
    "gpt-image-2.5-flare": ["1k", "2k", "4k"],
    "gpt-image-2.5-sunburst": ["1k", "2k", "4k"],
}

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


# ====================================================================== #
# Helpers
# ====================================================================== #

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


def resolve_size(aspect_ratio: str, resolution: str) -> str:
    """Translate the UI's ratio/resolution into the API's pixel size string."""
    if aspect_ratio == "auto":
        return "auto"
    size = _SIZE_MAP.get((aspect_ratio, resolution))
    if size is None:
        raise XHCYError(f"不支持的画幅组合：{aspect_ratio} × {resolution}")
    return size


# ====================================================================== #
# Node
# ====================================================================== #

class XHCYGPTImage25:
    """XHCY AI · GPT Image 2.5 family text-to-image node."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "图片描述（提示词）。留空会直接报错，不会白白扣费。",
                    },
                ),
                "model": (
                    list(_MODEL_LIST),
                    {
                        "default": _MODEL_LIST[0],
                        "tooltip": "同一家族的三个变体，切换即可换模型。",
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
                    list(_RATIOS),
                    {"default": "1:1", "tooltip": "auto 表示交给服务端决定画幅。"},
                ),
                "resolution": (
                    list(_RESOLUTIONS),
                    {
                        "default": "1k",
                        "tooltip": "gpt-image-2.5 仅支持 1k；-flare / -sunburst 支持到 4k。",
                    },
                ),
                "quality": (
                    list(_QUALITIES),
                    {
                        "default": "auto",
                        "tooltip": "gpt-image-2.5 不支持质量档；-flare 到 high；-sunburst 还支持 xhigh / max。",
                    },
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
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "status", "saved_paths")
    FUNCTION = "generate"
    CATEGORY = "XHCY/Image"
    OUTPUT_NODE = False
    DESCRIPTION = "XHCY AI · GPT Image 2.5 家族文生图（gpt-image-2.5 / -flare / -sunburst）"

    # ------------------------------------------------------------------ #

    def generate(self, prompt, model, api_key, aspect_ratio, resolution, quality,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        if model not in _MODEL_LIST:
            raise XHCYError(f"未知的模型：{model}")

        allowed = _RESOLUTION_LIMITS.get(model, _RESOLUTIONS)
        if aspect_ratio != "auto" and resolution not in allowed:
            raise XHCYError(
                f"{model} 不支持 {resolution} 分辨率；可选：{'、'.join(allowed)}"
            )

        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)
        size = resolve_size(aspect_ratio, resolution)

        client = XHCYClient(api_key, base_url)

        # 站点当前禁用了异步图像生成：发送 async=true 会直接返回 HTTP 400
        # "async image generation is disabled"（已实测确认），因此走同步提交。
        # 若服务端仍然返回 task id，下面的轮询逻辑会自动接管。
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

        check_interrupt()
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

        task_id = extract_task_id(result) or extract_task_id(first) or "-"
        summary = (
            f"XHCY 生成成功\n"
            f"模型：{model}\n"
            f"画幅：{aspect_ratio} @ {resolution}（{size}）\n"
            f"任务：{task_id}\n"
            f"张数：{len(paths)}\n"
            f"文件：\n" + "\n".join(paths)
        )
        return (torch.stack(tensors), summary, "\n".join(paths))

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
            current = XHCYGPTImage25._poll_with_retry(client, task_id)
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
        """A single flaky poll should not kill the whole job."""
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

    @staticmethod
    def _save_image(raw: bytes, index: int) -> tuple[torch.Tensor, str]:
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
        path = os.path.join(directory, f"xhcy_gpt_image_25_{index}_{uuid.uuid4().hex[:8]}.{ext}")
        with open(path, "wb") as handle:
            handle.write(raw)

        tensor = torch.from_numpy(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
        return tensor, path


# ====================================================================== #
# Registration
# ====================================================================== #

NODE_CLASS_MAPPINGS = {
    "xhcy_gpt_image_25": XHCYGPTImage25,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_gpt_image_25": "XHCY GPT Image 2.5（文生图）",
}
