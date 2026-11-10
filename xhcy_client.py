"""XHCY AI (ai.xhcyai.org) service access layer.

Self-contained: only depends on `requests`. Provides submit / poll / download
for the site's OpenAI-compatible image generation endpoints, plus tolerant
response parsers (the gateway wraps fields differently between sync and async).

Every recoverable failure raises XHCYError with a user-facing Chinese message,
which ComfyUI surfaces directly on the node.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
import threading
import time
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError

DEFAULT_BASE_URL = "https://ai.xhcyai.org"

# Routes documented by the site itself.
MODELS_PATH = "/v1/models"
IMAGE_GENERATIONS_PATH = "/v1/images/generations"
IMAGE_TASK_PATH = "/v1/images/tasks/{task_id}"
VIDEO_GENERATIONS_PATH = "/v1/video/generations"
VIDEO_TASK_PATH = "/v1/video/generations/{task_id}"
# 768P -> 2K 再生成：结果仍走 /v1/video/generations/{task_id} 轮询
VIDEO_REGENERATIONS_PATH = "/v1/video/regenerations"
# H3 Context-IR：同步返回增强后的提示词，不产生可查询任务
VIDEO_CONTEXT_IR_PATH = "/v1/video/context-ir"
# 视频超分（Video Super-Resolution）：提交与查询都在 /v1/video/enhance 下，
# 与生成任务的 /v1/video/generations/{task_id} **不是同一条路径**，必须分开。
VIDEO_ENHANCE_PATH = "/v1/video/enhance"
VIDEO_ENHANCE_TASK_PATH = "/v1/video/enhance/{task_id}"
# 文本/对话模型（OpenAI 兼容）
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 300  # image/video generation can genuinely take minutes
# Handshake retries only. A failed handshake means the request never left the
# machine, so repeating it cannot submit the same generation twice.
_CONNECT_RETRY_DELAYS = (0.4, 1.0)
# Second address family starts this long after the first, so a stalled route
# does not consume the whole handshake budget before a working route is tried.
_FAMILY_STAGGER = 0.25

# When a task result points at another host, ask the gateway for the bytes first.
_ARTIFACT_PATHS = {
    "image": "/v1/images/tasks/{task_id}/content",
    "video": "/v1/video/generations/{task_id}/content",
    "enhance": "/v1/video/enhance/{task_id}/content",
}

STATUS_SUCCESS = {"succeeded", "success", "completed", "complete", "done", "finished"}
# timeout / timed_out are terminal on the image task API. They must fail the
# poll immediately, not burn max_poll_attempts and then look like a client wait.
STATUS_FAILURE = {
    "failed", "failure", "fail", "error", "violation", "cancelled", "canceled",
    "timeout", "timed_out",
}


def model_rejects_quality(model: str) -> bool:
    """Banana and Gemini image models answer HTTP 400 param_not_supported for quality."""
    name = (model or "").strip().lower()
    if not name:
        return False
    if "banana" in name:
        return True
    # gemini-2.5-flash-image, gemini-3.1-flash-image-preview, and the same shape.
    return "gemini" in name and "image" in name


def _origin_of(url: str) -> str:
    """scheme://host:port, so a same-site content URL is not confused with another host."""
    parsed = requests.utils.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return "%s://%s:%s" % (parsed.scheme, parsed.hostname.lower(), port)


def _resolve_addresses(host: str, port: int) -> list[tuple[int, Any]]:
    if host.startswith("["):
        host = host.strip("[]")
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.version == 4:
            return [(socket.AF_INET, (host, port))]
        return [(socket.AF_INET6, (host, port, 0, 0))]
    found = []
    seen = set()
    for family, _socktype, _proto, _canon, sockaddr in socket.getaddrinfo(
        host, port, socket.AF_UNSPEC, socket.SOCK_STREAM
    ):
        if sockaddr in seen:
            continue
        seen.add(sockaddr)
        found.append((family, sockaddr))
    return found


def connect_candidates(addresses, timeout, socket_options=None, source_address=None):
    """Open one TCP connection.

    Address families run together, with the second family delayed slightly.
    The first socket that connects wins. A family that never answers does not
    have to time out before another family is attempted.
    """
    if not addresses:
        raise OSError("getaddrinfo returned no addresses")
    if timeout is None or timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        budget = float(_CONNECT_TIMEOUT)
    else:
        budget = float(timeout)
    deadline = time.monotonic() + max(budget, 0.1)
    families = []
    for family, _sockaddr in addresses:
        if family not in families:
            families.append(family)
    families.sort(key=lambda family: 0 if family == socket.AF_INET else 1)

    winner: dict[str, socket.socket] = {}
    errors: list[BaseException] = []
    lock = threading.Lock()
    done = threading.Event()

    def attempt(family, sockaddr):
        if done.is_set() or time.monotonic() >= deadline:
            return
        remaining = deadline - time.monotonic()
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if socket_options:
                for level, option, value in socket_options:
                    sock.setsockopt(level, option, value)
            if source_address:
                sock.bind(source_address)
            sock.settimeout(max(remaining, 0.05))
            sock.connect(sockaddr)
        except OSError as exc:
            sock.close()
            with lock:
                errors.append(exc)
            return
        with lock:
            if done.is_set():
                sock.close()
                return
            winner["sock"] = sock
            done.set()

    for index, family in enumerate(families):
        if index and done.wait(min(_FAMILY_STAGGER, max(0.0, deadline - time.monotonic()))):
            break
        for family_item, sockaddr in addresses:
            if family_item != family or done.is_set() or time.monotonic() >= deadline:
                continue
            threading.Thread(
                target=attempt, args=(family_item, sockaddr), daemon=True
            ).start()
    remaining = deadline - time.monotonic()
    if remaining > 0:
        done.wait(remaining)
    sock = winner.get("sock")
    if sock is not None:
        return sock
    if errors:
        raise errors[-1]
    raise socket.timeout("timed out")


class _RacingHTTPConnection(HTTPConnection):
    def _new_conn(self) -> socket.socket:
        host = self._dns_host
        port = self.port
        try:
            addresses = _resolve_addresses(host, int(port))
            return connect_candidates(
                addresses, self.timeout, self.socket_options, self.source_address
            )
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        except TimeoutError as exc:
            raise ConnectTimeoutError(
                self,
                "Connection to %s timed out. (connect timeout=%s)" % (self.host, self.timeout),
            ) from exc
        except OSError as exc:
            raise NewConnectionError(
                self, "Failed to establish a new connection: %s" % exc
            ) from exc


class _RacingHTTPSConnection(_RacingHTTPConnection, HTTPSConnection):
    pass


class _RacingHTTPPool(HTTPConnectionPool):
    ConnectionCls = _RacingHTTPConnection


class _RacingHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _RacingHTTPSConnection


class _GatewayAdapter(HTTPAdapter):
    """Use the racing handshake for connections this process opens itself."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _RacingHTTPPool,
            "https": _RacingHTTPSPool,
        }


def _new_session(trust_env: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    adapter = _GatewayAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _environ_proxies(url: str) -> bool:
    try:
        return bool(requests.utils.get_environ_proxies(url))
    except Exception:
        return False


def _request_not_sent(exc: BaseException) -> bool:
    """True only when the HTTP request cannot have reached the gateway.

    A dropped upload or a read timeout may already have been accepted, and
    repeating it could record the same generation twice. A handshake that
    never completed cannot.
    """
    if isinstance(exc, requests.ConnectTimeout):
        return True
    if isinstance(exc, (requests.ReadTimeout, requests.Timeout)):
        return False
    if not isinstance(exc, requests.ConnectionError):
        return False
    if isinstance(exc, (requests.exceptions.ChunkedEncodingError, requests.exceptions.SSLError)):
        return False
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "failed to establish a new connection",
            "connection refused",
            "name or service not known",
            "temporary failure in name resolution",
            "network is unreachable",
            "no route to host",
            "nodename nor servname",
        )
    )


def _read_body(response: requests.Response, max_bytes: int) -> bytes:
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


def model_supports_quality(model: str) -> bool:
    """gpt-image 2.5 / 2.6 tiers accept quality. Banana-family ids never do."""
    if model_rejects_quality(model):
        return False
    # "gpt-image-2" and "gpt-image-2-vip" do not match; "gpt-image-2.6" does.
    return (model or "").strip().lower().startswith("gpt-image-2.")


class XHCYError(RuntimeError):
    """Error message safe to show to the end user."""


def _payload_mentions(response: requests.Response, needle: str) -> bool:
    """True when the JSON body contains needle in any nested string (code or message)."""
    needle = needle.lower()
    try:
        payload = response.json()
    except ValueError:
        return needle in (response.text or "").lower()

    def walk(node: Any) -> bool:
        if isinstance(node, str):
            return needle in node.lower()
        if isinstance(node, dict):
            return any(walk(value) for value in node.values())
        if isinstance(node, list):
            return any(walk(value) for value in node)
        return False

    return walk(payload)


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
    if code == 400 and _payload_mentions(response, "async_generation_disabled"):
        # The gate ignores ?async=true. Body {"async": true} is rejected with this
        # code when ASYNC_GENERATION_ENABLED is off. Do not retry as a sync call.
        return XHCYError(
            "图像异步生成未开启（HTTP 400 async_generation_disabled）。"
            "请在网关设置环境变量 ASYNC_GENERATION_ENABLED=true 后重启。"
            "节点不会退回同步请求，否则会再次撞上 Cloudflare 524。"
            + suffix
        )
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
        # 自己连网关。地址族并行握手，避免一条没有回应的地址占满等待时间。
        # 不读取进程环境里的出站通道；那条路只在直连握手失败后才作为备用。
        self._direct = _new_session(trust_env=False)
        self._proxied = _new_session(trust_env=True)

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
        """Call the gateway.

        A handshake failure is retried: the HTTP request was not sent, so a
        repeat cannot create a second billed task. A read timeout is not
        retried, because the gateway may already be working on the request.
        """
        url = path if path.startswith("http") else self.base_url + path
        sessions = [self._direct]
        if _environ_proxies(url):
            sessions.append(self._proxied)
        last_error: Exception | None = None
        for session in sessions:
            attempts = len(_CONNECT_RETRY_DELAYS) + 1 if session is self._direct else 1
            try_next_session = False
            for attempt in range(attempts):
                try:
                    return session.request(
                        method, url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT), **kwargs
                    )
                except requests.RequestException as exc:
                    last_error = exc
                    # Only a handshake that never completed is safe to repeat.
                    if (
                        session is self._direct
                        and _request_not_sent(exc)
                        and attempt + 1 < attempts
                    ):
                        print(
                            "[XHCY] %s握手未完成，%.1f 秒后重试"
                            % (context, _CONNECT_RETRY_DELAYS[attempt])
                        )
                        time.sleep(_CONNECT_RETRY_DELAYS[attempt])
                        continue
                    try_next_session = _request_not_sent(exc)
                    break
            if not try_next_session:
                break
        if isinstance(last_error, requests.Timeout):
            raise XHCYError(f"{context}超时{note}") from last_error
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
        """Fetch a generated artifact.

        Same-host redirects stay on the gateway and keep the bearer token.
        A redirect to any other host is followed once, without the token.
        Video content on our own /v1 path needs that token; public image URLs do not.
        """
        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            raise XHCYError("服务端返回的产物地址无效")
        current = url
        left_gateway = False
        for _hop in range(4):
            on_gateway = _origin_of(current) == _origin_of(self.base_url)
            response = self._send(
                "GET", current, "产物下载", note="，请稍后重试",
                headers=(self._headers if on_gateway else None),
                stream=True,
                allow_redirects=False,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = urljoin(current, response.headers.get("Location") or "")
                closer = getattr(response, "close", None)
                if closer:
                    closer()
                if not location.startswith(("http://", "https://")):
                    raise XHCYError("产物下载返回了无效的跳转地址")
                same_site = (
                    _origin_of(location) == _origin_of(current)
                    or _origin_of(location) == _origin_of(self.base_url)
                )
                if not same_site:
                    if left_gateway:
                        raise XHCYError("产物下载被连续转到网关以外的地址，没有直接返回文件")
                    left_gateway = True
                current = location
                continue
            if response.status_code >= 400:
                raise _http_error(response, "产物下载")
            return _read_body(response, max_bytes)
        raise XHCYError("产物下载跳转次数过多，请稍后重试")

    def artifact_urls(self, url: str, task_id: str = "", kind: str = "image") -> list[str]:
        """Gateway URL first, any other host after it.

        A result link on another host is only used when the gateway does not
        serve the bytes itself. Image, video and enhance tasks share this order.
        """
        ordered: list[str] = []

        def add(value: str) -> None:
            if value and value not in ordered:
                ordered.append(value)

        text = url if isinstance(url, str) else ""
        on_gateway = bool(text) and _origin_of(text) == _origin_of(self.base_url)
        if on_gateway:
            add(text)
        template = _ARTIFACT_PATHS.get(kind)
        task = (task_id or "").strip()
        if task and template and "://" not in task and " " not in task:
            add(self.base_url + template.format(task_id=task))
        if text.startswith(("http://", "https://")) and not on_gateway:
            add(text)
        return ordered

    def image_bytes(self, slot: dict, task_id: str = "") -> bytes:
        """Prefer bytes the gateway already returned, then a gateway URL, then any other URL."""
        raw = slot.get("raw") if isinstance(slot, dict) else None
        if isinstance(raw, (bytes, bytearray)) and _looks_like_image(bytes(raw)):
            return bytes(raw)
        url = ""
        if isinstance(slot, dict):
            url = slot.get("url") or ""
        last: XHCYError | None = None
        for candidate in self.artifact_urls(url, task_id, "image"):
            try:
                data = self.download(candidate)
            except XHCYError as exc:
                last = exc
                continue
            if _looks_like_image(data):
                return data
            last = XHCYError("产物下载返回的内容不是图片")
        if isinstance(raw, (bytes, bytearray)) and raw:
            return bytes(raw)
        if last:
            raise last
        raise XHCYError("服务端返回的图片字段无法识别")

    def media_bytes(self, url: str, task_id: str = "", kind: str = "video",
                    max_bytes: int = 256 * 1024 * 1024) -> bytes:
        """Download a video-like artifact, asking the gateway before any other host."""
        last: XHCYError | None = None
        for candidate in self.artifact_urls(url, task_id, kind):
            try:
                data = self.download(candidate, max_bytes=max_bytes)
            except XHCYError as exc:
                last = exc
                continue
            stripped = data.lstrip()
            if stripped[:1] in (b"{", b"<"):
                last = XHCYError("产物下载返回的内容不是媒体文件")
                continue
            return data
        if last:
            raise last
        raise XHCYError("服务端返回的产物地址无效")

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
        """Submit POST /v1/images/generations with {"async": true} in the JSON body.

        Platform IsAsyncImageRequest only reads that body field. A query string
        (?async=true) is ignored, and the call stays synchronous until Cloudflare
        returns 524. Callers poll with poll_image. A gateway that still inlines
        data[] is fine — the body is returned as-is.

        If the gate has ASYNC_GENERATION_ENABLED unset, the response is HTTP 400
        async_generation_disabled. That error is raised as-is; there is no sync
        fallback.

        response_format is never forwarded. quality is dropped for banana / Gemini
        image models (HTTP 400 param_not_supported) and when the caller left it
        at auto.
        """
        body = dict(payload)
        body.pop("response_format", None)
        quality = str(body.get("quality") or "").strip().lower()
        if not quality or quality == "auto" or model_rejects_quality(str(body.get("model") or "")):
            body.pop("quality", None)
        body["async"] = True
        return self.post_json(IMAGE_GENERATIONS_PATH, body, "图像生成请求")

    def poll_image(self, task_id: str) -> dict[str, Any]:
        return self.get_json(IMAGE_TASK_PATH.format(task_id=task_id), "图像结果查询")

    def submit_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(VIDEO_GENERATIONS_PATH, payload, "视频生成请求")

    def poll_video(self, task_id: str) -> dict[str, Any]:
        return self.get_json(VIDEO_TASK_PATH.format(task_id=task_id), "视频结果查询")

    def list_video_tasks(self, page: int = 1, size: int = 10) -> dict[str, Any]:
        """列出本密钥最近提交的视频任务。

        用来在「提交请求被网关超时掐断」之后找回任务：站点是同步等上游建任务的，
        而它自己没设超时，所以 Cloudflare 报了 524 之后任务其实还在后台建，
        很快就会出现在这个列表里。
        """
        path = "%s?page_num=%d&page_size=%d" % (VIDEO_GENERATIONS_PATH, int(page), int(size))
        return self.get_json(path, "视频任务列表")

    def submit_video_regeneration(self, payload: dict[str, Any]) -> dict[str, Any]:
        """768P -> 2K 再生成。请求体与生成接口不同，见 BuildRegenerationPayload。"""
        return self.post_json(VIDEO_REGENERATIONS_PATH, payload, "视频再生成请求")

    def submit_video_enhancement(self, payload: dict[str, Any]) -> dict[str, Any]:
        """视频超分提交。两种输入二选一：source_task_id 或 content 里的 base_video。"""
        return self.post_json(VIDEO_ENHANCE_PATH, payload, "视频超分请求")

    def poll_video_enhancement(self, task_id: str) -> dict[str, Any]:
        """超分任务的查询路径与生成任务不同，不能复用 poll_video。"""
        return self.get_json(
            VIDEO_ENHANCE_TASK_PATH.format(task_id=task_id), "视频超分结果查询"
        )

    def submit_context_ir(self, payload: dict[str, Any]) -> dict[str, Any]:
        """H3 Context-IR。站点同步等待上游产出一段增强后的提示词，可能需要 1～2 分钟。"""
        return self.post_json(VIDEO_CONTEXT_IR_PATH, payload, "Context-IR 请求")

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """文本/对话模型（OpenAI 兼容的 /v1/chat/completions）。"""
        return self.post_json(CHAT_COMPLETIONS_PATH, payload, "对话请求")


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
    if value and not isinstance(value, (dict, list)):
        text = str(value).strip()
        # A base64 blob is not a task id. Real ids are short tokens.
        if text and len(text) <= 200 and " " not in text and "\n" not in text:
            return text
    data = payload.get("data")
    if isinstance(data, str):
        text = data.strip()
        if not text or " " in text or "\n" in text or len(text) > 200:
            return ""
        # Some gateways put the image bytes directly in `data`. That must not
        # be polled as a task id, even when the blob is a tiny PNG.
        if text.startswith("data:") or _decode_b64_image(text):
            return ""
        return text
    return ""


def extract_status(payload: dict[str, Any]) -> str:
    return str(pick(payload, "status", "state", "task_status") or "").lower()


# Fields the gateway may use to embed the image bytes instead of linking them.
# Live /v1/images/generations replies often contain data[].b64_json and no url.
_B64_FIELDS = ("b64_json", "b64", "base64", "image_base64", "imageBase64")
# `content` is the async task envelope: {"content": {"url": "https://.../content"}}.
# `data` stays for synchronous OpenAI-style data[].url / data[].b64_json.
_IMAGE_CONTAINER_KEYS = ("data", "results", "result", "output", "images", "content")


def _looks_like_image(raw: bytes) -> bool:
    if len(raw) < 8:
        return False
    if raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff"):
        return True
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return True
    return len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"


def _decode_b64_image(value: str) -> bytes | None:
    """Decode one base64 payload, tolerating a data-URI prefix and padding."""
    text = value.strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    text = text.strip()
    if not text:
        return None
    # Some gateways emit newlines inside the blob; strip whitespace before padding.
    text = "".join(text.split())
    text += "=" * (-len(text) % 4)
    try:
        raw = base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError):
        return None
    # Short non-images (task ids, model names) are valid base64 too. Keep a
    # decoded blob when it is an actual image, or when it is long enough that
    # it cannot be one of those tokens.
    if _looks_like_image(raw) or len(raw) > 512:
        return raw
    return None


def _http_url(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("url")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def extract_image_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Image items in response order.

    Each slot is {"url": str | None, "raw": bytes | None}.

    Sync replies use data[].url and data[].b64_json. Async task replies use
    content.url (or a nested content object / a bare http content string).
    A data[] entry with only url and a sibling with only b64_json both show up,
    in that order. When one entry carries both, both fields are kept so the
    caller can download the url and fall back to the embedded bytes.
    """
    slots: list[dict[str, Any]] = []
    seen: set[int] = set()

    def fields(node: dict[str, Any]) -> tuple[str | None, bytes | None]:
        url = None
        for key in ("url", "image_url", "imageUrl"):
            if key in node:
                url = _http_url(node.get(key))
                if url:
                    break
        raw = None
        for field in _B64_FIELDS:
            value = node.get(field)
            if isinstance(value, dict):
                value = value.get("data") or value.get("base64")
            if isinstance(value, str) and value.strip():
                raw = _decode_b64_image(value)
                if raw:
                    break
        if raw is None:
            for key in ("url", "image_url", "imageUrl"):
                value = node.get(key)
                if isinstance(value, dict):
                    value = value.get("url")
                if isinstance(value, str) and value.strip().startswith("data:"):
                    raw = _decode_b64_image(value)
                    if raw:
                        break
        return url, raw

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for entry in node:
                walk(entry)
            return
        if not isinstance(node, dict):
            return
        marker = id(node)
        if marker in seen:
            return
        seen.add(marker)
        kids = [
            node[key]
            for key in _IMAGE_CONTAINER_KEYS
            if isinstance(node.get(key), (list, dict))
        ]
        content = node.get("content")
        content_url = _http_url(content) if isinstance(content, str) else None
        url, raw = fields(node)
        if kids or content_url:
            before = len(slots)
            for child in kids:
                walk(child)
            if content_url:
                slots.append({"url": content_url, "raw": None})
            if len(slots) == before and (url or raw):
                slots.append({"url": url, "raw": raw})
            return
        if url or raw:
            slots.append({"url": url, "raw": raw})

    walk(payload)
    return slots


def extract_image_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for slot in extract_image_slots(payload):
        url = slot.get("url")
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_inline_images(payload: dict[str, Any]) -> list[bytes]:
    """Images embedded in the response body, in the same order as data[]."""
    blobs: list[bytes] = []
    for slot in extract_image_slots(payload):
        raw = slot.get("raw")
        if isinstance(raw, (bytes, bytearray)) and raw:
            blobs.append(bytes(raw))
    return blobs


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


def extract_chat_text(payload: dict[str, Any]) -> str:
    """从 /v1/chat/completions 的返回里取出正文。

    choices[0].message.content 可能是字符串，也可能是分片数组
    （多模态或部分网关会把文本拆成 [{"type": "text", "text": "..."}]）。
    """
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for piece in content:
                        if isinstance(piece, dict) and piece.get("text"):
                            parts.append(str(piece["text"]))
                        elif isinstance(piece, str):
                            parts.append(piece)
                    if parts:
                        return "".join(parts)
            text = choice.get("text")
            if isinstance(text, str) and text.strip():
                return text

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("content", "text", "answer", "output"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("content", "text", "answer"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def extract_prompt(payload: dict[str, Any]) -> str:
    """Context-IR 的产物：{"success": true, "data": {"task_id": ..., "prompt": "..."}}."""
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("prompt", "enhanced_prompt", "text"):
            value = data.get(key)
            if value:
                return str(value)
    if isinstance(data, str) and data.strip():
        return data
    for key in ("prompt", "enhanced_prompt"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def extract_failure_reason(payload: dict[str, Any]) -> str:
    value = pick(payload, "failure_reason", "fail_reason", "error", "message", "detail", "msg")
    if isinstance(value, dict):
        return str(value.get("message") or value.get("code") or "")
    return str(value or "")
