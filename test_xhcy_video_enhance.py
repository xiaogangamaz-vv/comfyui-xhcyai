"""Video Super-Resolution node — offline tests.

No network, no files written: the client methods are patched and the node's
``_save_video`` is overridden, so these run in a bare ComfyUI python.

    python -m unittest test_xhcy_video_enhance.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
if NODE_DIR not in sys.path:
    sys.path.insert(0, NODE_DIR)

import nodes_xhcy_video_enhance as enhance  # noqa: E402
import xhcy_client  # noqa: E402
import xhcy_video_base  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class RecordingNode(enhance.XHCYVideoSuperResolution):
    """Does not touch the ComfyUI output directory."""

    saved: list = []

    @classmethod
    def _save_video(cls, raw: bytes, task_id: str) -> str:
        cls.saved.append((raw, task_id))
        return os.path.join(NODE_DIR, "unused.mp4")


def run_node(payloads: list, **overrides):
    """Run the node with every side effect patched out."""
    submit = overrides.pop("submit", {"task_id": "task_1", "status": "queued"})
    poll = overrides.pop(
        "poll",
        {
            "status": "succeeded",
            "content": {"url": "https://api.example.test/v1/video/enhance/task_1/content"},
        },
    )
    kwargs = dict(
        api_key="key",
        source_task_id="task_source",
        video_url="",
        duration=5,
        resolution="2K",
        tool_version="standard",
        scene="aigc",
        bitrate_level="medium",
        fps=0,
        max_poll_attempts=3,
        poll_interval=1,
        base_url="https://api.example.test",
    )
    kwargs.update(overrides)

    with mock.patch.object(
        xhcy_client.XHCYClient, "submit_video_enhancement", return_value=submit
    ) as submitted, mock.patch.object(
        xhcy_client.XHCYClient, "poll_video_enhancement", return_value=poll
    ) as polled, mock.patch.object(
        xhcy_client.XHCYClient, "download", return_value=b"mp4-bytes"
    ), mock.patch.object(
        xhcy_video_base, "sleep_interruptible", lambda *_: None
    ), mock.patch.object(
        xhcy_video_base, "check_interrupt", lambda: None
    ), mock.patch.object(
        enhance, "check_interrupt", lambda: None
    ):
        result = RecordingNode().generate(**kwargs)

    if submitted.called:
        payloads.append(submitted.call_args.args[0])
    return result, polled


class VideoSuperResolutionNodeTest(unittest.TestCase):
    def setUp(self) -> None:
        RecordingNode.saved = []

    # -- payload ------------------------------------------------------- #

    def test_task_id_form_builds_the_documented_payload(self):
        payloads: list = []
        result, polled = run_node(payloads)

        payload = payloads[0]
        self.assertEqual(payload["model"], "Video Super-Resolution")
        self.assertEqual(payload["source_task_id"], "task_source")
        self.assertNotIn("content", payload)
        self.assertEqual(payload["resolution"], "2K")
        self.assertEqual(payload["tool_version"], "standard")
        self.assertEqual(payload["scene"], "aigc")
        self.assertEqual(payload["bitrate_level"], "medium")
        self.assertEqual(payload["duration"], 5)
        self.assertNotIn("fps", payload)
        self.assertNotIn("ratio", payload)

        # 4 outputs, and the task id is the 4th so it can be piped onward.
        self.assertEqual(len(result), 4)
        self.assertEqual(result[3], "task_1")
        self.assertTrue(polled.called)

    def test_professional_omits_scene_and_says_so(self):
        payloads: list = []
        result, _ = run_node(payloads, tool_version="professional", scene="ugc")

        self.assertNotIn("scene", payloads[0])
        self.assertIn("professional", payloads[0]["tool_version"])
        self.assertIn("只对 standard 生效", result[1])

    def test_fps_is_omitted_at_zero_and_forwarded_when_set(self):
        payloads: list = []
        run_node(payloads, fps=0)
        self.assertNotIn("fps", payloads[0])

        run_node(payloads, fps=24)
        self.assertEqual(payloads[1]["fps"], 24)

    def test_url_form_builds_a_single_base_video_item(self):
        payloads: list = []
        run_node(
            payloads,
            source_task_id="",
            video_url="https://cdn.example.com/source-720p.mp4",
        )

        payload = payloads[0]
        self.assertNotIn("source_task_id", payload)
        self.assertEqual(
            payload["content"],
            [
                {
                    "type": "video_url",
                    "role": "base_video",
                    "video_url": {"url": "https://cdn.example.com/source-720p.mp4"},
                }
            ],
        )

    # -- validation ---------------------------------------------------- #

    def test_both_sources_are_rejected(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "二选一"):
            run_node([], source_task_id="task_source", video_url="https://x/y.mp4")

    def test_missing_source_is_rejected(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "缺少源视频"):
            run_node([], source_task_id="", video_url="")

    def test_non_http_url_is_rejected(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "http"):
            run_node([], source_task_id="", video_url="ftp://x/y.mp4")

    def test_duration_must_fit_the_sold_window(self):
        for value in (0, 301):
            with self.assertRaisesRegex(xhcy_client.XHCYError, "源视频时长"):
                run_node([], duration=value)

    def test_fps_above_the_priced_band_is_rejected(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "目标帧率"):
            run_node([], fps=31)

    def test_unknown_resolution_is_rejected(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "目标分辨率"):
            run_node([], resolution="480P")

    # -- failure paths ------------------------------------------------- #

    def test_submit_failure_raises_and_does_not_poll(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "提交失败"):
            run_node(
                [],
                submit={"status": "failed", "error": {"message": "upstream refused"}},
            )

    def test_poll_failure_raises(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "生成失败"):
            run_node([], poll={"status": "failed", "failure_reason": "bad source"})

    def test_missing_task_id_after_submit_raises(self):
        with self.assertRaisesRegex(xhcy_client.XHCYError, "任务 ID"):
            run_node([], submit={"status": "queued"})

    # -- client + base contract ---------------------------------------- #

    def test_client_uses_the_enhance_paths(self):
        with mock.patch.object(
            xhcy_client.XHCYClient,
            "_send",
            return_value=FakeResponse(200, {"task_id": "t1"}),
        ) as send:
            xhcy_client.XHCYClient("key", "https://api.example.test").submit_video_enhancement(
                {"model": "Video Super-Resolution"}
            )
        self.assertEqual(send.call_args.args[0], "POST")
        self.assertEqual(send.call_args.args[1], "/v1/video/enhance")

        with mock.patch.object(
            xhcy_client.XHCYClient,
            "_send",
            return_value=FakeResponse(200, {"status": "succeeded"}),
        ) as send:
            xhcy_client.XHCYClient("key", "https://api.example.test").poll_video_enhancement(
                "task_7"
            )
        self.assertEqual(send.call_args.args[1], "/v1/video/enhance/task_7")

    def test_every_video_node_exposes_the_task_id_output(self):
        # The bridge only works if the generation nodes hand the task id onward.
        # task_id is appended; the first three sockets stay video / status / video_path.
        expected_names = ("video", "status", "video_path", "task_id")
        expected_types = ("VIDEO", "STRING", "STRING", "STRING")
        self.assertEqual(xhcy_video_base.XHCYVideoBase.RETURN_NAMES, expected_names)
        self.assertEqual(xhcy_video_base.XHCYVideoBase.RETURN_TYPES, expected_types)
        self.assertEqual(enhance.XHCYVideoSuperResolution.RETURN_NAMES, expected_names)
        self.assertEqual(enhance.XHCYVideoSuperResolution.RETURN_TYPES, expected_types)

    def test_node_is_registered_with_its_display_name(self):
        self.assertIn("xhcy_video_enhance", enhance.NODE_CLASS_MAPPINGS)
        self.assertIn("xhcy_video_enhance", enhance.NODE_DISPLAY_NAME_MAPPINGS)
        self.assertIn(
            "Video Super-Resolution",
            enhance.NODE_DISPLAY_NAME_MAPPINGS["xhcy_video_enhance"],
        )

    def test_upload_write_timeout_is_not_recovered_into_another_submit(self):
        import time

        import requests
        import urllib3.exceptions

        client = xhcy_client.XHCYClient("key", "https://api.example.test")
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
            with self.assertRaises(xhcy_client.XHCYError) as caught:
                client.submit_video({"model": "MiniMax-H3", "content": []})
        self.assertEqual(calls, [client._direct])
        self.assertIn(xhcy_client.UPLOAD_WRITE_TIMEOUT_MARK, str(caught.exception))

        listing = mock.Mock()

        def fail_if_slept(*_args, **_kwargs):
            raise AssertionError("upload write timeout must not enter gateway recovery")

        with mock.patch.object(xhcy_video_base, "sleep_interruptible", fail_if_slept):
            with self.assertRaises(xhcy_client.XHCYError) as recovered:
                xhcy_video_base.XHCYVideoBase._recover_after_gateway_timeout(
                    listing, "MiniMax-H3", time.time(), caught.exception
                )
        self.assertIs(recovered.exception, caught.exception)
        listing.list_video_tasks.assert_not_called()
        listing.submit_video.assert_not_called()

    def test_gateway_response_timeout_still_looks_up_the_task_without_resubmitting(self):
        import time

        client = mock.Mock()
        client.list_video_tasks.return_value = {
            "items": [
                {
                    "model": "MiniMax-H3",
                    "created_at": time.time(),
                    "task_id": "task-recovered",
                    "status": "queued",
                }
            ]
        }
        with mock.patch.object(xhcy_video_base, "sleep_interruptible", lambda *_a, **_k: None), mock.patch.object(
            xhcy_video_base, "check_interrupt", lambda: None
        ):
            found = xhcy_video_base.XHCYVideoBase._recover_after_gateway_timeout(
                client,
                "MiniMax-H3",
                time.time(),
                xhcy_client.XHCYError("视频生成请求已发出，但等待网关响应超时"),
            )
        self.assertEqual(found["task_id"], "task-recovered")
        client.list_video_tasks.assert_called()
        client.submit_video.assert_not_called()

    def test_seedance_and_regeneration_nodes_return_four_values(self):
        import nodes_minimax_h3  # noqa: E402
        import nodes_minimax_h3_frames  # noqa: E402
        import nodes_minimax_h3_regen  # noqa: E402
        import nodes_seedance  # noqa: E402

        expected_names = ("video", "status", "video_path", "task_id")
        expected_types = ("VIDEO", "STRING", "STRING", "STRING")
        for node_cls in (
            nodes_seedance.XHCYSeedance2,
            nodes_minimax_h3.XHCYMiniMaxH3,
            nodes_minimax_h3_frames.XHCYMiniMaxH3Frames,
            nodes_minimax_h3_regen.XHCYMiniMaxH3Regeneration,
        ):
            self.assertEqual(node_cls.RETURN_NAMES, expected_names)
            self.assertEqual(node_cls.RETURN_TYPES, expected_types)

        saved = os.path.join(NODE_DIR, "unused.mp4")

        def save_video(cls, raw, task_id):
            return saved

        with mock.patch.object(
            xhcy_client.XHCYClient,
            "submit_video",
            return_value={"task_id": "task_seedance", "status": "queued"},
        ), mock.patch.object(
            xhcy_client.XHCYClient,
            "poll_video",
            return_value={
                "status": "succeeded",
                "content": {"url": "https://api.example.test/v.mp4"},
            },
        ), mock.patch.object(
            xhcy_client.XHCYClient, "media_bytes", return_value=b"mp4-bytes"
        ), mock.patch.object(
            xhcy_video_base.XHCYVideoBase, "_save_video", classmethod(save_video)
        ), mock.patch.object(
            xhcy_video_base, "sleep_interruptible", lambda *_a, **_k: None
        ), mock.patch.object(
            xhcy_video_base, "check_interrupt", lambda: None
        ):
            seedance = nodes_seedance.XHCYSeedance2().generate(
                prompt="a cat walks",
                model="doubao-seedance-2-0",
                api_key="key",
                resolution="720P",
                duration=5,
                ratio="16:9",
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://api.example.test",
            )
        self.assertEqual(len(seedance), 4)
        self.assertEqual(seedance[1].splitlines()[0], "XHCY 视频生成成功")
        self.assertEqual(seedance[2], saved)
        self.assertEqual(seedance[3], "task_seedance")

        with mock.patch.object(
            xhcy_client.XHCYClient,
            "submit_video_regeneration",
            return_value={"task_id": "task_regen", "status": "queued"},
        ), mock.patch.object(
            xhcy_client.XHCYClient,
            "poll_video",
            return_value={
                "status": "succeeded",
                "content": {"url": "https://api.example.test/v.mp4"},
            },
        ), mock.patch.object(
            xhcy_client.XHCYClient, "media_bytes", return_value=b"mp4-bytes"
        ), mock.patch.object(
            xhcy_video_base.XHCYVideoBase, "_save_video", classmethod(save_video)
        ), mock.patch.object(
            xhcy_video_base, "sleep_interruptible", lambda *_a, **_k: None
        ), mock.patch.object(
            xhcy_video_base, "check_interrupt", lambda: None
        ), mock.patch.object(
            nodes_minimax_h3_regen, "check_interrupt", lambda: None
        ):
            regen = nodes_minimax_h3_regen.XHCYMiniMaxH3Regeneration().generate(
                api_key="key",
                model="MiniMax-H3",
                source_task_id="task_source",
                prompt="",
                duration=5,
                max_poll_attempts=2,
                poll_interval=1,
                base_url="https://api.example.test",
            )
        self.assertEqual(len(regen), 4)
        self.assertIn("再生成成功", regen[1])
        self.assertEqual(regen[2], saved)
        self.assertEqual(regen[3], "task_regen")


if __name__ == "__main__":
    unittest.main(verbosity=2)
