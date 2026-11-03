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
        self.assertEqual(len(xhcy_video_base.XHCYVideoBase.RETURN_NAMES), 4)
        self.assertEqual(xhcy_video_base.XHCYVideoBase.RETURN_NAMES[3], "task_id")
        self.assertEqual(len(enhance.XHCYVideoSuperResolution.RETURN_NAMES), 4)
        self.assertEqual(enhance.XHCYVideoSuperResolution.RETURN_NAMES[3], "task_id")

    def test_node_is_registered_with_its_display_name(self):
        self.assertIn("xhcy_video_enhance", enhance.NODE_CLASS_MAPPINGS)
        self.assertIn("xhcy_video_enhance", enhance.NODE_DISPLAY_NAME_MAPPINGS)
        self.assertIn(
            "Video Super-Resolution",
            enhance.NODE_DISPLAY_NAME_MAPPINGS["xhcy_video_enhance"],
        )

    def test_seedance_and_regeneration_nodes_return_four_values(self):
        import nodes_minimax_h3_regen  # noqa: E402
        import nodes_seedance  # noqa: E402

        self.assertEqual(len(nodes_seedance.XHCYSeedance2.RETURN_NAMES), 4)
        self.assertEqual(nodes_seedance.XHCYSeedance2.RETURN_NAMES[3], "task_id")
        self.assertEqual(
            len(nodes_minimax_h3_regen.XHCYMiniMaxH3Regeneration.RETURN_NAMES), 4
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
