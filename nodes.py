"""XINGHUO Nano Banana secure image node."""

import base64
import binascii
import io
import json
import os
import sys
import uuid
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests
import torch
import folder_paths
import comfy.model_management
from PIL import Image
try:
    from .secure_config import (ConfigError, load_config, load_locked_billing,
                                load_locked_service_origin, load_locked_service_profile)
    from .providers.secure_draw_client import SecureDrawClient
except ImportError:  # Allows direct test execution outside package loading.
    from secure_config import (ConfigError, load_config, load_locked_billing,
                               load_locked_service_origin, load_locked_service_profile)
    from providers.secure_draw_client import SecureDrawClient


_BASE_RATIOS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]
_EXTENDED_RATIOS = ["1:4", "4:1", "1:8", "8:1"]
_TERMINAL_SUCCESS = {"succeeded", "success"}
_TERMINAL_FAILURE = {"failed", "failure", "error", "violation", "cancelled"}
_MAX_IMAGES = 16
_MAX_EDGE = 2048
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_BYTES = 50 * 1024 * 1024
_MODEL_LIST = ["nano-banana-fast", "nano-banana-2", "nano-banana-pro"]
_IMAGE_SIZE_LIST = ["1K", "2K", "4K"]
_REPLY_TYPE_LIST = ["json", "async", "stream"]
_LOCKED_BILLING_DIGEST = "d698c42d480eea080d14577f792bcc21d7d81cce0f45c4b2a4d1f6f23007bde8"
_UPSTREAM_STATUS_TEXT = {
    "input_moderation": "输入违规：提示词或参考图触发内容审核",
    "output_moderation": "输出违规：生成结果触发内容审核",
    "violation": "内容审核未通过",
    "failed": "服务端生成失败",
    "failure": "服务端生成失败",
    "error": "服务端处理错误",
    "cancelled": "服务端任务已取消",
}
_LEGACY_NODE_ID = base64.b64decode("Y29tZnl1aV94aW5naHVvX2dwdF9pbWFnZV8y").decode("ascii")


def _provider_config() -> dict[str, Any]:
    try:
        config = load_config()
    except ConfigError:
        # Direct key input remains usable without a local encrypted profile.
        config = {"base_url": load_locked_service_origin(), "api_key": "", "profiles": {}}
    if not config["base_url"].startswith("https://"):
        raise ValueError("加密配置中的服务端 URL 必须为 HTTPS")
    return config


@lru_cache(maxsize=1)
def _service_routes() -> dict[str, str]:
    return load_locked_service_profile()["routes"]


@lru_cache(maxsize=1)
def _locked_billing() -> dict[str, dict[str, int | float]]:
    """Load the fixed portable protected display mapping without source literals."""
    try:
        billing = load_locked_billing(_LOCKED_BILLING_DIGEST)
    except ConfigError as exc:
        raise RuntimeError("节点计费数据不可用") from exc
    if set(billing) != set(_MODEL_LIST):
        raise RuntimeError("节点计费数据模型范围无效")

    normalized: dict[str, dict[str, int | float]] = {}
    for model in _MODEL_LIST:
        item = billing.get(model)
        if not isinstance(item, dict):
            raise RuntimeError("节点计费数据格式无效")
        credits, display_amount = item.get("credits"), item.get("display_amount")
        if isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0:
            raise RuntimeError("节点计费数据积分无效")
        if isinstance(display_amount, bool) or not isinstance(display_amount, (int, float)) or display_amount <= 0:
            raise RuntimeError("节点计费数据金额无效")
        normalized[model] = {"credits": credits, "display_amount": float(display_amount)}
    return normalized


def query_account_balance(api_key: str = "", model: str = "nano-banana-2") -> dict[str, Any]:
    """Query credits and apply the user-confirmed local display mapping."""
    try:
        billing_table = _locked_billing()
        config = _provider_config()
        api_key = api_key.strip() or config.get("api_key", "").strip()
        if not api_key:
            return {"success": False, "error": "请填写访问密钥", "balance": 0}
        billing = billing_table.get(model, billing_table["nano-banana-2"])
        credit_cost = billing["credits"]
        routes = _service_routes()
        response = requests.post(
            config["base_url"].rstrip("/") + routes["balance"],
            json={"apiKey": api_key},
            timeout=(10, 30),
        )
        if response.status_code == 401:
            return {"success": False, "error": "访问密钥错误或已失效", "balance": 0}
        if response.status_code != 200:
            return {"success": False, "error": f"账户查询失败（HTTP {response.status_code}）", "balance": 0}
        data = response.json()
        if not isinstance(data, dict) or data.get("code") != 0:
            return {"success": False, "error": "账户查询失败（服务端拒绝请求）", "balance": 0}
        credits = data.get("data", {}).get("credits")
        if not isinstance(credits, (int, float)):
            return {"success": False, "error": "账户响应中未包含有效余额", "balance": 0}
        complete_calls = int(credits // credit_cost)
        balance = round(complete_calls * billing["display_amount"], 2)
        # Keep credits server-side. The browser receives only the approved local display mapping.
        preview_costs = [billing_table[name]["display_amount"] for name in _MODEL_LIST]
        return {"success": True, "credits": credits, "balance": balance,
                "preview_costs": preview_costs}
    except requests.Timeout:
        return {"success": False, "error": "账户查询超时，请稍后重试", "balance": 0}
    except requests.RequestException:
        return {"success": False, "error": "账户查询网络失败，请检查网络后重试", "balance": 0}
    except (ValueError, RuntimeError, json.JSONDecodeError):
        return {"success": False, "error": "账户查询失败，请检查本机配置后重试", "balance": 0}


def public_balance_preview(api_key: str = "", model: str = "nano-banana-2") -> dict[str, Any]:
    """Return the minimal, non-sensitive balance view used by the browser widget."""
    result = query_account_balance(api_key, model)
    if not result.get("success"):
        # Do not expose remote response text, account credits, URLs, or exception details to the browser.
        return {"success": False, "error": "账户查询失败，请检查访问密钥或网络后重试"}
    return {
        "success": True,
        "balance": result["balance"],
        "preview_costs": list(result["preview_costs"]),
    }


try:
    if "server" in sys.modules:
        from server import PromptServer
        from aiohttp import web

        @PromptServer.instance.routes.post("/xinghuo_nano_banana/balance")
        async def _account_balance_route(request):
            try:
                body = await request.json()
            except Exception:
                body = {}
            return web.json_response(public_balance_preview(str(body.get("api_key", "")), str(body.get("model", "nano-banana-2"))))
except Exception:
    # The node remains importable in standalone test environments.
    pass


def _api_error(response: requests.Response, context: str) -> RuntimeError:
    if response.status_code == 401:
        return RuntimeError("访问密钥错误或已失效（HTTP 401），未继续轮询。")
    if response.status_code == 403:
        return RuntimeError("没有调用权限或账户不可用（HTTP 403），未继续轮询。")
    if response.status_code == 429:
        return RuntimeError(f"{context}请求过于频繁（HTTP 429），请稍后重试")
    if response.status_code >= 500:
        return RuntimeError(f"{context}服务端暂时不可用（HTTP {response.status_code}），请稍后重试")
    if response.status_code == 400:
        return RuntimeError(f"{context}参数未被服务端接受（HTTP 400）")
    if response.status_code == 404:
        return RuntimeError(f"{context}资源不存在（HTTP 404）")
    return RuntimeError(f"{context}失败（HTTP {response.status_code}）")


def _error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("error") or "")
    if error:
        return str(error)
    data = payload.get("data")
    if isinstance(data, dict):
        nested = _error_message(data)
        if nested:
            return nested
    return str(payload.get("message") or payload.get("failure_reason") or payload.get("fail_reason") or payload.get("detail") or "")


def _contains_timeout_marker(*values: Any) -> bool:
    """Recognize timeout semantics without returning raw upstream text."""
    for value in values:
        text = str(value or "").casefold()
        compact = "".join(character for character in text if character.isalnum())
        if "timeout" in compact or "timedout" in compact or "超时" in text:
            return True
    return False


def _upstream_failure_reason(payload: dict[str, Any]) -> str:
    failure_reason = str(payload.get("failure_reason") or payload.get("fail_reason") or "").lower()
    status = _status(payload)
    message = _error_message(payload)
    if _contains_timeout_marker(failure_reason, status, message):
        return "处理超时"
    label = _UPSTREAM_STATUS_TEXT.get(failure_reason) or _UPSTREAM_STATUS_TEXT.get(status)
    if label:
        return label
    if failure_reason or status in _TERMINAL_FAILURE or message:
        return "服务端返回失败状态"
    return ""


def _public_network_failure(context: str, exc: requests.RequestException) -> str:
    """Classify transport failures without exposing provider hosts or library details."""
    timed_out = isinstance(exc, requests.Timeout)
    if context == "生成请求":
        if timed_out:
            return "生成请求响应超时；任务是否已提交无法确认，请勿立即重复提交"
        return "生成请求网络连接失败；请检查网络后重试"
    if context == "异步结果查询":
        return "异步结果查询超时，请稍后重试" if timed_out else "异步结果查询网络失败，请稍后重试"
    if context == "图片下载":
        return "生成结果图片下载超时，请稍后重试" if timed_out else "生成结果图片下载网络失败，请稍后重试"
    return "服务网络请求失败，请稍后重试"


def _unwrap_draw_response(payload: dict[str, Any], context: str) -> dict[str, Any]:
    """Normalize the documented /v1/draw response envelope without losing errors."""
    code = payload.get("code")
    if code not in (None, 0):
        detail = _upstream_failure_reason(payload) or "服务端返回失败状态"
        raise RuntimeError(f"{context}失败（服务端 code {code}）：{detail}")
    data = payload.get("data")
    if isinstance(data, dict):
        merged = dict(data)
        if "msg" in payload and "message" not in merged:
            merged["message"] = payload["msg"]
        return merged
    return payload


def _task_id(payload: dict[str, Any]) -> str:
    """Read the documented id plus common proxy wrappers without guessing URLs."""
    value = payload.get("id") or payload.get("task_id")
    if value:
        return str(value)
    data = payload.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        value = data.get("id") or data.get("task_id")
        if value:
            return str(value)
    return ""


def _status(payload: dict[str, Any]) -> str:
    value = payload.get("status")
    if value is None and isinstance(payload.get("data"), dict):
        value = payload["data"].get("status")
    return str(value or "").lower()


def _check_comfyui_interrupt() -> None:
    """Raise ComfyUI's native interruption exception at safe request boundaries."""
    comfy.model_management.throw_exception_if_processing_interrupted()


def _interruptible_sleep(seconds: int) -> None:
    import time
    remaining = float(seconds)
    while remaining > 0:
        _check_comfyui_interrupt()
        step = min(0.25, remaining)
        time.sleep(step)
        remaining -= step


def _normalize_generation_parameters(
    aspect_ratio: Any,
    image_size: Any,
    reply_type: Any = "async",
) -> tuple[str, str, str]:
    """Repair one known legacy widget shift, then enforce the request contract."""
    ratio = str(aspect_ratio or "").strip()
    size = str(image_size or "").strip().upper()
    reply = str(reply_type or "").strip().lower()

    allowed_ratios = set(_BASE_RATIOS + _EXTENDED_RATIOS)
    allowed_sizes = set(_IMAGE_SIZE_LIST)
    allowed_replies = set(_REPLY_TYPE_LIST)

    # Legacy workflows stored widget values positionally. The known shifted
    # pattern is image_size=<ratio> and reply_type=<resolution>.
    if size in allowed_ratios and str(reply_type or "").strip().upper() in allowed_sizes:
        ratio = size
        size = str(reply_type).strip().upper()
        reply = "async"

    if ratio not in allowed_ratios:
        raise ValueError(f"画面比例参数无效：{ratio or '<空>'}")
    if size not in allowed_sizes:
        raise ValueError(f"图像尺寸参数无效：{size or '<空>'}；只允许 1K、2K、4K")
    if reply not in allowed_replies:
        raise ValueError("历史兼容参数无效；请重新添加新版节点")

    return ratio, size, reply


def _normalize_polling_parameters(max_poll_attempts: Any, poll_interval: Any) -> tuple[int, int]:
    """Validate polling values before any account or generation request."""
    if isinstance(max_poll_attempts, bool) or isinstance(poll_interval, bool):
        raise ValueError("轮询参数必须为整数")
    try:
        attempts = int(max_poll_attempts)
        interval = int(poll_interval)
    except (TypeError, ValueError) as exc:
        raise ValueError("轮询参数必须为整数") from exc
    if attempts != max_poll_attempts or interval != poll_interval:
        # Accept numeric strings while rejecting non-integral floats.
        if str(max_poll_attempts).strip() != str(attempts) or str(poll_interval).strip() != str(interval):
            raise ValueError("轮询参数必须为整数")
    if not 1 <= attempts <= 1000:
        raise ValueError("最大轮询次数必须在 1 到 1000 之间")
    if not 1 <= interval <= 60:
        raise ValueError("轮询间隔必须在 1 到 60 秒之间")
    return attempts, interval


class _ComfyExecutionResult(dict):
    """ComfyUI result mapping with tuple-style indexing for existing tests/tools."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return dict.__getitem__(self, "result")[key]
        return dict.__getitem__(self, key)


def _comfy_result(
    image: torch.Tensor,
    response_text: str,
    local_image_paths: str,
    status: str,
) -> dict[str, Any]:
    """Return normal outputs plus a minimal browser-only execution status."""
    return _ComfyExecutionResult(
        ui={"xinghuo_generation_status": [status]},
        result=(image, response_text, local_image_paths),
    )


class ComfyuiXinghuoNanoBanana:
    """Generate images with the documented Nano Banana API only."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {f"image{i}": ("IMAGE", {"tooltip": f"Reference image #{i}"}) for i in range(1, 17)}
        try:
            _provider_config()
        except ValueError:
            pass
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (_MODEL_LIST, {"default": "nano-banana-2"}),
                "api_key": ("STRING", {"default": "", "multiline": False, "defaultInput": True, "tooltip": "可直接填写，或连接 TEXT/STRING 节点"}),
                "aspect_ratio": (_BASE_RATIOS + _EXTENDED_RATIOS, {"default": "1:1"}),
                "image_size": (_IMAGE_SIZE_LIST, {"default": "1K"}),
                # Retained solely to keep existing workflows' widget positions stable.
                # The documented draw endpoint always uses webHook='-1' polling below.
                "reply_type": (_REPLY_TYPE_LIST, {"default": "async", "tooltip": "历史兼容参数；固定使用异步查询"}),
                "max_poll_attempts": ("INT", {"default": 300, "min": 1, "max": 1000}),
                "poll_interval": ("INT", {"default": 5, "min": 1, "max": 60}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "response_text", "local_image_paths")
    FUNCTION = "generate"
    OUTPUT_NODE = False
    CATEGORY = "星火/Secure Image"

    @staticmethod
    def _tensor_to_png_data_uri(tensor: torch.Tensor) -> str:
        array = (tensor.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            raise ValueError(f"参考图必须是 HWC 的 RGB/RGBA 图像，实际 shape={array.shape}")
        pil = Image.fromarray(array, "RGBA" if array.shape[2] == 4 else "RGB")
        if max(pil.size) > _MAX_EDGE:
            scale = _MAX_EDGE / max(pil.size)
            pil = pil.resize((round(pil.width * scale), round(pil.height * scale)), Image.Resampling.LANCZOS)
        if pil.mode == "RGBA":
            # The documented image field is a reference image, not a mask; retain pixels without adding a mask contract.
            pil = pil.convert("RGB")
        output = io.BytesIO()
        pil.save(output, format="PNG", optimize=True)
        raw = output.getvalue()
        if len(raw) > _MAX_IMAGE_BYTES:
            raise ValueError(f"参考图 PNG 编码后为 {len(raw) / 1024 / 1024:.1f} MiB，超过单图 10 MiB 限制")
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _collect_images(kwargs: dict[str, Any]) -> list[str]:
        encoded: list[str] = []
        total_bytes = 0
        for index in range(1, 17):
            batch = kwargs.get(f"image{index}")
            if batch is None:
                continue
            if not isinstance(batch, torch.Tensor) or batch.ndim != 4:
                raise ValueError(f"image{index} 必须是 ComfyUI IMAGE batch")
            for item in batch:
                if len(encoded) >= _MAX_IMAGES:
                    raise ValueError("参考图总数超过 Nano Banana 节点限制：最多 16 张")
                image_data_uri = ComfyuiXinghuoNanoBanana._tensor_to_png_data_uri(item)
                encoded_payload = image_data_uri.split(",", 1)[1]
                raw_size = len(base64.b64decode(encoded_payload, validate=True))
                total_bytes += raw_size
                if total_bytes > _MAX_TOTAL_BYTES:
                    raise ValueError("参考图 PNG 编码总量超过 50 MiB 限制")
                encoded.append(image_data_uri)
        return encoded

    @staticmethod
    def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
        """Legacy helper retained for direct callers; transport now lives in SecureDrawClient."""
        return SecureDrawClient.request(method, url, **kwargs)

    @staticmethod
    def _parse_json(response: requests.Response, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise _api_error(response, context)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{context}返回了非 JSON 内容") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{context}返回格式错误：期望 JSON 对象")
        return payload

    def _poll(self, task_id: str, headers: dict[str, str], client: SecureDrawClient, max_attempts: int, interval: int) -> dict[str, Any]:
        last_status = "unknown"
        for attempt in range(max_attempts):
            try:
                _check_comfyui_interrupt()
                response = client.poll_once(headers, task_id)
                if response.status_code in (401, 403, 400, 404):
                    raise _api_error(response, "异步结果查询")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == max_attempts - 1:
                        raise _api_error(response, "异步结果查询")
                else:
                    payload = _unwrap_draw_response(self._parse_json(response, "异步结果查询"), "异步结果查询")
                    last_status = _status(payload) or last_status
                    if last_status in _TERMINAL_SUCCESS:
                        return payload
                    if last_status in _TERMINAL_FAILURE:
                        raise RuntimeError(f"任务 {task_id} {_upstream_failure_reason(payload) or '服务端未提供失败原因'}")
            except requests.RequestException as exc:
                if attempt == max_attempts - 1:
                    raise RuntimeError(_public_network_failure("异步结果查询", exc)) from None
            _interruptible_sleep(interval)
        raise RuntimeError(f"任务 {task_id} 轮询超时，最后状态：{last_status}")

    @staticmethod
    def _result_items(payload: dict[str, Any]) -> list[dict[str, str]]:
        results = payload.get("results")
        if not isinstance(results, list) and isinstance(payload.get("data"), dict):
            results = payload["data"].get("results")
        if not isinstance(results, list):
            raise RuntimeError("服务端响应中未找到 results 数组")
        items = []
        for result in results:
            if not isinstance(result, dict):
                continue
            value = result.get("url") or result.get("b64_json") or result.get("b64")
            if value:
                items.append({"value": str(value)})
        if not items:
            raise RuntimeError("results 中未找到图片 URL 或 Base64 数据")
        return items

    @staticmethod
    def _image_bytes(value: str, client: SecureDrawClient | None = None) -> bytes:
        _check_comfyui_interrupt()
        if value.startswith("data:"):
            try:
                value = value.split(",", 1)[1]
            except IndexError as exc:
                raise RuntimeError("Data URI 缺少 Base64 数据") from exc
        if value.startswith("http://") or value.startswith("https://"):
            try:
                routes = _service_routes()
                response = (client or SecureDrawClient(
                    load_locked_service_origin(), routes["submit"], routes["result"]
                )).download_generated_image(value)
                if response.status_code >= 400:
                    raise _api_error(response, "下载服务端图片")
                raw = response.content
            except requests.RequestException as exc:
                raise RuntimeError(_public_network_failure("图片下载", exc)) from None
            if len(raw) > _MAX_IMAGE_BYTES:
                raise RuntimeError("服务端图片超过 10 MiB 下载限制")
            return raw
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("服务端返回的 Base64 图片无效") from exc

    @staticmethod
    def _save_and_tensor(raw: bytes, task_id: str, index: int) -> tuple[torch.Tensor, str]:
        try:
            pil = Image.open(io.BytesIO(raw))
            pil.load()
        except Exception as exc:
            raise RuntimeError("服务端返回内容不是有效图片") from exc
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get((pil.format or "").upper(), "png")
        output_dir = folder_paths.get_temp_directory()
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"nano_banana_{task_id}_{index}_{uuid.uuid4().hex}.{ext}")
        with open(path, "wb") as handle:
            handle.write(raw)
        tensor = torch.from_numpy(np.asarray(pil.convert("RGB"), dtype=np.float32) / 255.0)
        return tensor, path

    def generate(self, prompt, model, api_key, aspect_ratio, image_size, reply_type,
                 max_poll_attempts, poll_interval, **kwargs):
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt 不能为空")
        config = _provider_config()
        api_key = api_key.strip() or config.get("api_key", "").strip()
        if not api_key:
            raise ValueError("加密配置中的 API Key 为空")
        if model not in _MODEL_LIST:
            raise ValueError("所选模型不在此节点允许的三模型范围内；未提交生成请求")

        # Normalize and validate before any account or generation request.
        aspect_ratio, image_size, reply_type = _normalize_generation_parameters(
            aspect_ratio,
            image_size,
            reply_type,
        )
        max_poll_attempts, poll_interval = _normalize_polling_parameters(
            max_poll_attempts,
            poll_interval,
        )

        if aspect_ratio in _EXTENDED_RATIOS and model != "nano-banana-2":
            raise ValueError(f"{aspect_ratio} 不适用于当前 XINGHUO 模型配置")

        balance_before = query_account_balance(api_key, model)
        if not balance_before["success"]:
            error_text = str(balance_before.get("error", ""))
            if "访问密钥" in error_text or "API Key" in error_text:
                raise ValueError("访问密钥错误或已失效；未提交生成请求")
            raise ValueError("余额或模型计费校验失败；未提交生成请求")
        required_credits = _locked_billing()[model]["credits"]
        if balance_before["credits"] < required_credits:
            raise ValueError("账户可用余额不足以完成当前模型的一次生成；未提交生成请求")

        _check_comfyui_interrupt()
        images = self._collect_images(kwargs)
        # webHook='-1' is the documented way to receive a task id for polling.
        payload = {"model": model, "prompt": prompt, "urls": images, "aspectRatio": aspect_ratio,
                   "imageSize": image_size, "webHook": "-1"}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        routes = _service_routes()
        client = SecureDrawClient(config["base_url"], routes["submit"], routes["result"])

        try:
            _check_comfyui_interrupt()
            response = client.submit(headers, payload)
            result = _unwrap_draw_response(self._parse_json(response, "生成请求"), "生成请求")
            status = _status(result)
            task_id = _task_id(result)
            if status in _TERMINAL_FAILURE:
                raise RuntimeError(f"生成任务 {_upstream_failure_reason(result) or '服务端未提供失败原因'}")
            if not task_id:
                raise RuntimeError("服务端未返回任务 ID，无法查询生成结果")
            if status not in _TERMINAL_SUCCESS or not result.get("results"):
                result = self._poll(task_id, headers, client, max_poll_attempts, poll_interval)
            if not task_id:
                task_id = _task_id(result) or "sync"
            tensors, paths = [], []
            for index, item in enumerate(self._result_items(result), start=1):
                _check_comfyui_interrupt()
                tensor, path = self._save_and_tensor(self._image_bytes(item["value"], client), task_id, index)
                tensors.append(tensor)
                paths.append(path)
            first_shape = tensors[0].shape
            if any(tensor.shape != first_shape for tensor in tensors):
                raise RuntimeError("服务端返回了不同尺寸的多张图片，无法组成 ComfyUI IMAGE batch")
            summary = f"XINGHUO Nano Banana 生成成功\n模型: {model}\n任务 ID: {task_id}\n图片数量: {len(paths)}"
            return _comfy_result(torch.stack(tensors), summary, "\n".join(paths), "success")
        except requests.RequestException as exc:
            return _comfy_result(
                torch.zeros(1, 64, 64, 3),
                f"生成失败：{_public_network_failure('生成请求', exc)}",
                "",
                "failure",
            )
        except (ValueError, RuntimeError) as exc:
            return _comfy_result(torch.zeros(1, 64, 64, 3), f"生成失败：{exc}", "", "failure")


class ComfyuiXinghuoNanoBananaV3(ComfyuiXinghuoNanoBanana):
    """Clean node schema with no non-request reply_type widget."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {f"image{i}": ("IMAGE", {"tooltip": f"Reference image #{i}"}) for i in range(1, 17)}
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (_MODEL_LIST, {"default": "nano-banana-2"}),
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "defaultInput": True,
                        "tooltip": "可直接填写，或连接 TEXT/STRING 节点",
                    },
                ),
                "aspect_ratio": (_BASE_RATIOS + _EXTENDED_RATIOS, {"default": "1:1"}),
                "image_size": (_IMAGE_SIZE_LIST, {"default": "1K"}),
                "max_poll_attempts": ("INT", {"default": 300, "min": 1, "max": 1000}),
                "poll_interval": ("INT", {"default": 5, "min": 1, "max": 60}),
            },
            "optional": optional,
        }

    def generate(
        self,
        prompt,
        model,
        api_key,
        aspect_ratio,
        image_size,
        max_poll_attempts,
        poll_interval,
        **kwargs,
    ):
        return super().generate(
            prompt,
            model,
            api_key,
            aspect_ratio,
            image_size,
            "async",
            max_poll_attempts,
            poll_interval,
            **kwargs,
        )


# The old ID remains loadable and is repaired at both browser and Python layers.
# New workflows should use the clean V3 ID.
NODE_CLASS_MAPPINGS = {
    "comfyui_xinghuo_nano_banana_v3": ComfyuiXinghuoNanoBananaV3,
    _LEGACY_NODE_ID: ComfyuiXinghuoNanoBanana,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "comfyui_xinghuo_nano_banana_v3": "comfyui xinghuo nano banana",
    _LEGACY_NODE_ID: "comfyui xinghuo nano banana ",
}
