"""GET vs POST header construction.

The gateway unmarshals a body whenever Content-Type is application/json.
These tests stub HTTP and prepare requests locally. They do not open a
connection and they do not use a real key.
"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from xhcy_client import XHCYClient


def _content_type(headers) -> str:
    if not headers:
        return ""
    for key, value in headers.items():
        if str(key).lower() == "content-type":
            return str(value)
    return ""


class _Resp:
    def __init__(self, payload=None, status_code=200, content=b"png-bytes"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.headers = {}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1024):
        yield self.content

    def close(self):
        return None


class RequestHeaderTests(unittest.TestCase):
    def setUp(self):
        self.client = XHCYClient("sk-test", "https://example.invalid")
        self.seen = []

        def request(session, method, url, **kwargs):
            self.seen.append((method, url, kwargs))
            if kwargs.get("stream"):
                return _Resp(content=b"png-bytes")
            return _Resp({"id": "task-1", "status": "queued"})

        patch = mock.patch.object(requests.Session, "request", request)
        patch.start()
        self.addCleanup(patch.stop)

    def _call(self, index=0):
        return self.seen[index]

    def _assert_json_get(self, index, url_suffix):
        method, url, kwargs = self._call(index)
        headers = kwargs.get("headers") or {}
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith(url_suffix), url)
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test")
        self.assertEqual(headers.get("Accept"), "application/json")
        self.assertEqual(_content_type(headers), "")
        self.assertIsNone(kwargs.get("json"))
        self.assertIsNone(kwargs.get("data"))
        prepared = requests.Request(method, url, headers=headers).prepare()
        self.assertIsNone(prepared.body)
        self.assertEqual(_content_type(prepared.headers), "")
        self.assertEqual(prepared.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(prepared.headers["Accept"], "application/json")

    def test_get_json_omits_json_content_type(self):
        self.client.get_json("/v1/images/tasks/task-1", "图像结果查询")
        self._assert_json_get(0, "/v1/images/tasks/task-1")

    def test_poll_image_and_poll_video_are_bodyless_gets(self):
        self.client.poll_image("task-img")
        self.client.poll_video("task-vid")
        self.client.poll_video_enhancement("task-enh")
        self._assert_json_get(0, "/v1/images/tasks/task-img")
        self._assert_json_get(1, "/v1/video/generations/task-vid")
        self._assert_json_get(2, "/v1/video/enhance/task-enh")

    def test_post_json_sends_content_type_with_a_json_body(self):
        payload = {"model": "nano-banana-2", "prompt": "a cat", "async": True}
        self.client.post_json("/v1/images/generations", payload, "图像生成请求")
        method, url, kwargs = self._call(0)
        headers = kwargs.get("headers") or {}
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/v1/images/generations"), url)
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test")
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertEqual(kwargs.get("json"), payload)
        prepared = requests.Request(
            method, url, headers=headers, json=kwargs.get("json")
        ).prepare()
        self.assertEqual(prepared.headers["Content-Type"], "application/json")
        self.assertEqual(prepared.headers["Authorization"], "Bearer sk-test")
        self.assertTrue(prepared.body)

    def test_header_helper_matches_method_and_body(self):
        get_headers = self.client._headers("GET", json_body=False)
        post_headers = self.client._headers("POST", json_body=True)
        put_headers = self.client._headers("PUT", json_body=True)
        patch_headers = self.client._headers("PATCH", json_body=True)
        empty_post = self.client._headers("POST", json_body=False)
        get_even_if_flagged = self.client._headers("GET", json_body=True)

        for headers in (get_headers, empty_post, get_even_if_flagged):
            self.assertEqual(headers["Authorization"], "Bearer sk-test")
            self.assertEqual(headers["Accept"], "application/json")
            self.assertNotIn("Content-Type", headers)

        for headers in (post_headers, put_headers, patch_headers):
            self.assertEqual(headers["Authorization"], "Bearer sk-test")
            self.assertEqual(headers["Content-Type"], "application/json")

    def test_send_strips_content_type_when_there_is_no_body(self):
        supplied = {
            "Authorization": "Bearer sk-test",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.client._send("GET", "/v1/images/tasks/task-1", "图像结果查询", headers=supplied)
        self.client._send("POST", "/v1/images/generations", "图像生成请求", headers=dict(supplied))
        self.client._send(
            "PUT",
            "/v1/images/generations",
            "图像生成请求",
            headers=dict(supplied),
            data=b"",
        )
        for index in (0, 1, 2):
            method, _url, kwargs = self._call(index)
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
            self.assertEqual(kwargs["headers"]["Accept"], "application/json")
            self.assertEqual(_content_type(kwargs["headers"]), "", method)
        # The caller's dict is not rewritten in place.
        self.assertEqual(supplied["Content-Type"], "application/json")

    def test_send_keeps_content_type_on_post_and_put_with_a_json_body(self):
        supplied = {
            "Authorization": "Bearer sk-test",
            "Content-Type": "application/json",
        }
        self.client._send(
            "POST",
            "/v1/images/generations",
            "图像生成请求",
            headers=dict(supplied),
            json={"prompt": "a cat"},
        )
        self.client._send(
            "PUT",
            "/v1/images/generations",
            "图像生成请求",
            headers={"Authorization": "Bearer sk-test", "content-type": "application/json"},
            json={"prompt": "a cat"},
        )
        post_headers = self._call(0)[2]["headers"]
        put_headers = self._call(1)[2]["headers"]
        self.assertEqual(post_headers["Content-Type"], "application/json")
        self.assertEqual(put_headers["content-type"], "application/json")
        self.assertEqual(post_headers["Authorization"], "Bearer sk-test")
        self.assertEqual(put_headers["Authorization"], "Bearer sk-test")

    def test_gateway_download_keeps_authorization_without_json_content_type(self):
        data = self.client.download("https://example.invalid/v1/images/tasks/task-1/content")
        method, url, kwargs = self._call(0)
        headers = kwargs.get("headers") or {}
        self.assertEqual(data, b"png-bytes")
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://example.invalid/v1/images/tasks/task-1/content")
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test")
        self.assertEqual(_content_type(headers), "")
        self.assertNotIn("Accept", headers)
        self.assertIsNone(kwargs.get("json"))
        prepared = requests.Request(method, url, headers=headers).prepare()
        self.assertIsNone(prepared.body)
        self.assertEqual(_content_type(prepared.headers), "")


if __name__ == "__main__":
    unittest.main()
