import base64
import hashlib
import importlib.util
import io
import os
import sys
import unittest

import torch
from PIL import Image


COMFY_ROOT = os.environ.get("COMFYUI_ROOT", r"F:\Program Files\ComfyUI-xinghuo\ComfyUI")
NODE_PATH = os.path.join(COMFY_ROOT, "custom_nodes", "comfyui-xinghuo-nano-banana", "nodes.py")
if COMFY_ROOT not in sys.path:
    sys.path.insert(0, COMFY_ROOT)
spec = importlib.util.spec_from_file_location("nano_banana_nodes", NODE_PATH)
nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nodes)


def png_data_uri():
    image = Image.new("RGB", (8, 8), "red")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def secure_draw_client(origin="https://service.invalid"):
    routes = nodes._service_routes()
    return nodes.SecureDrawClient(origin, routes["submit"], routes["result"])


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class NanoBananaNodeTests(unittest.TestCase):
    def setUp(self):
        self.node = nodes.ComfyuiXinghuoNanoBanana()
        self.original_request = nodes.requests.request
        self.original_post = nodes.requests.post
        self.original_config = nodes._provider_config
        self.original_balance = nodes.query_account_balance
        self.original_sleep = nodes._interruptible_sleep
        nodes._interruptible_sleep = lambda _seconds: None
        nodes._provider_config = lambda: {"base_url": "https://service.invalid", "api_key": "key", "profiles": {"标准": "private-model"}, "extended_ratio_profiles": []}
        nodes.requests.post = lambda *_args, **_kwargs: FakeResponse(payload={"code": 0, "data": {"credits": 999999}})

    def tearDown(self):
        nodes.requests.request = self.original_request
        nodes.requests.post = self.original_post
        nodes._provider_config = self.original_config
        nodes.query_account_balance = self.original_balance
        nodes._interruptible_sleep = self.original_sleep

    def test_sync_request_uses_only_documented_fields_and_data_uri(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(payload={"code": 0, "data": {"id": "sync-1", "status": "succeeded", "results": [{"url": png_data_uri()}]}})

        nodes.requests.request = request
        result = self.node.generate("draw", "nano-banana-2", "key", "21:9", "4K", "async", 2, 1)
        self.assertEqual(result[0].shape, (1, 8, 8, 3))
        self.assertIn("sync-1", result[1])
        self.assertNotIn("\u8d26\u6237\u4f59\u989d", result[1])
        self.assertEqual(calls[0][0:2], ("POST", "https://service.invalid/v1/draw/nano-banana"))
        self.assertEqual(set(calls[0][2]["json"]), {"model", "prompt", "urls", "aspectRatio", "imageSize", "webHook"})
        self.assertEqual(calls[0][2]["json"]["aspectRatio"], "21:9")
        self.assertNotIn("output_compression", calls[0][2]["json"])

    def test_reference_image_is_sent_as_valid_png_data_uri(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(payload={"code": 0, "data": {
                "id": "image-1",
                "status": "succeeded",
                "results": [{"url": png_data_uri()}],
            }})

        nodes.requests.request = request
        result = self.node.generate(
            "draw",
            "nano-banana-2",
            "key",
            "1:1",
            "1K",
            "async",
            2,
            1,
            image1=torch.rand(1, 8, 8, 3),
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["success"])
        payload = calls[0][2]["json"]
        encoded = payload["urls"][0]
        self.assertTrue(encoded.startswith("data:image/png;base64,"))
        raw = base64.b64decode(encoded.split(",", 1)[1], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (8, 8))

    def test_shared_client_keeps_draw_endpoints_stable(self):
        client = secure_draw_client("https://service.invalid/")
        self.assertEqual(client.generation_url, "https://service.invalid/v1/draw/nano-banana")
        self.assertEqual(client.result_url, "https://service.invalid/v1/draw/result")

    def test_default_service_origin_is_authenticated_encrypted(self):
        origin = nodes.load_locked_service_origin()
        source_path = os.path.join(os.path.dirname(NODE_PATH), "secure_config.py")
        with open(source_path, "rb") as handle:
            source = handle.read()

        self.assertTrue(origin.startswith("https://"))
        self.assertNotIn(origin.encode("utf-8"), source)

    def test_encrypted_service_profile_rejects_tampering(self):
        config_module = sys.modules[nodes.load_locked_service_profile.__module__]
        original = config_module._SERVICE_PROFILE_CIPHERTEXT
        replacement = "A" if original[-2] != "A" else "B"
        try:
            config_module._SERVICE_PROFILE_CIPHERTEXT = original[:-2] + replacement + original[-1]
            config_module._locked_service_profile.cache_clear()
            with self.assertRaises(nodes.ConfigError):
                nodes.load_locked_service_profile()
        finally:
            config_module._SERVICE_PROFILE_CIPHERTEXT = original
            config_module._locked_service_profile.cache_clear()

    def test_runtime_package_has_no_plaintext_forbidden_provider_markers(self):
        root = os.path.dirname(NODE_PATH)
        marker_blobs = (
            "Z3JzYWk=",
            "ZGFra2E=",
            "Z3B0X2ltYWdlXzI=",
            "Z3B0IGltYWdlIDI=",
        )
        markers = [base64.b64decode(value).decode("ascii") for value in marker_blobs]
        text_extensions = {".py", ".js", ".json", ".txt", ".bak"}

        for current_root, directories, filenames in os.walk(root):
            directories[:] = [name for name in directories if name != "__pycache__"]
            for name in filenames:
                relative_path = os.path.relpath(os.path.join(current_root, name), root)
                lowered_path = relative_path.lower()
                for marker in markers:
                    self.assertNotIn(marker, lowered_path, relative_path)
                if os.path.splitext(name)[1].lower() not in text_extensions:
                    continue
                with open(os.path.join(current_root, name), "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read().lower()
                for marker in markers:
                    self.assertNotIn(marker, content, relative_path)

    def test_locked_billing_file_is_unchanged(self):
        billing_path = os.path.join(os.path.dirname(NODE_PATH), "xinghuo.billing.lock")
        with open(billing_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(
            digest,
            "6786a1a393ba2d7ef0ce7c8d0629b127a7e9e07bc324cabbe54aba4be1738164",
        )

    def test_shared_client_download_never_forwards_provider_auth(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

        nodes.requests.request = request
        secure_draw_client().download_generated_image("https://8.8.8.8/generated.png")
        self.assertEqual(calls[0][0:2], ("GET", "https://8.8.8.8/generated.png"))
        self.assertNotIn("headers", calls[0][2])
        self.assertFalse(calls[0][2]["allow_redirects"])

    def test_shared_client_rejects_private_generated_image_url(self):
        with self.assertRaisesRegex(ValueError, "私有或保留"):
            secure_draw_client().download_generated_image("https://127.0.0.1/image.png")

    def test_async_data_string_is_polled_with_id_query(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if url.endswith("/nano-banana"):
                return FakeResponse(payload={"code": 0, "data": {"id": "task-1"}})
            return FakeResponse(payload={"code": 0, "data": {"id": "task-1", "status": "succeeded", "results": [{"url": png_data_uri()}]}})

        nodes.requests.request = request
        result = self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)
        self.assertEqual(result[0].shape, (1, 8, 8, 3))
        self.assertEqual(calls[1][0:2], ("POST", "https://service.invalid/v1/draw/result"))
        self.assertEqual(calls[1][2]["json"], {"id": "task-1"})

    def test_polling_never_resubmits_a_generation_request(self):
        calls = []
        poll_count = 0

        def request(method, url, **kwargs):
            nonlocal poll_count
            calls.append((method, url, kwargs))
            if url.endswith("/nano-banana"):
                return FakeResponse(payload={"code": 0, "data": {"id": "task-1", "status": "running"}})
            poll_count += 1
            if poll_count == 1:
                return FakeResponse(payload={"code": 0, "data": {"id": "task-1", "status": "running"}})
            return FakeResponse(payload={"code": 0, "data": {
                "id": "task-1", "status": "succeeded", "results": [{"url": png_data_uri()}]
            }})

        nodes.requests.request = request
        result = self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 3, 1)
        self.assertEqual(result[0].shape, (1, 8, 8, 3))
        self.assertEqual(sum(url.endswith("/nano-banana") for _, url, _ in calls), 1)
        self.assertEqual(sum(url.endswith("/v1/draw/result") for _, url, _ in calls), 2)

    def test_submit_timeout_is_returned_without_provider_details(self):
        nodes.requests.request = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            nodes.requests.ReadTimeout(
                "HTTPSConnectionPool(host='private-provider.example', port=443): "
                "Read timed out. (read timeout=10)"
            )
        )

        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("响应超时", result[1])
        self.assertIn("请勿立即重复提交", result[1])
        self.assertNotIn("private-provider.example", result[1])
        self.assertNotIn("HTTPSConnectionPool", result[1])
        self.assertNotIn("443", result[1])

    def test_poll_timeout_is_returned_without_provider_details(self):
        def request(_method, url, **_kwargs):
            if url.endswith("/nano-banana"):
                return FakeResponse(payload={"code": 0, "data": {
                    "id": "task-1", "status": "running"
                }})
            raise nodes.requests.ReadTimeout(
                "HTTPSConnectionPool(host='private-provider.example', port=443): timed out"
            )

        nodes.requests.request = request
        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 1, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("异步结果查询超时", result[1])
        self.assertNotIn("private-provider.example", result[1])
        self.assertNotIn("HTTPSConnectionPool", result[1])

    def test_image_download_timeout_is_returned_without_provider_details(self):
        def request(method, url, **_kwargs):
            if method == "POST":
                return FakeResponse(payload={"code": 0, "data": {
                    "id": "task-1",
                    "status": "succeeded",
                    "results": [{"url": "https://8.8.8.8/generated.png"}],
                }})
            raise nodes.requests.ReadTimeout(
                "HTTPSConnectionPool(host='private-storage.example', port=443): timed out"
            )

        nodes.requests.request = request
        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 1, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("图片下载超时", result[1])
        self.assertNotIn("private-storage.example", result[1])
        self.assertNotIn("HTTPSConnectionPool", result[1])

    def test_http_error_body_is_not_returned_to_comfyui(self):
        nodes.requests.request = lambda *_args, **_kwargs: FakeResponse(
            status_code=502,
            text="upstream https://private-provider.example failed?api_key=secret",
        )

        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 1, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("服务端暂时不可用", result[1])
        self.assertNotIn("private-provider.example", result[1])
        self.assertNotIn("api_key", result[1])

    def test_protocol_error_message_is_not_returned_to_comfyui(self):
        nodes.requests.request = lambda *_args, **_kwargs: FakeResponse(payload={
            "code": 500,
            "msg": "call https://private-provider.example failed?token=secret",
        })

        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 1, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("服务端返回失败状态", result[1])
        self.assertNotIn("private-provider.example", result[1])
        self.assertNotIn("token", result[1])

    def test_failed_terminal_timeout_is_classified_without_model_details(self):
        private_error = base64.b64decode(
            "Z29vZ2xlIGdlbWluaSB0aW1lb3V0Li4u"
        ).decode("ascii")
        payload = {
            "id": "2-22938a00-7fbc-4f27-9258-32f2e33cc366",
            "results": None,
            "progress": 0,
            "status": "failed",
            "failure_reason": "error",
            "error": private_error,
            "callback_url": "-1",
            "start_time": 1784354493,
            "end_time": 1784354728,
        }
        nodes.requests.request = lambda *_args, **_kwargs: FakeResponse(payload=payload)

        result = self.node.generate(
            "draw", "nano-banana-2", "key", "1:1", "1K", "async", 1, 1
        )

        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["failure"])
        self.assertIn("生成任务 处理超时", result[1])
        self.assertNotIn(private_error, result[1])
        self.assertNotIn("google", result[1].lower())
        self.assertNotIn("gemini", result[1].lower())

    def test_seventeen_reference_images_are_rejected_before_network(self):
        def request(*_args, **_kwargs):
            self.fail("network request must not be made")

        nodes.requests.request = request
        with self.assertRaisesRegex(ValueError, "最多 16 张"):
            self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1,
                               image1=torch.rand(17, 8, 8, 3))

    def test_unauthorized_response_does_not_poll(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(status_code=401, payload={"error": "bad key"}, text="bad key")

        nodes.requests.request = request
        result = self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)
        self.assertIn("访问密钥错误", result[1])
        self.assertEqual(len(calls), 1)

    def test_legacy_shifted_widgets_are_repaired_before_request(self):
        calls = []

        def request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(payload={"code": 0, "data": {
                "id": "legacy-1",
                "status": "succeeded",
                "results": [{"url": png_data_uri()}],
            }})

        nodes.requests.request = request
        result = self.node.generate(
            "draw",
            "nano-banana-fast",
            "key",
            "auto",
            "16:9",
            "2K",
            300,
            5,
        )
        self.assertEqual(result["ui"]["xinghuo_generation_status"], ["success"])
        payload = calls[0][2]["json"]
        self.assertEqual(payload["aspectRatio"], "16:9")
        self.assertEqual(payload["imageSize"], "2K")

    def test_invalid_generation_parameters_are_rejected_before_balance_query(self):
        calls = []
        nodes.query_account_balance = lambda *_args: calls.append("balance") or {
            "success": True,
            "credits": 999999,
        }

        with self.assertRaisesRegex(ValueError, "图像尺寸参数无效"):
            self.node.generate(
                "draw",
                "nano-banana-2",
                "key",
                "1:1",
                "16:9",
                "async",
                300,
                5,
            )

        self.assertEqual(calls, [])

    def test_v3_schema_excludes_reply_type(self):
        required = nodes.ComfyuiXinghuoNanoBananaV3.INPUT_TYPES()["required"]
        self.assertEqual(
            list(required),
            [
                "prompt",
                "model",
                "api_key",
                "aspect_ratio",
                "image_size",
                "max_poll_attempts",
                "poll_interval",
            ],
        )
        self.assertNotIn("reply_type", required)
        self.assertIn(
            "comfyui_xinghuo_nano_banana_v3",
            nodes.NODE_CLASS_MAPPINGS,
        )

    def test_encrypted_legacy_node_id_remains_compatible(self):
        legacy_id = base64.b64decode(
            "Y29tZnl1aV94aW5naHVvX2dwdF9pbWFnZV8y"
        ).decode("ascii")
        self.assertIs(
            nodes.NODE_CLASS_MAPPINGS[legacy_id],
            nodes.ComfyuiXinghuoNanoBanana,
        )
        self.assertEqual(
            nodes.NODE_DISPLAY_NAME_MAPPINGS[legacy_id],
            "comfyui xinghuo nano banana ",
        )

    def test_balance_uses_encrypted_config_key_without_returning_it(self):
        captured = {}

        def request(method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return FakeResponse(payload={"code": 0, "data": {"credits": 123}})

        nodes.requests.post = lambda url, **kwargs: request("POST", url, **kwargs)
        result = nodes.query_account_balance("key", "nano-banana-2")
        self.assertEqual(result["success"], True)
        self.assertEqual(result["credits"], 123)
        self.assertEqual(captured["url"], "https://service.invalid/client/openapi/getAPIKeyCredits")
        self.assertEqual(captured["kwargs"]["json"], {"apiKey": "key"})
        self.assertNotIn("key", result)

    def test_browser_balance_preview_excludes_credits_and_internal_errors(self):
        billing = nodes._locked_billing()
        nodes.query_account_balance = lambda *_args: {
            "success": True,
            "credits": 987654,
            "balance": 12.34,
            "preview_costs": [billing[name]["display_amount"] for name in nodes._MODEL_LIST],
            "error": "internal details must never be sent to the browser",
        }
        preview = nodes.public_balance_preview("key", "nano-banana-2")
        self.assertEqual(preview, {"success": True, "balance": 12.34,
                                   "preview_costs": [billing[name]["display_amount"] for name in nodes._MODEL_LIST]})
        self.assertNotIn("credits", preview)
        self.assertNotIn("error", preview)

        nodes.query_account_balance = lambda *_args: {
            "success": False,
            "error": "https://internal.example/secret?api_key=not-for-browser",
        }
        failed_preview = nodes.public_balance_preview("key", "nano-banana-2")
        self.assertEqual(failed_preview, {"success": False, "error": "\u8d26\u6237\u67e5\u8be2\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8bbf\u95ee\u5bc6\u94a5\u6216\u7f51\u7edc\u540e\u91cd\u8bd5"})

    def test_balance_timeout_does_not_store_provider_details(self):
        nodes.requests.post = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            nodes.requests.ReadTimeout(
                "HTTPSConnectionPool(host='private-provider.example', port=443): timed out"
            )
        )

        result = nodes.query_account_balance("key", "nano-banana-2")

        self.assertEqual(result["success"], False)
        self.assertIn("账户查询超时", result["error"])
        self.assertNotIn("private-provider.example", result["error"])
        self.assertNotIn("HTTPSConnectionPool", result["error"])

    def test_balance_protocol_error_does_not_store_upstream_message(self):
        nodes.requests.post = lambda *_args, **_kwargs: FakeResponse(payload={
            "code": 500,
            "msg": "upstream https://private-provider.example failed?token=secret",
        })

        result = nodes.query_account_balance("key", "nano-banana-2")

        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "账户查询失败（服务端拒绝请求）")
        self.assertNotIn("private-provider.example", result["error"])
        self.assertNotIn("token", result["error"])

    def test_configured_single_request_billing_is_locked_to_the_three_allowed_models(self):
        billing = nodes._locked_billing()
        self.assertEqual(list(billing), nodes._MODEL_LIST)
        self.assertTrue(all(item["credits"] > 0 and item["display_amount"] > 0 for item in billing.values()))

    def test_balance_uses_only_complete_calls_at_the_selected_model_rate(self):
        nodes.requests.post = lambda *_args, **_kwargs: FakeResponse(payload={"code": 0, "data": {"credits": 2501}})
        result = nodes.query_account_balance("key", "nano-banana-2")
        billing = nodes._locked_billing()["nano-banana-2"]
        self.assertEqual(result["credits"], 2501)
        self.assertEqual(result["balance"], round((2501 // billing["credits"]) * billing["display_amount"], 2))
        self.assertEqual(result["preview_costs"], [nodes._locked_billing()[name]["display_amount"] for name in nodes._MODEL_LIST])

    def test_interruption_before_submit_does_not_send_generation_request(self):
        original_interrupt = nodes.comfy.model_management.throw_exception_if_processing_interrupted
        nodes.query_account_balance = lambda *_args: {"success": True, "credits": 999999}
        try:
            nodes.comfy.model_management.throw_exception_if_processing_interrupted = lambda: (_ for _ in ()).throw(RuntimeError("interrupted"))
            nodes.requests.request = lambda *_args, **_kwargs: self.fail("generation request must not be sent after cancellation")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)
        finally:
            nodes.comfy.model_management.throw_exception_if_processing_interrupted = original_interrupt

    def test_violation_response_reports_public_reason_only(self):
        payload = {"id": "task-1", "status": "violation", "error": "prompt policy blocked"}
        self.assertEqual(nodes._upstream_failure_reason(payload), "内容审核未通过")

    def test_balance_failure_prevents_generation_submission(self):
        nodes.query_account_balance = lambda *_args: {"success": False, "error": "模型余额状态不可确认", "balance": 0}
        with self.assertRaisesRegex(ValueError, "未提交生成请求"):
            self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)

    def test_balance_failure_does_not_expose_internal_error_details(self):
        nodes.query_account_balance = lambda *_args: {
            "success": False,
            "error": "https://internal.invalid/private?api_key=not-for-ui",
            "balance": 0,
        }
        with self.assertRaises(ValueError) as context:
            self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)
        self.assertIn("未提交生成请求", str(context.exception))
        self.assertNotIn("internal.invalid", str(context.exception))
        self.assertNotIn("api_key", str(context.exception))

    def test_insufficient_balance_does_not_expose_credit_values_or_submit(self):
        nodes.query_account_balance = lambda *_args: {"success": True, "credits": 0, "balance": 0}
        nodes.requests.request = lambda *_args, **_kwargs: self.fail("generation request must not be made")
        with self.assertRaises(ValueError) as context:
            self.node.generate("draw", "nano-banana-2", "key", "1:1", "1K", "async", 2, 1)
        self.assertIn("未提交生成请求", str(context.exception))
        self.assertNotIn("nano-banana-2", str(context.exception))

    def test_comfyui_interrupt_is_propagated(self):
        original = nodes.comfy.model_management.throw_exception_if_processing_interrupted
        try:
            nodes.comfy.model_management.throw_exception_if_processing_interrupted = lambda: (_ for _ in ()).throw(RuntimeError("interrupted"))
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                nodes._check_comfyui_interrupt()
        finally:
            nodes.comfy.model_management.throw_exception_if_processing_interrupted = original


if __name__ == "__main__":
    unittest.main()
