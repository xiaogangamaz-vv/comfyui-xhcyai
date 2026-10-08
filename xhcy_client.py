"""XHCY AI (ai.xhcyai.org) service access layer.

Self-contained: only depends on `requests`. Provides submit / poll / download
for the site's OpenAI-compatible image generation endpoints, plus tolerant
response parsers (the gateway wraps fields differently between sync and async).

Every recoverable failure raises XHCYError with a user-facing Chinese message,
which ComfyUI surfaces directly on the node.
"""

from __future__ import annotations

import time
from typing import Any

import requests

DEFAULT_BASE_URL = "https://ai.xhcyai.org"

# Routes documented by the site itself.
MODELS_PATH = "/v1/models"
IMAGE_GENERATIONS_PATH = "/v1/images/generations"
IMAGE_TASK_PATH = "/v1/images/tasks/{task_id}"
VIDEO_GENERATIONS_PATH = "/v1/video/generations"
VIDEO_TASK_PATH = "/v1/video/generations/{task_id}"

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 300  # image/video generation can genuinely take minutes

STATUS_SUCCESS = {"succeeded", "success", "completed", "done", "finished"}
STATUS_FAILURE = {"failed", "failure", "error", "violation", "cancelled", "canceled"}


class XHCYError(RuntimeError):
    """Error message safe to show to the end user."""


def _body_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")
    if isinstance(error, str):
        return error
    return str(payload.get("message") or payload.get("detail") or "")


def _http_error(response: requests.Response, context: str) -> XHCYError:
    code = response.status_code
    detail = _body_message(response)
    suffix = ("：" + detail) if detail else ""
    if code == 400:
        return XHCYError(f"{context}被服务端拒绝（HTTP 400）{suffix}")
    if code == 401:
        return XHCYError("访问密钥错误或已失效（HTTP 401），请检查 api_key")
    if code == 403:
        return XHCYError(f"没有调用权限或账户不可用（HTTP 403）{suffix}")
    if code == 404:
        return XHCYError(f"接口或资源不存在（HTTP 404）{suffix}")
    if code == 429:
        return XHCYError("请求过于频繁（HTTP 429），请稍后重试")
    if code == 451:
        return XHCYError(
            f"{context}被上游以内容合规原因拒绝（HTTP 451）{suffix}；"
            "通常是提示词或参考素材被判为不合规，换一种描述或换一张参考图再试"
        )
    if code == 524:
        return XHCYError("服务端处理超时（HTTP 524，网关等待上限约 100 秒）。带参考图的生成明显更慢，实测单图约 80 秒，请减少参考图数量或缩小分辨率后重试")
    if code in (502, 503, 504):
        return XHCYError(
            f"上游服务暂时不可用（HTTP {code}），已自动重试多次仍未成功；"
            "这通常是站点上游的临时抖动，等一两分钟再试即可"
        )
    if code >= 500:
        return XHCYError(f"服务端暂时不可用（HTTP {code}），请稍后重试")
    return XHCYError(f"{context}失败（HTTP {code}）{suffix}")


class XHCYClient:
    """One instance per node execution; holds the caller's API key."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL):
        api_key = (api_key or "").strip()
        if not api_key:
            raise XHCYError("请填写 XHCY 访问密钥（api_key）")
        base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url.startswith("http://") and not base_url.startswith("https://"):
            raise XHCYError("服务地址必须以 http:// 或 https:// 开头")
        self.api_key = api_key
        self.base_url = base_url
        # 直连优先：实测本机代理（HTTP_PROXY / HTTPS_PROXY）在请求体稍大时
        # （例如带参考图、参考视频的请求）会直接掐断连接并报 ProxyError。
        # 所以默认不走环境代理，只在直连失败时才回退到代理。
        self._direct = requests.Session()
        self._direct.trust_env = False
        self._proxied = requests.Session()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _parse(self, response: requests.Response, context: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise _http_error(response, context)
        try:
            payload = response.json()
        except ValueError as exc:
            raise XHCYError(f"{context}返回了非 JSON 内容，可能是网关错误页") from exc
        if not isinstance(payload, dict):
            raise XHCYError(f"{context}返回格式异常：期望 JSON 对象")
        return payload

    def _send(self, method: str, path: str, context: str, note: str = "", **kwargs):
        """直连优先；直连失败才回退到环境代理，两者都失败才报错。

        超时不回退：超时说明已经连上、只是慢，换通道没有意义。
        """
        url = path if path.startswith("http") else self.base_url + path
        last_error: Exception | None = None
        for session in (self._direct, self._proxied):
            try:
                return session.request(
                    method, url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT), **kwargs
                )
            except requests.Timeout as exc:
                raise XHCYError(f"{context}超时{note}") from exc
            except requests.RequestException as exc:
                last_error = exc
                continue
        raise XHCYError(f"{context}网络失败，请检查网络后重试") from last_error

    # 上游偶发的 502 / 503 / 504（站点原话「服务端暂时不可用」）。
    # 这类状态码表示请求根本没被处理，重试不会造成重复扣费，所以自动重试几次。
    _RETRYABLE_STATUS = frozenset({502, 503, 504})
    _RETRY_DELAYS = (2.0, 5.0)

    def _request_json(self, method: str, path: str, context: str, retry: bool = False, **kwargs) -> dict[str, Any]:
        attempts = len(self._RETRY_DELAYS) + 1 if retry else 1
        response = None
        for index in range(attempts):
            if index:
                time.sleep(self._RETRY_DELAYS[index - 1])
            response = self._send(method, path, context, **kwargs)
            if response.status_code not in self._RETRYABLE_STATUS:
                break
            if index + 1 < attempts:
                print(
                    "[XHCY] %s返回 HTTP %d，%.0f 秒后自动重试"
                    % (context, response.status_code, self._RETRY_DELAYS[index])
                )
        return self._parse(response, context)

    def post_json(self, path: str, payload: dict[str, Any], context: str = "请求") -> dict[str, Any]:
        return self._request_json(
            "POST", path, context, retry=True,
            note="；任务是否已提交无法确认，请先别急着重复提交",
            headers=self._headers, json=payload,
        )

    def get_json(self, path: str, context: str = "查询") -> dict[str, Any]:
        return self._request_json("GET", path, context, headers=self._headers)

    def download(self, url: str, max_bytes: int = 256 * 1024 * 1024) -> bytes:
        """Fetch a generated artifact. Video content lives behind our own /v1 path and needs the bearer token; image URLs are public."""
        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            raise XHCYError("服务端返回的产物地址无效")
        response = self._send(
            "GET", url, "产物下载", note="，请稍后重试",
            headers=(self._headers if url.startswith(self.base_url) else None),
            stream=True,
        )
        if response.status_code >= 400:
            raise _http_error(response, "产物下载")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise XHCYError("产物超过节点允许的下载上限（%d MiB）" % (max_bytes // (1024 * 1024)))
            chunks.append(chunk)
        return b"".join(chunks)

    # ------------------------------------------------------------------ #
    # Convenience wrappers
    # ------------------------------------------------------------------ #

    def list_models(self) -> list[str]:
        payload = self.get_json(MODELS_PATH, "获取模型列表")
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        names: list[str] = []
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
            elif isinstance(item, str):
                names.append(item)
        return names

    def submit_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(IMAGE_GENERATIONS_PATH, payload, "图像生成请求")

    def poll_image(self, task_id: str) -> dict[str, Any]:
        return self.get_json(IMAGE_TASK_PATH.format(task_id=task_id), "图像结果查询")

    def submit_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(VIDEO_GENERATIONS_PATH, payload, "视频生成请求")

    def poll_video(self, task_id: str) -> dict[str, Any]:
        return self.get_json(VIDEO_TASK_PATH.format(task_id=task_id), "视频结果查询")


# ---------------------------------------------------------------------- #
# Response parsers — tolerant of the gateway's several envelope shapes
# ---------------------------------------------------------------------- #

def pick(payload: dict[str, Any], *keys: str) -> Any:
    layers = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        layers.append(data)
    for layer in layers:
        for key in keys:
            value = layer.get(key)
            if value not in (None, ""):
                return value
    return None


def extract_task_id(payload: dict[str, Any]) -> str:
    value = pick(payload, "id", "task_id", "taskId")
    if value:
        return str(value)
    data = payload.get("data")
    if isinstance(data, str):
        return data
    return ""


def extract_status(payload: dict[str, Any]) -> str:
    return str(pick(payload, "status", "state", "task_status") or "").lower()


def extract_image_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    containers: list[Any] = [payload]
    for key in ("data", "results", "result", "output", "images"):
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            containers.append(value)
    seen: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, list):
            for entry in node:
                collect(entry)
            return
        if not isinstance(node, dict):
            return
        value = node.get("url") or node.get("image_url") or node.get("imageUrl")
        if isinstance(value, dict):
            value = value.get("url")
        if value and str(value) not in seen:
            seen.add(str(value))
            urls.append(str(value))

    for container in containers:
        collect(container)
    return urls


def extract_video_url(payload: dict[str, Any]) -> str:
    """Video tasks answer {"status": "succeeded", "content": {"url": ...}}."""
    content = payload.get("content")
    if isinstance(content, dict):
        for key in ("url", "video_url"):
            if content.get(key):
                return str(content[key])
    elif isinstance(content, str) and content.startswith("http"):
        return content
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                value = item.get("url") or item.get("video_url")
                if value:
                    return str(value)
    for key in ("video_url", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def extract_failure_reason(payload: dict[str, Any]) -> str:
    value = pick(payload, "failure_reason", "fail_reason", "error", "message", "detail", "msg")
    if isinstance(value, dict):
        return str(value.get("message") or value.get("code") or "")
    return str(value or "")
