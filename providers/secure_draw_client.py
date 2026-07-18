"""HTTP transport for the encrypted service profile's asynchronous draw API."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import requests


class SecureDrawClient:
    """Transport client whose origin and routes are supplied after decryption."""

    def __init__(self, base_url: str, generation_path: str, result_path: str):
        parsed = urlparse(str(base_url).strip())
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("服务端 URL 必须是无凭据的 HTTPS 地址")
        if any(not isinstance(path, str) or not path.startswith("/") or "://" in path
               for path in (generation_path, result_path)):
            raise ValueError("服务端路由配置无效")
        self.base_url = str(base_url).rstrip("/")
        self._generation_path = generation_path
        self._result_path = result_path

    @property
    def generation_url(self) -> str:
        return self.base_url + self._generation_path

    @property
    def result_url(self) -> str:
        return self.base_url + self._result_path

    @staticmethod
    def request(method: str, url: str, **kwargs: Any) -> requests.Response:
        """Keep TLS verification enabled and impose bounded connect/read timeouts."""
        return requests.request(method, url, timeout=(10, 120), **kwargs)

    def submit(self, headers: dict[str, str], payload: dict[str, Any]) -> requests.Response:
        return self.request("POST", self.generation_url, headers=headers, json=payload)

    def poll_once(self, headers: dict[str, str], task_id: str) -> requests.Response:
        return self.request("POST", self.result_url, headers=headers, json={"id": task_id})

    def download_generated_image(self, value: str) -> requests.Response:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("服务端图片 URL 必须是无凭据的 HTTPS 地址")
        self._require_public_host(parsed.hostname or "", parsed.port or 443)
        # Never attach the service Authorization header to an untrusted result URL.
        return self.request("GET", value, stream=True, allow_redirects=False)

    @staticmethod
    def _require_public_host(hostname: str, port: int) -> None:
        """Reject result URLs resolving to loopback, private, or reserved IPs."""
        try:
            addresses = {str(ipaddress.ip_address(hostname))}
        except ValueError:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)}
            except socket.gaierror as exc:
                raise ValueError("服务端图片 URL 主机无法解析") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("服务端图片 URL 不能指向私有或保留网络地址")
