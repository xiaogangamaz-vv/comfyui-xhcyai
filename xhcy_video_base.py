"""Reusable base for XHCY video nodes.

Everything shared by the MiniMax H3 nodes lives here: reference-material
handling, submission, task polling, download and saving. A new video node only
declares which materials it accepts and how to build the `content` array.

Measured against the live service:
    POST /v1/video/generations  -> {"status": "queued", "task_id": "..."}
    GET  /v1/video/generations/{task_id} -> queued -> processing -> succeeded,
                                            result URL arrives as content.url
    The result URL is served from the site's own /v1 path and needs the bearer
    token (401 without it) - XHCYClient.download() handles that.
    Reference material is passed as base64 data URIs inside `content`, e.g.
        {"type": "image_url", "role": "first_frame", "image_url": {"url": "<data URI>"}}
    Roles: first_frame / last_frame / reference_image / reference_video / reference_audio
"""

from __future__ import annotations

import base64
import io
import os
import time
import uuid
import wave

import numpy as np

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


# ---------------------------------------------------------------------- #
# Reference-material limits
#
# Everything travels as a base64 data URI inside the JSON body, so oversized
# material means a giant request that can blow through the gateway timeout.
# ---------------------------------------------------------------------- #

# 2026-10-18：站点提交视频时是「同步等上游建任务」，而它自己的 HTTP 客户端在
# RelayTimeout 未配置时根本没有超时（common/client/init.go），于是 Cloudflare
# 会在 100 秒时返回 524，而站点还在后台继续等。素材越大，上游建任务越慢，
# 越容易撞这道墙 —— 所以把上限和压缩比都收紧，宁可少一点细节，也别让整次
# 生成白等 100 秒。
# 参考素材尽量不降质：只有在超过 2560 长边时才缩放，JPEG 质量 95（肉眼几乎
# 无损）。实测上传不是瓶颈（6 MB 上传 0.84 秒），所以压素材对「提交超时」帮助
# 很小 —— 那 100 秒耗在站点转发上游建任务上，不在上传上。
MAX_MATERIAL_IMAGE_EDGE = 2560
MATERIAL_IMAGE_QUALITY = 95
# 上限按「base64 后不超 Cloudflare 单请求 100 MB」反推：raw×1.34 是实际上传量。
MAX_MATERIAL_BYTES = 48 * 1024 * 1024      # 单个素材，base64 后约 64 MB
MAX_MATERIAL_TOTAL = 60 * 1024 * 1024      # 整个请求，base64 后约 80 MB

# 参考视频的时长限制来自站点上游的硬校验（错误码 2013）：
#   media duration must be between 2 and 15.5 seconds
REF_VIDEO_MIN_SECONDS = 2.0
REF_VIDEO_MAX_SECONDS = 15.5
MAX_VIDEO_BYTES = 512 * 1024 * 1024        # result download cap


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


# ---------------------------------------------------------------------- #
# Material -> data URI
# ---------------------------------------------------------------------- #

_TOTAL_BUDGET = {"used": 0}


def reset_material_budget() -> None:
    _TOTAL_BUDGET["used"] = 0


def _charge_budget(raw: bytes, label: str) -> None:
    _TOTAL_BUDGET["used"] += len(raw)
    if _TOTAL_BUDGET["used"] > MAX_MATERIAL_TOTAL:
        raise XHCYError(
            "参考素材总体积过大（超过 %d MiB），请减少素材数量或先压缩"
            % (MAX_MATERIAL_TOTAL // (1024 * 1024))
        )


def image_tensor_to_uri(tensor) -> str:
    """ComfyUI IMAGE tensor -> JPEG data URI."""
    from PIL import Image

    array = (tensor.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    if array.ndim == 3 and array.shape[2] == 4:
        image = Image.fromarray(array, "RGBA").convert("RGB")
    elif array.ndim == 3 and array.shape[2] == 3:
        image = Image.fromarray(array, "RGB")
    elif array.ndim == 2:
        image = Image.fromarray(array, "L").convert("RGB")
    else:
        raise XHCYError(f"参考图格式无法识别，shape={getattr(array, 'shape', '?')}")
    if max(image.size) > MAX_MATERIAL_IMAGE_EDGE:
        scale = MAX_MATERIAL_IMAGE_EDGE / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=MATERIAL_IMAGE_QUALITY, optimize=True)
    raw = buffer.getvalue()
    _charge_budget(raw, "参考图")
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def video_input_to_uri(video) -> str:
    """ComfyUI VIDEO input -> MP4 data URI."""
    # 站点对参考视频有硬性要求，且只在提交之后才检查，被拒时已经消耗了一次请求。
    # 实测报错原文：media duration must be between 2 and 15.5 seconds /
    # media metadata is invalid。先在这里挡掉，用户立刻看到中文原因。
    duration = None
    if hasattr(video, "get_duration"):
        try:
            value = float(video.get_duration())
            if value > 0:
                duration = value
        except Exception:
            duration = None
    if duration is not None and not (
        REF_VIDEO_MIN_SECONDS <= duration <= REF_VIDEO_MAX_SECONDS
    ):
        raise XHCYError(
            "参考视频时长 %.1f 秒，站点只接受 %.0f～%.1f 秒。\n"
            "请先裁剪再连接（可用 ComfyUI 的视频裁剪/截取节点）。"
            % (duration, REF_VIDEO_MIN_SECONDS, REF_VIDEO_MAX_SECONDS)
        )

    source = None
    if hasattr(video, "get_stream_source"):
        try:
            source = video.get_stream_source()
        except Exception:
            source = None
    if source is None:
        source = video

    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif hasattr(source, "read"):
        try:
            source.seek(0)
        except Exception:
            pass
        raw = source.read()
    elif isinstance(source, str) and os.path.isfile(source):
        with open(source, "rb") as handle:
            raw = handle.read()
    else:
        raise XHCYError("无法读取参考视频的内容（不支持的 VIDEO 来源）")

    # 站点只接受 MP4；WebM/AVI 会被上游以 "media metadata is invalid" 拒掉，
    # 而那一步已经是真实请求了。只在能确定格式时提前拦，避免误杀少见封装。
    if raw[:4] == b"\x1a\x45\xdf\xa3":
        raise XHCYError(
            "参考视频是 WebM 格式，站点只接受 MP4（其他封装会被拒：media metadata is invalid）。\n"
            "请先用 MP4 重编码再连接。"
        )
    if raw[:4] == b"RIFF" and raw[8:12] == b"AVI ":
        raise XHCYError(
            "参考视频是 AVI 格式，站点只接受 MP4（其他封装会被拒：media metadata is invalid）。\n"
            "请先用 MP4 重编码再连接。"
        )

    if len(raw) > MAX_MATERIAL_BYTES:
        raise XHCYError(
            "参考视频超过 %d MiB，请先压缩或剪短后再连接"
            % (MAX_MATERIAL_BYTES // (1024 * 1024))
        )
    _charge_budget(raw, "参考视频")
    return "data:video/mp4;base64," + base64.b64encode(raw).decode("ascii")


def audio_input_to_uri(audio) -> str:
    """ComfyUI AUDIO input ({"waveform", "sample_rate"}) -> WAV data URI."""
    if not isinstance(audio, dict):
        raise XHCYError("参考音频格式无法识别")
    waveform = audio.get("waveform")
    rate = int(audio.get("sample_rate") or 44100)
    if waveform is None:
        raise XHCYError("参考音频缺少 waveform 数据")

    data = waveform.detach().cpu().numpy() if hasattr(waveform, "detach") else np.asarray(waveform)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if data.ndim != 2:
        raise XHCYError(f"参考音频维度异常：{data.shape}")

    # 统一成 int16 PCM，声道数不超过 2
    channels = min(data.shape[0], 2)
    samples = np.clip(data[:channels], -1.0, 1.0)
    pcm = (samples * 32767.0).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    raw = buffer.getvalue()
    if len(raw) > MAX_MATERIAL_BYTES:
        raise XHCYError(
            "参考音频超过 %d MiB（约 6 分钟 44.1kHz 立体声），请剪短后再连接"
            % (MAX_MATERIAL_BYTES // (1024 * 1024))
        )
    _charge_budget(raw, "参考音频")
    return "data:audio/wav;base64," + base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------- #
# Base node
# ---------------------------------------------------------------------- #

class XHCYVideoBase:
    """Shared behaviour for every XHCY video node."""

    VARIANT_MODELS: list[str] = []
    RESOLUTION_LIMITS: dict[str, list[str]] = {}
    RATIO_LIMITS: dict[str, list[str]] = {}
    DURATION_LIMITS: dict[str, tuple[int, int]] = {}
    DEFAULT_MODEL = ""
    DEFAULT_RESOLUTION = "768P"
    DEFAULT_DURATION = 5
    DEFAULT_RATIO = "16:9"
    RESOLUTIONS: list[str] = ["480P", "768P", "1080P", "2K"]
    RATIOS: list[str] = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
    PROMPT_TOOLTIP = "视频描述（提示词）。留空会直接报错，不会白白扣费。"
    NODE_ID = "xhcy_video_base"
    OUTPUT_PREFIX = "xhcy_video"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = ""

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "status", "video_path")
    FUNCTION = "generate"
    OUTPUT_NODE = False

    # ------------------------------------------------------------------ #

    @classmethod
    def all_resolutions(cls) -> list[str]:
        """下拉候选 = 各模型支持项取并集（改 RESOLUTION_LIMITS 即自动同步）。"""
        seen: list[str] = []
        for values in cls.RESOLUTION_LIMITS.values():
            for value in values:
                if value not in seen:
                    seen.append(value)
        return seen or list(cls.RESOLUTIONS)

    @classmethod
    def all_ratios(cls) -> list[str]:
        """下拉候选 = 各模型支持比例取并集。"""
        seen: list[str] = []
        for values in cls.RATIO_LIMITS.values():
            for value in values:
                if value not in seen:
                    seen.append(value)
        return seen or list(cls.RATIOS)

    @classmethod
    def material_inputs(cls) -> dict:
        """素材输入，由子类声明；默认没有。"""
        return {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": cls.PROMPT_TOOLTIP},
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
                "resolution": (
                    cls.all_resolutions(),
                    {"default": cls.DEFAULT_RESOLUTION, "tooltip": "输出分辨率，按所选模型自动校验。"},
                ),
                "duration": (
                    "INT",
                    {
                        "default": cls.DEFAULT_DURATION,
                        "min": 1,
                        "max": 60,
                        "tooltip": "时长（秒），按秒计费。超出所选模型范围时会自动收进合法区间并提示。",
                    },
                ),
                "ratio": (
                    cls.all_ratios(),
                    {"default": cls.DEFAULT_RATIO, "tooltip": "画面比例，adaptive 由服务端决定。"},
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
            },
            "optional": cls.material_inputs(),
        }

    # ------------------------------------------------------------------ #

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> list:
        """由子类实现：组装 content 数组。"""
        return [{"type": "text", "text": prompt}]

    def generate(self, prompt, model, api_key, resolution, duration, ratio,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL, **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")

        if self.VARIANT_MODELS and model not in self.VARIANT_MODELS:
            raise XHCYError(f"未知的模型：{model}")

        allowed_res = self.RESOLUTION_LIMITS.get(model, self.RESOLUTIONS)
        if resolution not in allowed_res:
            raise XHCYError(f"{model} 不支持 {resolution}；可选：{'、'.join(allowed_res)}")
        allowed_ratio = self.RATIO_LIMITS.get(model, self.RATIOS)
        if ratio not in allowed_ratio:
            raise XHCYError(f"{model} 不支持 {ratio} 比例；可选：{'、'.join(allowed_ratio)}")

        low, high = self.DURATION_LIMITS.get(model, (1, 15))
        # 控件允许填 1~15 秒，但各模型下限不同（H3 最少 4 秒、Max 最少 5 秒、
        # Lite 最少 1 秒）。填到范围外时自动收进合法区间并提示，而不是直接报错，
        # 省掉用户一次白跑。
        requested = _int_param(duration, "时长（秒）", 1, 60)
        seconds = min(max(requested, low), high)
        duration_note = ""
        if seconds != requested:
            duration_note = (
                f"\n时长已自动调整：{requested} 秒 → {seconds} 秒（{model} 支持 {low}～{high} 秒）"
            )
        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)

        check_interrupt()
        reset_material_budget()
        content = self.build_content(prompt, kwargs)

        client = XHCYClient(api_key, base_url)
        payload = {
            "model": model,
            "resolution": resolution,
            "duration": seconds,
            "ratio": ratio,
            "content": content,
            # 让站点把「提交上游」放到后台，请求立刻返回任务号。
            # 带参考素材的请求要等站点把几十 MB 转发给上游建任务，实测会超过
            # Cloudflare 固定的 100 秒上限（返回 524，任务却可能已经建好）。
            # 站点没有这个字段的旧版本会忽略它，行为不变。
            "async": True,
        }

        check_interrupt()
        started_at = time.time()
        try:
            first = client.submit_video(payload)
        except XHCYError as exc:
            first = self._recover_after_gateway_timeout(client, model, started_at, exc)
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

        raw = client.download(video_url, max_bytes=MAX_VIDEO_BYTES)
        path = self._save_video(raw, task_id)

        summary = (
            f"XHCY 视频生成成功\n"
            f"节点：{self.NODE_ID}\n"
            f"模型：{model}\n"
            f"规格：{resolution} · {seconds} 秒 · {ratio}{duration_note}\n"
            f"任务：{task_id}\n"
            f"文件：{path}"
        )
        return (self._video_object(path), summary, path)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _video_object(path: str):
        if _VideoFromFile is None:
            return None
        try:
            return _VideoFromFile(path)
        except Exception:
            return None

    # 站点提交视频时是同步等上游建任务，而它自己的 HTTP 客户端在 RelayTimeout
    # 未配置时没有超时（common/client/init.go）；Cloudflare 只等 100 秒就返回
    # 524，可站点往往还在后台继续建任务。与其让整次生成白跑，不如回任务列表
    # 把它捞回来 —— 列表按密钥隔离，加上时间窗口和模型名双重匹配。
    _TIMEOUT_HINTS = ("http 524", "超时", "timeout", "timed out")

    @classmethod
    def _recover_after_gateway_timeout(cls, client: XHCYClient, model: str,
                                       started_at: float, exc: Exception) -> dict:
        message = str(exc).lower()
        if not any(hint in message for hint in cls._TIMEOUT_HINTS):
            raise exc

        print("[XHCY] 提交遇到网关超时，正在任务列表里查找可能已创建的任务…")
        for _ in range(4):
            sleep_interruptible(8)
            check_interrupt()
            try:
                listing = client.list_video_tasks(page=1, size=10)
            except XHCYError:
                continue
            items = listing.get("items")
            if not isinstance(items, list):
                data = listing.get("data")
                items = data if isinstance(data, list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("model") or "") != model:
                    continue
                created = item.get("created_at")
                if not isinstance(created, (int, float)) or created < started_at - 15:
                    continue
                task_id = item.get("task_id") or item.get("id")
                if task_id:
                    print("[XHCY] 已找回任务 %s（状态 %s）" % (task_id, item.get("status")))
                    return {"task_id": str(task_id), "status": item.get("status") or "queued"}

        raise XHCYError(
            "提交时网关超时（HTTP 524，Cloudflare 等待上限约 100 秒），"
            "任务列表里也没找到这次提交的任务。\n"
            "这通常是参考素材太大或太多，站点转发给上游建任务超过了 100 秒。\n"
            "建议：\n"
            "  1) 减少参考素材，尤其是参考视频，或把参考视频剪短；\n"
            "  2) 分辨率先降到 768P 再试一次；\n"
            "  3) 过几分钟到站点的任务列表看看，任务可能已经在后台生成好了。"
        ) from exc

    @staticmethod
    def _wait_for_video(client: XHCYClient, task_id: str, attempts: int, interval: int) -> dict:
        last_status = "处理中"
        for _ in range(attempts):
            sleep_interruptible(interval)
            check_interrupt()
            current = XHCYVideoBase._poll_with_retry(client, task_id)
            status = extract_status(current)
            if status:
                last_status = status
            if status in STATUS_SUCCESS:
                return current
            if status in STATUS_FAILURE:
                raise XHCYError(f"生成失败：{extract_failure_reason(current) or '服务端未给出原因'}")
            if not status and extract_video_url(current):
                return current
        if last_status == "submitted":
            # 站点已经收下请求，但上游还没建出任务。这是上游排队或临时故障
            # （实测上游 metaso 会直接回 502 Bad Gateway），不是请求本身有问题。
            # 说清楚比只报「等待超时」有用：用户知道该等、该重试，而不是改素材。
            raise XHCYError(
                "等待超时（已查询 %d 次）。任务一直停在「已提交」：站点已经收到请求，"
                "但上游还没有接受建任务。\n"
                "这通常是上游在排队或临时故障（上游会回 502 Bad Gateway），"
                "和你的提示词、参考素材无关。\n"
                "建议：等 1～2 分钟直接重跑；连续几次都这样，就是上游在故障，等它恢复。"
                % attempts
            )
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

    @classmethod
    def _save_video(cls, raw: bytes, task_id: str) -> str:
        if not raw:
            raise XHCYError("服务端返回了空的视频内容")
        directory = _output_dir()
        os.makedirs(directory, exist_ok=True)
        safe_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "_-") or uuid.uuid4().hex[:8]
        path = os.path.join(directory, f"{cls.OUTPUT_PREFIX}_{safe_id}.mp4")
        with open(path, "wb") as handle:
            handle.write(raw)
        return path
