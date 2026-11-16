"""Image generation contract: b64_json, no banana quality, no response_format, async poll.

These tests stub HTTP. They do not call ai.xhcyai.org and do not need a key.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from unittest import mock

import requests
from PIL import Image

import xhcy_image_base
from nodes_gpt_image_25 import XHCYGPTImage25
from nodes_nano_banana import XHCYNanoBanana
from xhcy_client import (
    XHCYClient,
    XHCYError,
    extract_image_slots,
    model_rejects_quality,
    model_supports_quality,
)
from xhcy_image_base import XHCYImageBase


def _png(color: str, size: tuple[int, int] = (8, 8)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


RED = _png("red")
BLUE = _png("blue")
RED_B64 = _b64(RED)
BLUE_B64 = _b64(BLUE)


class _Resp:
    def __init__(self, payload=None, status_code=200, content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = ""

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1024):
        yield self.content


class ImageParserTests(unittest.TestCase):
    def test_b64_only_url_only_and_mixed_keep_order(self):
        b64_only = {"data": [{"b64_json": RED_B64}]}
        url_only = {"data": [{"url": "https://cdn.example/a.png"}]}
        mixed = {
            "data": [
                {"b64_json": RED_B64},
                {"url": "https://cdn.example/b.png"},
                {"url": "https://cdn.example/c.png", "b64_json": BLUE_B64},
            ]
        }

        slots = extract_image_slots(b64_only)
        self.assertEqual(len(slots), 1)
        self.assertIsNone(slots[0]["url"])
        self.assertEqual(slots[0]["raw"], RED)

        slots = extract_image_slots(url_only)
        self.assertEqual(slots, [{"url": "https://cdn.example/a.png", "raw": None}])

        slots = extract_image_slots(mixed)
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0]["raw"], RED)
        self.assertIsNone(slots[0]["url"])
        self.assertEqual(slots[1]["url"], "https://cdn.example/b.png")
        self.assertIsNone(slots[1]["raw"])
        self.assertEqual(slots[2]["url"], "https://cdn.example/c.png")
        self.assertEqual(slots[2]["raw"], BLUE)

    def test_nested_task_envelope_and_data_uri(self):
        payload = {
            "id": "task-9",
            "status": "succeeded",
            "data": {
                "data": [{"url": "data:image/png;base64," + RED_B64}],
            },
        }
        slots = extract_image_slots(payload)
        self.assertEqual(len(slots), 1)
        self.assertIsNone(slots[0]["url"])
        self.assertEqual(slots[0]["raw"], RED)

    def test_async_content_url_is_a_downloadable_slot(self):
        direct = {
            "task_id": "task-c",
            "status": "succeeded",
            "content": {"url": "https://ai.example/v1/images/content/abc"},
        }
        nested = {"data": {"content": {"url": "https://cdn.example/nested.png"}}}
        bare = {"status": "succeeded", "content": "https://cdn.example/plain.png"}

        slots = extract_image_slots(direct)
        self.assertEqual(
            slots,
            [{"url": "https://ai.example/v1/images/content/abc", "raw": None}],
        )
        self.assertEqual(extract_image_slots(nested)[0]["url"], "https://cdn.example/nested.png")
        self.assertEqual(extract_image_slots(bare)[0]["url"], "https://cdn.example/plain.png")

        # Sync data[] still works beside an async content.url.
        mixed = {
            "data": [{"b64_json": RED_B64}],
            "content": {"url": "https://cdn.example/also.png"},
        }
        slots = extract_image_slots(mixed)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]["raw"], RED)
        self.assertEqual(slots[1]["url"], "https://cdn.example/also.png")

    def test_short_token_is_not_an_image_or_a_huge_task_id(self):
        self.assertEqual(extract_image_slots({"data": [{"b64_json": "aGVsbG8"}]}), [])
        from xhcy_client import extract_task_id

        self.assertEqual(extract_task_id({"data": RED_B64}), "")
        self.assertEqual(extract_task_id({"id": "task-1", "data": []}), "task-1")

    def test_banana_schema_omits_quality_and_keeps_reply_type(self):
        banana = XHCYNanoBanana.INPUT_TYPES()["required"]
        gpt = XHCYGPTImage25.INPUT_TYPES()["required"]
        self.assertNotIn("quality", banana)
        self.assertIn("reply_type", banana)
        self.assertIn("quality", gpt)

    def test_quality_predicates(self):
        for name in (
            "nano-banana-2",
            "nano-banana-pro",
            "gemini-nano-banana-2.1",
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image-preview",
        ):
            self.assertTrue(model_rejects_quality(name), name)
            self.assertFalse(model_supports_quality(name), name)
        self.assertTrue(model_supports_quality("gpt-image-2.6"))
        self.assertTrue(model_supports_quality("gpt-image-2.5-flare"))
        self.assertFalse(model_supports_quality("gpt-image-2"))
        self.assertFalse(model_supports_quality("gpt-image-2-vip"))


class SubmitContractTests(unittest.TestCase):
    def _capture(self, payload):
        client = XHCYClient("sk-test", "https://example.invalid")
        captured = {}

        def fake_request_json(method, path, context, retry=False, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["json"] = kwargs.get("json")
            return {"id": "task-1", "status": "queued"}

        client._request_json = fake_request_json
        client.submit_image(payload)
        return captured

    def test_async_body_strips_response_format_and_banana_quality(self):
        for model in (
            "nano-banana-2",
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image-preview",
        ):
            captured = self._capture(
                {
                    "model": model,
                    "prompt": "a cat",
                    "n": 1,
                    "response_format": "url",
                    "quality": "high",
                }
            )
            self.assertEqual(captured["method"], "POST")
            self.assertEqual(captured["path"], "/v1/images/generations")
            self.assertNotIn("?", captured["path"])
            self.assertIs(captured["json"]["async"], True)
            self.assertNotIn("response_format", captured["json"])
            self.assertNotIn("quality", captured["json"])

    def test_gpt_image_26_keeps_quality_but_not_response_format(self):
        captured = self._capture(
            {
                "model": "gpt-image-2.6",
                "prompt": "a cat",
                "quality": "high",
                "response_format": "url",
                "async": False,
            }
        )
        self.assertEqual(captured["json"]["quality"], "high")
        self.assertIs(captured["json"]["async"], True)
        self.assertNotIn("response_format", captured["json"])
        self.assertEqual(captured["path"], "/v1/images/generations")
        self.assertNotIn("?", captured["path"])

    def test_auto_quality_is_omitted(self):
        captured = self._capture(
            {"model": "gpt-image-2.6", "prompt": "a cat", "quality": "auto"}
        )
        self.assertNotIn("quality", captured["json"])


class _GeminiPreview(XHCYImageBase):
    """Stand-in for a banana-style id that is not on the shipping dropdown."""

    VARIANT_MODELS = ["gemini-3.1-flash-image-preview"]
    QUALITIES = ["auto", "low", "medium", "high"]
    ASPECT_PARAM_MODELS = ["gemini-3.1-flash-image-preview"]
    SIZE_FIELD = "image_size"
    DEFAULT_RESOLUTION = "1K"
    OUTPUT_PREFIX = "gemini_preview"


class _Gpt26(XHCYImageBase):
    VARIANT_MODELS = ["gpt-image-2.6"]
    QUALITIES = ["auto", "low", "medium", "high"]
    SIZE_MAP = {("1:1", "1k"): "1024x1024"}
    RESOLUTION_LIMITS = {"gpt-image-2.6": ["1k"]}
    DEFAULT_RESOLUTION = "1k"
    OUTPUT_PREFIX = "gpt26"


class GeneratePathTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._output = xhcy_image_base._output_dir
        self._sleep = xhcy_image_base.sleep_interruptible
        xhcy_image_base._output_dir = lambda: self._tmpdir.name
        xhcy_image_base.sleep_interruptible = lambda _seconds: None
        self.calls: list[tuple] = []

    def tearDown(self):
        xhcy_image_base._output_dir = self._output
        xhcy_image_base.sleep_interruptible = self._sleep
        self._tmpdir.cleanup()

    def _run(self, node, responses, downloads=None, **kwargs):
        downloads = downloads or {}
        queue = list(responses)

        def request(session, method, url, **req_kwargs):
            body = req_kwargs.get("json")
            self.calls.append((method, url, body))
            if method == "GET" and url in downloads:
                return _Resp(content=downloads[url])
            if method == "GET" and "/v1/images/tasks/" not in url:
                return _Resp(content=downloads.get(url, b""))
            if not queue:
                raise AssertionError(f"unexpected {method} {url}")
            return _Resp(queue.pop(0))

        params = dict(
            prompt="a red square",
            api_key="sk-test",
            max_poll_attempts=3,
            poll_interval=1,
            base_url="https://example.invalid",
        )
        params.update(kwargs)
        with mock.patch.object(requests.Session, "request", request):
            return node.generate(**params)

    def test_banana_b64_json_becomes_image_tensor_without_quality_or_format(self):
        result = self._run(
            XHCYNanoBanana(),
            responses=[
                {"id": "task-b64", "status": "queued"},
                {
                    "id": "task-b64",
                    "status": "succeeded",
                    "data": [{"b64_json": RED_B64}],
                },
            ],
            model="nano-banana-2",
            aspect_ratio="1:1",
            image_size="1K",
            quality="high",
        )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))
        self.assertGreater(float(result[0][0, 0, 0, 0]), 0.9)
        self.assertIn("task-b64", result[1])
        post = self.calls[0]
        self.assertEqual(post[0], "POST")
        self.assertTrue(post[1].endswith("/v1/images/generations"), post[1])
        self.assertNotIn("?", post[1])
        self.assertNotIn("response_format", post[2])
        self.assertNotIn("quality", post[2])
        self.assertIs(post[2]["async"], True)
        self.assertEqual(post[2]["model"], "nano-banana-2")
        self.assertEqual(self.calls[1][0], "GET")
        self.assertTrue(self.calls[1][1].endswith("/v1/images/tasks/task-b64"))
        self.assertTrue(os.path.isfile(result[2].splitlines()[0]))

    def test_url_item_is_downloaded(self):
        url = "https://cdn.example/red.png"
        result = self._run(
            XHCYNanoBanana(),
            responses=[{"data": [{"url": url}], "status": "succeeded"}],
            downloads={url: RED},
            model="gemini-2.5-flash-image",
            aspect_ratio="1:1",
            image_size="1K",
            quality="high",
        )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][1], url)
        self.assertNotIn("quality", self.calls[0][2])
        self.assertNotIn("response_format", self.calls[0][2])

    def test_mixed_data_items_both_become_images(self):
        url = "https://cdn.example/blue.png"
        result = self._run(
            XHCYNanoBanana(),
            responses=[
                {
                    "status": "succeeded",
                    "data": [
                        {"b64_json": RED_B64},
                        {"url": url},
                    ],
                }
            ],
            downloads={url: BLUE},
            model="nano-banana-2",
            aspect_ratio="1:1",
            image_size="1K",
        )
        self.assertEqual(tuple(result[0].shape), (2, 8, 8, 3))
        self.assertGreater(float(result[0][0, 0, 0, 0]), 0.9)
        self.assertGreater(float(result[0][1, 0, 0, 2]), 0.9)
        self.assertEqual(self.calls[-1][1], url)

    def test_url_download_failure_falls_back_to_b64(self):
        url = "https://cdn.example/missing.png"

        def request(session, method, url_called, **req_kwargs):
            self.calls.append((method, url_called, req_kwargs.get("json")))
            if method == "GET" and url_called == url:
                return _Resp({"error": {"message": "gone"}}, status_code=404)
            return _Resp(
                {
                    "status": "succeeded",
                    "data": [{"url": url, "b64_json": RED_B64}],
                }
            )

        with mock.patch.object(requests.Session, "request", request):
            result = XHCYNanoBanana().generate(
                prompt="a red square",
                model="nano-banana-2",
                api_key="sk-test",
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://example.invalid",
                aspect_ratio="1:1",
                image_size="1K",
            )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))

    def test_poll_timeout_and_transient_retry(self):
        responses = [
            {"id": "task-slow", "status": "queued"},
            None,  # first poll raises via status
        ]

        def request(session, method, url, **req_kwargs):
            if method == "POST":
                return _Resp(responses[0])
            # Two transient failures, then still queued, attempts=3 so this times out.
            request.n += 1
            if request.n < 3:
                return _Resp({"error": {"message": "busy"}}, status_code=503)
            return _Resp({"id": "task-slow", "status": "running"})

        request.n = 0
        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                XHCYNanoBanana().generate(
                    prompt="a red square",
                    model="nano-banana-2",
                    api_key="sk-test",
                    max_poll_attempts=3,
                    poll_interval=1,
                    base_url="https://example.invalid",
                    aspect_ratio="1:1",
                    image_size="1K",
                )
        message = str(caught.exception)
        self.assertIn("等待超时", message)
        self.assertIn("失败", message)
        self.assertNotIn("生成成功", message)
        self.assertEqual(request.n, 3)

    def test_terminal_failure_is_not_polled_forever(self):
        def request(session, method, url, **req_kwargs):
            if method == "POST":
                return _Resp({"id": "task-bad", "status": "queued"})
            return _Resp({"id": "task-bad", "status": "failed", "error": "upstream rejected"})

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                XHCYNanoBanana().generate(
                    prompt="a red square",
                    model="nano-banana-2",
                    api_key="sk-test",
                    max_poll_attempts=5,
                    poll_interval=1,
                    base_url="https://example.invalid",
                    aspect_ratio="1:1",
                    image_size="1K",
                )
        self.assertIn("upstream rejected", str(caught.exception))

    def test_platform_timeout_status_fails_without_exhausting_polls(self):
        for status in ("timeout", "timed_out"):
            with self.subTest(status=status):
                polls = []

                def request(session, method, url, _polls=polls, _status=status, **req_kwargs):
                    if method == "POST":
                        return _Resp({"task_id": "task-timeout", "status": "queued"})
                    _polls.append(url)
                    return _Resp(
                        {
                            "task_id": "task-timeout",
                            "status": _status,
                            "failure_reason": "gateway deadline",
                        }
                    )

                with mock.patch.object(requests.Session, "request", request):
                    with self.assertRaises(XHCYError) as caught:
                        XHCYNanoBanana().generate(
                            prompt="a red square",
                            model="nano-banana-2",
                            api_key="sk-test",
                            max_poll_attempts=8,
                            poll_interval=1,
                            base_url="https://example.invalid",
                            aspect_ratio="1:1",
                            image_size="1K",
                        )
                message = str(caught.exception)
                self.assertIn("生成失败", message)
                self.assertIn("gateway deadline", message)
                self.assertNotIn("等待超时", message)
                self.assertEqual(len(polls), 1, polls)

    def test_content_url_is_downloaded_into_an_image(self):
        url = "https://example.invalid/v1/images/tasks/task-c/content"
        result = self._run(
            XHCYNanoBanana(),
            responses=[
                {"task_id": "task-c", "status": "queued"},
                {
                    "task_id": "task-c",
                    "status": "succeeded",
                    "content": {"url": url},
                },
            ],
            downloads={url: RED},
            model="nano-banana-2",
            aspect_ratio="1:1",
            image_size="1K",
        )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))
        self.assertGreater(float(result[0][0, 0, 0, 0]), 0.9)
        self.assertIs(self.calls[0][2]["async"], True)
        self.assertNotIn("?", self.calls[0][1])
        self.assertEqual(self.calls[1][0], "GET")
        self.assertTrue(self.calls[1][1].endswith("/v1/images/tasks/task-c"))
        self.assertEqual(self.calls[2][1], url)
        self.assertIn("task-c", result[1])

    def test_same_host_content_download_sends_bearer(self):
        url = "https://example.invalid/v1/images/tasks/task-auth/content"
        seen = {}

        def request(session, method, url_called, **req_kwargs):
            if method == "POST":
                return _Resp({"task_id": "task-auth", "status": "queued"})
            if "/v1/images/tasks/" in url_called and url_called != url:
                return _Resp(
                    {"task_id": "task-auth", "status": "succeeded", "content": {"url": url}}
                )
            seen["headers"] = req_kwargs.get("headers")
            seen["url"] = url_called
            return _Resp(content=RED)

        with mock.patch.object(requests.Session, "request", request):
            result = XHCYNanoBanana().generate(
                prompt="a red square",
                model="nano-banana-2",
                api_key="sk-test",
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://example.invalid",
                aspect_ratio="1:1",
                image_size="1K",
            )
        self.assertEqual(seen["url"], url)
        self.assertEqual(seen["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))

    def test_async_generation_disabled_is_a_hard_error(self):
        posts = []

        def request(session, method, url, **req_kwargs):
            posts.append((method, url, req_kwargs.get("json")))
            return _Resp(
                {"error": {"code": "async_generation_disabled", "message": "async off"}},
                status_code=400,
            )

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                XHCYNanoBanana().generate(
                    prompt="a red square",
                    model="nano-banana-2",
                    api_key="sk-test",
                    max_poll_attempts=3,
                    poll_interval=1,
                    base_url="https://example.invalid",
                    aspect_ratio="1:1",
                    image_size="1K",
                )
        message = str(caught.exception)
        self.assertIn("async_generation_disabled", message)
        self.assertIn("ASYNC_GENERATION_ENABLED", message)
        self.assertEqual(len(posts), 1)
        self.assertIs(posts[0][2]["async"], True)
        self.assertNotIn("?", posts[0][1])

    def test_terminal_success_without_image_is_a_failure(self):
        def request(session, method, url, **req_kwargs):
            if method == "POST":
                return _Resp({"task_id": "task-empty", "status": "queued"})
            return _Resp({"task_id": "task-empty", "status": "succeeded"})

        with mock.patch.object(requests.Session, "request", request):
            with self.assertRaises(XHCYError) as caught:
                XHCYNanoBanana().generate(
                    prompt="a red square",
                    model="nano-banana-2",
                    api_key="sk-test",
                    max_poll_attempts=3,
                    poll_interval=1,
                    base_url="https://example.invalid",
                    aspect_ratio="1:1",
                    image_size="1K",
                )
        self.assertIn("失败", str(caught.exception))
        self.assertIn("没有", str(caught.exception))

    def test_gpt_image_25_still_sends_quality_gpt26_too_preview_does_not(self):
        done = {"status": "succeeded", "data": [{"b64_json": RED_B64}]}
        gpt = self._run(
            XHCYGPTImage25(),
            responses=[done],
            model="gpt-image-2.5-flare",
            aspect_ratio="1:1",
            resolution="1k",
            quality="high",
        )
        self.assertEqual(self.calls[0][2]["quality"], "high")
        self.assertNotIn("response_format", self.calls[0][2])
        self.assertEqual(tuple(gpt[0].shape), (1, 8, 8, 3))

        self.calls.clear()
        self._run(
            XHCYGPTImage25(),
            responses=[done],
            model="gpt-image-2.5-flare",
            aspect_ratio="1:1",
            resolution="1k",
            quality="auto",
        )
        self.assertNotIn("quality", self.calls[0][2])

        self.calls.clear()
        self._run(
            _Gpt26(),
            responses=[done],
            model="gpt-image-2.6",
            aspect_ratio="1:1",
            resolution="1k",
            quality="medium",
        )
        self.assertEqual(self.calls[0][2]["quality"], "medium")
        self.assertIs(self.calls[0][2]["async"], True)
        self.assertNotIn("?", self.calls[0][1])

        self.calls.clear()
        self._run(
            _GeminiPreview(),
            responses=[done],
            model="gemini-3.1-flash-image-preview",
            aspect_ratio="1:1",
            image_size="1K",
            quality="high",
        )
        self.assertNotIn("quality", self.calls[0][2])
        self.assertNotIn("response_format", self.calls[0][2])


class GatewayReachabilityTests(unittest.TestCase):
    def test_embedded_image_is_used_without_calling_another_host(self):
        foreign = "https://cdn.example/red.png"
        calls = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self._output = xhcy_image_base._output_dir
        xhcy_image_base._output_dir = lambda: tmp.name
        self.addCleanup(lambda: setattr(xhcy_image_base, "_output_dir", self._output))

        def request(session, method, url, **kwargs):
            calls.append((method, url))
            if method == "POST":
                return _Resp(
                    {
                        "id": "task-inline",
                        "status": "succeeded",
                        "data": [{"url": foreign, "b64_json": RED_B64}],
                    }
                )
            raise AssertionError(url)

        with mock.patch.object(requests.Session, "request", request):
            result = XHCYNanoBanana().generate(
                prompt="a red square",
                model="nano-banana-2",
                api_key="sk-test",
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://example.invalid",
                aspect_ratio="1:1",
                image_size="1K",
            )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))
        self.assertEqual(calls, [("POST", "https://example.invalid/v1/images/generations")])

    def test_foreign_result_url_asks_the_gateway_first(self):
        foreign = "https://cdn.example/red.png"
        gateway = "https://example.invalid/v1/images/tasks/task-gw/content"
        seen = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self._output = xhcy_image_base._output_dir
        xhcy_image_base._output_dir = lambda: tmp.name
        self.addCleanup(lambda: setattr(xhcy_image_base, "_output_dir", self._output))

        def request(session, method, url, **kwargs):
            seen.append(url)
            if method == "POST":
                return _Resp(
                    {
                        "id": "task-gw",
                        "status": "succeeded",
                        "data": [{"url": foreign}],
                    }
                )
            if url == gateway:
                return _Resp(content=RED)
            raise AssertionError(url)

        with mock.patch.object(requests.Session, "request", request):
            result = XHCYNanoBanana().generate(
                prompt="a red square",
                model="nano-banana-2",
                api_key="sk-test",
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://example.invalid",
                aspect_ratio="1:1",
                image_size="1K",
            )
        self.assertEqual(tuple(result[0].shape), (1, 8, 8, 3))
        self.assertIn(gateway, seen)
        self.assertNotIn(foreign, seen)
        self.assertEqual(seen[-1], gateway)

    def test_connect_failure_is_retried_and_read_timeout_is_not(self):
        import xhcy_client

        client = XHCYClient("sk-test", "https://example.invalid")
        calls = {"n": 0}

        def handshake(session, method, url, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.ConnectTimeout("handshake")
            return _Resp({"ok": True})

        with mock.patch.object(requests.Session, "request", handshake), mock.patch.object(
            xhcy_client, "_CONNECT_RETRY_DELAYS", (0, 0)
        ), mock.patch.object(xhcy_client, "_environ_proxies", lambda _url: False):
            response = client._send("POST", "/v1/images/generations", "图像生成请求")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(response.json()["ok"], True)

        calls["n"] = 0

        def read_timeout(session, method, url, **kwargs):
            calls["n"] += 1
            raise requests.ReadTimeout("read")

        with mock.patch.object(requests.Session, "request", read_timeout):
            with self.assertRaises(XHCYError) as caught:
                client._send("POST", "/v1/images/generations", "图像生成请求")
        self.assertEqual(calls["n"], 1)
        self.assertIn("等待网关响应超时", str(caught.exception))
        self.assertNotIn(xhcy_client.UPLOAD_WRITE_TIMEOUT_MARK, str(caught.exception))

        calls["n"] = 0

        def aborted(session, method, url, **kwargs):
            calls["n"] += 1
            raise requests.ConnectionError("Connection aborted.")

        with mock.patch.object(requests.Session, "request", aborted):
            with self.assertRaises(XHCYError) as aborted_error:
                client._send("POST", "/v1/images/generations", "图像生成请求")
        self.assertEqual(calls["n"], 1)
        self.assertIn("连接中断", str(aborted_error.exception))
        self.assertNotIn("握手未完成", str(aborted_error.exception))
        self.assertNotIn(xhcy_client.UPLOAD_WRITE_TIMEOUT_MARK, str(aborted_error.exception))

    def test_stalled_address_does_not_block_a_working_one(self):
        import socket
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        import xhcy_client

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        started = time.monotonic()
        sock = xhcy_client.connect_candidates(
            [
                (socket.AF_INET, ("192.0.2.1", 81)),
                (socket.AF_INET, ("127.0.0.1", port)),
            ],
            timeout=3,
        )
        sock.close()
        self.assertLess(time.monotonic() - started, 1.5)

        called = {"yes": False}
        real = xhcy_client.connect_candidates

        def mark(*args, **kwargs):
            called["yes"] = True
            return real(*args, **kwargs)

        session = xhcy_client._new_session(False)
        with mock.patch.object(xhcy_client, "connect_candidates", mark):
            response = session.get("http://127.0.0.1:%d/v1/models" % port, timeout=(3, 3))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(called["yes"])

    def test_write_timeout_is_not_retried_as_a_handshake(self):
        import urllib3.exceptions

        import xhcy_client

        client = XHCYClient("sk-test", "https://example.invalid")
        calls = []

        def write_timeout(session, method, url, **kwargs):
            calls.append(session)
            timeout = TimeoutError("The write operation timed out")
            protocol = urllib3.exceptions.ProtocolError("Connection aborted.", timeout)
            try:
                raise protocol
            except urllib3.exceptions.ProtocolError as protocol_error:
                raise requests.ConnectionError(protocol_error)

        with mock.patch.object(requests.Session, "request", write_timeout), mock.patch.object(
            xhcy_client, "_environ_proxies", lambda _url: True
        ):
            with self.assertRaises(XHCYError) as caught:
                client._send("POST", "/v1/video/generations", "视频生成请求")
        # One direct attempt. Not the handshake retries, and not the proxy session.
        self.assertEqual(calls, [client._direct])
        message = str(caught.exception)
        self.assertIn(xhcy_client.UPLOAD_WRITE_TIMEOUT_MARK, message)
        self.assertIn("参考视频", message)
        self.assertIn("并不能说明站点已经宕掉", message)
        self.assertIn("不要立刻再次提交", message)
        self.assertNotIn("握手未完成", message)
        self.assertNotIn("等待网关响应超时", message)

    def test_exhausted_handshake_is_not_described_as_an_upload(self):
        import xhcy_client

        client = XHCYClient("sk-test", "https://example.invalid")
        calls = {"n": 0}

        def handshake(session, method, url, **kwargs):
            calls["n"] += 1
            raise requests.ConnectTimeout("timed out")

        with mock.patch.object(requests.Session, "request", handshake), mock.patch.object(
            xhcy_client, "_CONNECT_RETRY_DELAYS", (0, 0)
        ), mock.patch.object(xhcy_client, "_environ_proxies", lambda _url: False):
            with self.assertRaises(XHCYError) as caught:
                client._send("POST", "/v1/video/generations", "视频生成请求")
        self.assertEqual(calls["n"], 3)
        message = str(caught.exception)
        self.assertIn("握手未完成", message)
        self.assertNotIn(xhcy_client.UPLOAD_WRITE_TIMEOUT_MARK, message)
        self.assertNotIn("等待网关响应超时", message)

    def test_request_body_uses_read_timeout_after_handshake(self):
        """A finished TLS handshake must not keep the connect timeout for sendall."""
        import shutil
        import socket
        import ssl
        import subprocess
        import tempfile
        import threading
        import warnings

        import urllib3.exceptions

        import xhcy_client

        if shutil.which("openssl") is None:
            self.skipTest("openssl is required to mint a loopback certificate")

        observed = []
        real_sendall = ssl.SSLSocket.sendall

        def spy_sendall(sock, data, *args, **kwargs):
            if isinstance(data, (bytes, bytearray)) and len(data) > 4096:
                observed.append(sock.gettimeout())
            return real_sendall(sock, data, *args, **kwargs)

        def serve(port_holder, pem_path):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(5)
            port_holder.append(server.getsockname()[1])
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(pem_path)
            tls = None
            try:
                raw, _addr = server.accept()
            except socket.timeout:
                server.close()
                return
            try:
                tls = context.wrap_socket(raw, server_side=True)
                tls.settimeout(5)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    piece = tls.recv(16384)
                    if not piece:
                        break
                    buf += piece
                head, _, rest = buf.partition(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1].strip())
                while len(rest) < length:
                    piece = tls.recv(16384)
                    if not piece:
                        break
                    rest += piece
                payload = b'{"ok":true}'
                tls.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s"
                    % (len(payload), payload)
                )
            finally:
                for held in (tls, raw, server):
                    if held is None:
                        continue
                    try:
                        held.close()
                    except OSError:
                        pass

        with tempfile.TemporaryDirectory() as directory:
            pem_path = os.path.join(directory, "localhost.pem")
            subprocess.check_call(
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:2048",
                    "-keyout", pem_path, "-out", pem_path,
                    "-days", "1", "-nodes", "-subj", "/CN=127.0.0.1",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            port_holder = []
            thread = threading.Thread(target=serve, args=(port_holder, pem_path), daemon=True)
            thread.start()
            while not port_holder and thread.is_alive():
                thread.join(0.01)
            self.assertTrue(port_holder)
            port = port_holder[0]
            body = b'{"content":"%s"}' % (b"v" * 80000)
            ssl.SSLSocket.sendall = spy_sendall
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                    session = xhcy_client._new_session(False)
                    response = session.post(
                        "https://127.0.0.1:%d/v1/video/generations" % port,
                        data=body,
                        timeout=(0.5, 4.25),
                        verify=False,
                    )
                    self.assertEqual(response.status_code, 200)
                    response.close()
                    session.close()
                    self.assertTrue(observed, "request body was not written")
                    for value in observed:
                        self.assertIsNotNone(value)
                        self.assertGreater(float(value), 0.5)
                        self.assertAlmostEqual(float(value), 4.25, places=2)
                    thread.join(2)

                    observed.clear()
                    # The production client always passes (_CONNECT_TIMEOUT, _READ_TIMEOUT).
                    # The body write must use the read half, not the 10s connect half.
                    port_holder = []
                    thread = threading.Thread(
                        target=serve, args=(port_holder, pem_path), daemon=True
                    )
                    thread.start()
                    while not port_holder and thread.is_alive():
                        thread.join(0.01)
                    self.assertTrue(port_holder)
                    client = XHCYClient("sk-test", "https://127.0.0.1:%d" % port_holder[0])
                    response = client._send(
                        "POST",
                        "/v1/video/generations",
                        "视频生成请求",
                        data=body,
                        verify=False,
                    )
                    self.assertEqual(response.status_code, 200)
                    response.close()
                    client._direct.close()
                    self.assertTrue(observed, "client request body was not written")
                    for value in observed:
                        self.assertGreater(float(value), float(xhcy_client._CONNECT_TIMEOUT))
                        self.assertAlmostEqual(
                            float(value), float(xhcy_client._READ_TIMEOUT), places=2
                        )
            finally:
                ssl.SSLSocket.sendall = real_sendall
            thread.join(2)

    def test_video_and_enhance_urls_stay_on_the_gateway_before_any_other_host(self):
        client = XHCYClient("sk-test", "https://example.invalid")
        self.assertEqual(
            client.artifact_urls("https://cdn.example/clip.mp4", "task-v", "video"),
            [
                "https://example.invalid/v1/video/generations/task-v/content",
                "https://cdn.example/clip.mp4",
            ],
        )
        self.assertEqual(
            client.artifact_urls(
                "https://example.invalid/v1/video/enhance/task-e/content",
                "task-e",
                "enhance",
            ),
            ["https://example.invalid/v1/video/enhance/task-e/content"],
        )


if __name__ == "__main__":
    unittest.main()
