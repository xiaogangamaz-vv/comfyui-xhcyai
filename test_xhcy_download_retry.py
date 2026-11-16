"""Artifact download retries.

HTTP is stubbed. These tests do not open a socket, do not call the API
origin, and do not use a real key.
"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

import xhcy_client
import xhcy_image_base
from nodes_nano_banana import XHCYNanoBanana
from xhcy_client import XHCYClient, XHCYError

CONTENT = "https://example.invalid/v1/images/tasks/task-1/content"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Resp:
    def __init__(self, status_code=200, content=b"", headers=None, payload=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1024):
        yield self.content

    def close(self):
        return None


class DownloadRetryTests(unittest.TestCase):
    def setUp(self):
        self.client = XHCYClient("sk-test", "https://example.invalid")
        self.calls = []
        self.slept = []
        sleep_patch = mock.patch.object(
            xhcy_client.time, "sleep", side_effect=self.slept.append
        )
        proxy_patch = mock.patch.object(xhcy_client, "_environ_proxies", lambda _url: False)
        sleep_patch.start()
        proxy_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.addCleanup(proxy_patch.stop)

    def test_retry_budget_is_two_short_backoffs(self):
        self.assertEqual(xhcy_client._DOWNLOAD_RETRY_DELAYS, (1.0, 2.0))

    def test_content_read_timeout_is_retried_on_the_same_url(self):
        def request(_session, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if len(self.calls) == 1:
                raise requests.ReadTimeout(
                    "HTTPSConnectionPool(host='example.invalid', port=443): "
                    "Read timed out. (read timeout=300)"
                )
            return _Resp(content=PNG)

        with mock.patch.object(requests.Session, "request", request):
            data = self.client.download(CONTENT)

        self.assertEqual(data, PNG)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.slept, [1.0])
        for method, url, kwargs in self.calls:
            self.assertEqual(method, "GET")
            self.assertEqual(url, CONTENT)
            headers = kwargs.get("headers") or {}
            self.assertEqual(headers.get("Authorization"), "Bearer sk-test")
            self.assertNotIn("Content-Type", headers)
            self.assertNotIn("content-type", headers)
            self.assertIsNone(kwargs.get("json"))
            self.assertFalse(kwargs.get("allow_redirects"))

    def test_image_bytes_retries_content_timeout_without_another_host(self):
        def request(_session, method, url, **kwargs):
            self.calls.append((method, url))
            if len(self.calls) == 1:
                raise requests.ReadTimeout("Read timed out. (read timeout=300)")
            return _Resp(content=PNG)

        with mock.patch.object(requests.Session, "request", request):
            data = self.client.image_bytes({"url": CONTENT, "raw": None}, "task-1")

        self.assertEqual(data, PNG)
        self.assertEqual(self.calls, [("GET", CONTENT), ("GET", CONTENT)])
        self.assertEqual(
            self.client.artifact_urls(CONTENT, "task-1", "image"),
            [CONTENT],
        )

    def test_gateway_unavailable_statuses_are_retried(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                calls = []
                slept = []

                def request(_session, method, url, **kwargs):
                    calls.append((method, url, kwargs))
                    if len(calls) == 1:
                        return _Resp(status_code=status, payload={"error": {"message": "busy"}})
                    return _Resp(content=PNG)

                with mock.patch.object(requests.Session, "request", request), mock.patch.object(
                    xhcy_client.time, "sleep", side_effect=slept.append
                ):
                    data = self.client.download(CONTENT)

                self.assertEqual(data, PNG)
                self.assertEqual([item[0] for item in calls], ["GET", "GET"])
                self.assertEqual(calls[0][1], CONTENT)
                self.assertEqual(calls[1][1], CONTENT)
                self.assertEqual(slept, [1.0])
                self.assertNotIn("POST", [item[0] for item in calls])

    def test_pre_send_handshake_failure_is_retried(self):
        failures = (
            requests.ConnectTimeout("timed out"),
            requests.ConnectionError(
                "Failed to establish a new connection: [Errno 111] Connection refused"
            ),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                calls = []

                def request(_session, method, url, **kwargs):
                    calls.append((method, url))
                    if len(calls) == 1:
                        raise failure
                    return _Resp(content=PNG)

                with mock.patch.object(requests.Session, "request", request):
                    data = self.client.download(CONTENT)

                self.assertEqual(data, PNG)
                self.assertEqual(calls, [("GET", CONTENT), ("GET", CONTENT)])

    def test_exhausted_read_timeout_does_not_submit(self):
        def request(_session, method, url, **kwargs):
            self.calls.append((method, url))
            raise requests.ReadTimeout("Read timed out. (read timeout=300)")

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                self.client.image_bytes({"url": CONTENT, "raw": None}, "task-1")

        message = str(caught.exception)
        self.assertIn("产物下载已发出，但等待网关响应超时", message)
        self.assertIn("请稍后重试下载", message)
        self.assertIn("不要立刻重新提交生成", message)
        self.assertEqual(self.calls, [("GET", CONTENT)] * 3)
        self.assertEqual(self.slept, [1.0, 2.0])

    def test_exhausted_502_does_not_submit(self):
        def request(_session, method, url, **kwargs):
            self.calls.append((method, url))
            return _Resp(status_code=502, payload={"error": {"message": "busy"}})

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                self.client.download(CONTENT)

        message = str(caught.exception)
        self.assertIn("HTTP 502", message)
        self.assertIn("已自动重试多次仍未成功", message)
        self.assertIn("请稍后重试下载", message)
        self.assertIn("不要立刻重新提交生成", message)
        self.assertEqual(self.calls, [("GET", CONTENT)] * 3)
        self.assertEqual(self.slept, [1.0, 2.0])

    def test_submit_read_timeout_is_not_retried_as_a_new_task(self):
        calls = []

        def request(_session, method, url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            raise requests.ReadTimeout("Read timed out. (read timeout=300)")

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                self.client.submit_image({"model": "nano-banana-2", "prompt": "a cat"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "POST")
        self.assertTrue(calls[0][1].endswith("/v1/images/generations"), calls[0][1])
        self.assertIs(calls[0][2]["async"], True)
        message = str(caught.exception)
        self.assertIn("图像生成请求已发出，但等待网关响应超时", message)
        self.assertIn("任务是否已提交无法确认，请先别急着重复提交", message)
        self.assertNotIn("产物下载", message)
        self.assertEqual(self.slept, [])

    def test_content_only_response_does_not_invent_fallback_urls(self):
        self.assertEqual(
            self.client.artifact_urls(CONTENT, "task-1", "image"),
            [CONTENT],
        )
        calls = []

        def request(_session, method, url, **_kwargs):
            calls.append((method, url))
            raise requests.ReadTimeout("Read timed out. (read timeout=300)")

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError):
                self.client.image_bytes({"url": CONTENT, "raw": None}, "task-1")

        self.assertEqual(calls, [("GET", CONTENT)] * 3)
        hosts = {requests.utils.urlparse(url).hostname for _method, url in calls}
        self.assertEqual(hosts, {"example.invalid"})

    def test_returned_extra_link_is_next_and_no_third_host_is_invented(self):
        foreign = "https://cdn.example/result.png"
        self.assertEqual(
            self.client.artifact_urls(foreign, "task-1", "image"),
            [CONTENT, foreign],
        )
        calls = []

        def request(_session, method, url, **_kwargs):
            calls.append((method, url))
            if url == CONTENT:
                raise requests.ReadTimeout("Read timed out. (read timeout=300)")
            if url == foreign:
                return _Resp(content=PNG)
            raise AssertionError(url)

        with mock.patch.object(requests.Session, "request", request):
            data = self.client.image_bytes({"url": foreign, "raw": None}, "task-1")

        self.assertEqual(data, PNG)
        self.assertEqual(calls, [("GET", CONTENT)] * 3 + [("GET", foreign)])
        self.assertNotIn("POST", [method for method, _url in calls])

    def test_client_error_and_other_server_error_are_not_retried(self):
        for status in (404, 500):
            with self.subTest(status=status):
                calls = []

                def request(_session, method, url, **_kwargs):
                    calls.append((method, url))
                    return _Resp(status_code=status, payload={"error": {"message": "no"}})

                with mock.patch.object(requests.Session, "request", request):
                    with self.assertRaises(XHCYError) as caught:
                        self.client.download(CONTENT)

                self.assertEqual(calls, [("GET", CONTENT)])
                self.assertIn("HTTP %d" % status, str(caught.exception))
                self.assertEqual(self.slept, [])

    def test_generate_does_not_resubmit_when_content_download_times_out(self):
        calls = []

        def request(_session, method, url, **_kwargs):
            calls.append((method, url))
            if method == "POST":
                return _Resp(payload={"task_id": "task-1", "status": "queued"})
            if url.endswith("/v1/images/tasks/task-1"):
                return _Resp(
                    payload={
                        "task_id": "task-1",
                        "status": "succeeded",
                        "content": {"url": CONTENT},
                    }
                )
            if url == CONTENT:
                raise requests.ReadTimeout("Read timed out. (read timeout=300)")
            raise AssertionError((method, url))

        with mock.patch.object(requests.Session, "request", request), mock.patch.object(
            xhcy_image_base, "sleep_interruptible", lambda *_args, **_kwargs: None
        ):
            with self.assertRaises(XHCYError) as caught:
                XHCYNanoBanana().generate(
                    prompt="a red square",
                    model="nano-banana-2",
                    api_key="sk-test",
                    max_poll_attempts=2,
                    poll_interval=1,
                    base_url="https://example.invalid",
                    aspect_ratio="1:1",
                    image_size="1K",
                )

        posts = [item for item in calls if item[0] == "POST"]
        downloads = [item for item in calls if item[1] == CONTENT]
        self.assertEqual(posts, [("POST", "https://example.invalid/v1/images/generations")])
        self.assertEqual(downloads, [("GET", CONTENT)] * 3)
        message = str(caught.exception)
        self.assertIn("产物下载已发出，但等待网关响应超时", message)
        self.assertIn("不要立刻重新提交生成", message)
        self.assertNotIn("请先别急着重复提交", message)

    def test_same_origin_redirect_keeps_bearer(self):
        target = "https://example.invalid/v1/images/tasks/task-1/file"
        calls = []

        def request(_session, method, url, **kwargs):
            calls.append((method, url, kwargs.get("headers")))
            if url == CONTENT:
                return _Resp(status_code=302, headers={"Location": target})
            return _Resp(content=PNG)

        with mock.patch.object(requests.Session, "request", request):
            data = self.client.download(CONTENT)

        self.assertEqual(data, PNG)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0:2], ("GET", CONTENT))
        self.assertEqual(calls[1][0:2], ("GET", target))
        self.assertEqual(calls[0][2]["Authorization"], "Bearer sk-test")
        self.assertEqual(calls[1][2]["Authorization"], "Bearer sk-test")


if __name__ == "__main__":
    unittest.main()
