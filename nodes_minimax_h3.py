"""XHCY AI video node — MiniMax H3 family (text-to-video).

One node covers the whole family; the `model` dropdown switches between
MiniMax-H3 / MiniMax-H3-Max / MiniMax-H3-Lite.

Flow (verified against the live service):
    POST /v1/video/generations        -> {"status": "queued", "task_id": "..."}
    GET  /v1/video/generations/{id}   -> queued -> processing -> succeeded,
                                         then {"content": {"url": "..."}}
The content URL is served from the site's own /v1 path and needs the bearer
token, so the download goes through XHCYClient.download() which attaches the
Authorization header only for our own host.
"""

from __future__ import annotations

import os
import time
import uuid

try:  # provided by ComfyUI
    import folder_paths  # type: ignore
except ImportError:
    folder_paths = None  # type: ignore

try:  # ComfyUI >= 0.3 exposes the official VIDEO type
    from comfy_api.latest import InputImpl as _InputImpl  # type: ignore

    _VideoFromFile = getattr(_InputImpl, "VideoFromFile", None)
except Exception:  # pragma: no cover
    _VideoFromFile = None

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        STATUS_SUCCESS,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_status,
        extract_task_id,
        extract_video_url,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        STATUS_SUCCESS,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_status,
        extract_task_id,
        extract_video_url,
    )


# ====================================================================== #
# Constants
# ====================================================================== #

# Per-model limits, taken from the site's own /v1 documentation.
_MODEL_SPECS = {
    "MiniMax-H3": {
        "resolutions": ["768P", "2K"],
        "duration": (4, 15),
        "ratios": ["16:9", "9:16", "1:1", "adaptive", "21:9", "4:3", "3:4"],
    },
    "MiniMax-H3-Max": {
        "resolutions": ["768P", "480P"],
        "duration": (5, 15),
        "ratios": ["16:9", "9:16", "1:1", "adaptive", "21:9", "4:3", "3:4"],
    },
    "MiniMax-H3-Lite": {
        "resolutions": ["768P", "480P"],
        "duration": (1, 15),
        "ratios": ["16:9", "9:16", "1:1", "adaptive"],
    },
}

_MODEL_LIST = list(_MODEL_SPECS)
_RESOLUTIONS = ["768P", "2K", "480P"]  # union; validated per model
_RATIOS = ["16:9", "9:16", "1:1", "adaptive", "21:9", "4:3", "3:4"]

_MAX_VIDEO_BYTES = 512 * 1024 * 1024


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


# ====================================================================== #
# Node
# ====================================================================== #

class XHCYMiniMaxH3:
    """XHCY AI · MiniMax H3 family text-to-video node."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "视频描述（提示词）。留空会直接报错，不会白白扣费。",
                    },
                ),
                "model": (
                    list(_MODEL_LIST),
                    {
                        "default": "MiniMax-H3",
                        "tooltip": "H3 支持 2K；H3-Max 更快；H3-Lite 最短可到 1 秒。",
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
                "resolution": (
                    list(_RESOLUTIONS),
                    {"default": "768P", "tooltip": "H3 支持 768P / 2K；Max 与 Lite 支持 768P / 480P。"},
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 15,
                        "tooltip": "时长（秒）。按秒计费，H3 最少 4 秒，Max 最少 5 秒。",
                    },
                ),
                "ratio": (
                    list(_RATIOS),
                    {"default": "16:9", "tooltip": "画面比例，adaptive 由服务端决定。"},
                ),
                "max_poll_attempts": (
                    "INT",
                    {"default": 120, "min": 1, "max": 600, "tooltip": "最多查询多少次结果。"},
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

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "status", "video_path")
    FUNCTION = "generate"
    CATEGORY = "XHCY/Video"
    OUTPUT_NODE = False
    DESCRIPTION = "XHCY AI · MiniMax H3 家族文生视频（MiniMax-H3 / -Max / -Lite）"

    # ------------------------------------------------------------------ #

    def generate(self, prompt, model, api_key, resolution, duration, ratio,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")

        spec = _MODEL_SPECS.get(model)
        if spec is None:
            raise XHCYError(f"未知的模型：{model}")

        if resolution not in spec["resolutions"]:
            raise XHCYError(
                f"{model} 不支持 {resolution}；可选：{'、'.join(spec['resolutions'])}"
            )
        if ratio not in spec["ratios"]:
            raise XHCYError(f"{model} 不支持 {ratio} 比例；可选：{'、'.join(spec['ratios'])}")

        low, high = spec["duration"]
        seconds = _int_param(duration, "时长（秒）", low, high)
        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)

        client = XHCYClient(api_key, base_url)

        payload = {
            "model": model,
            "resolution": resolution,
            "duration": seconds,
            "ratio": ratio,
            "content": [{"type": "text", "text": prompt}],
        }

        check_interrupt()
        first = client.submit_video(payload)

        status = extract_status(first)
        if status in STATUS_FAILURE:
            raise XHCYError(f"提交失败：{extract_failure_reason(first) or '服务端未给出原因'}")

        task_id = extract_task_id(first)
        if not task_id:
            raise XHCYError("服务端没有返回任务 ID，无法查询视频结果")

        result = self._wait_for_video(client, task_id, attempts, interval)
        video_url = extract_video_url(result)
        if not video_url:
            raise XHCYError("任务已完成，但返回里没有找到视频地址")

        raw = client.download(video_url, max_bytes=_MAX_VIDEO_BYTES)
        path = self._save_video(raw, task_id)

        summary = (
            f"XHCY 视频生成成功\n"
            f"模型：{model}\n"
            f"规格：{resolution} · {seconds} 秒 · {ratio}\n"
            f"任务：{task_id}\n"
            f"文件：{path}"
        )
        return (self._video_object(path), summary, path)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _video_object(path: str):
        """Wrap the saved file in ComfyUI's official VIDEO type so it can feed
        SaveVideo / PreviewVideo. Falls back to None on very old ComfyUI."""
        if _VideoFromFile is None:
            return None
        try:
            return _VideoFromFile(path)
        except Exception:
            return None

    @staticmethod
    def _wait_for_video(client: XHCYClient, task_id: str, attempts: int, interval: int) -> dict:
        last_status = "处理中"
        for _ in range(attempts):
            sleep_interruptible(interval)
            check_interrupt()
            current = XHCYMiniMaxH3._poll_with_retry(client, task_id)
            status = extract_status(current)
            if status:
                last_status = status
            if status in STATUS_SUCCESS:
                return current
            if status in STATUS_FAILURE:
                raise XHCYError(f"生成失败：{extract_failure_reason(current) or '服务端未给出原因'}")
            if not status and extract_video_url(current):
                return current
        raise XHCYError(f"等待超时，已查询 {attempts} 次，最后状态：{last_status}")

    @staticmethod
    def _poll_with_retry(client: XHCYClient, task_id: str, retries: int = 2) -> dict:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return client.poll_video(task_id)
            except XHCYError as exc:
                message = str(exc)
                if "HTTP 401" in message or "HTTP 403" in message or "HTTP 404" in message:
                    raise
                last_error = exc
                if attempt < retries:
                    sleep_interruptible(2)
        raise last_error if last_error else XHCYError("视频结果查询失败")

    @staticmethod
    def _save_video(raw: bytes, task_id: str) -> str:
        if not raw:
            raise XHCYError("服务端返回了空的视频内容")
        directory = _output_dir()
        os.makedirs(directory, exist_ok=True)
        safe_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "_-") or uuid.uuid4().hex[:8]
        path = os.path.join(directory, f"xhcy_minimax_h3_{safe_id}.mp4")
        with open(path, "wb") as handle:
            handle.write(raw)
        return path


# ====================================================================== #
# Registration
# ====================================================================== #

NODE_CLASS_MAPPINGS = {
    "xhcy_minimax_h3": XHCYMiniMaxH3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_minimax_h3": "XHCY MiniMax H3（文生视频）",
}
