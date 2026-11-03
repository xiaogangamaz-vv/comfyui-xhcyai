"""HTTP-level smoke test for the Video Super-Resolution node.

Runs the *real* node and the *real* HTTP client against a local fake gateway, so
the only thing left unverified is the actual MediaKit/upstream call.

    python smoke_enhance_http.py

It checks:
  * submit goes to POST /v1/video/enhance with source_task_id (no content[]);
  * polling goes to GET /v1/video/enhance/{task_id}, not the generation path;
  * the succeeded envelope's content.url is downloaded **with** the bearer token;
  * the node returns 4 values and the 4th is the enhancement task id;
  * the saved file contains the served bytes.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
if NODE_DIR not in sys.path:
    sys.path.insert(0, NODE_DIR)

import nodes_xhcy_video_enhance as enhance  # noqa: E402
import xhcy_client  # noqa: E402

TASK_ID = "task_smoke_1"
BODY = b"smoke-mp4-bytes"


class FakeGateway(http.server.BaseHTTPRequestHandler):
    calls: list = []
    polls = 0

    def log_message(self, *args):  # keep the output clean
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        blob = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).calls.append(("POST", self.path, json.loads(body or b"{}"), self.headers.get("Authorization")))
        self._json({"task_id": TASK_ID, "status": "queued", "model": "Video Super-Resolution"})

    def do_GET(self):  # noqa: N802
        type(self).calls.append(("GET", self.path, None, self.headers.get("Authorization")))
        if self.path.startswith("/v1/video/enhance/") and self.path.endswith("/content"):
            if self.headers.get("Authorization") != "Bearer test-key":
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
            return
        type(self).polls += 1
        if type(self).polls == 1:
            self._json({"task_id": TASK_ID, "status": "processing"})
            return
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._json(
            {
                "task_id": TASK_ID,
                "status": "succeeded",
                "resolution": "2K",
                "tool_version": "standard",
                "content": {"url": f"{base}/v1/video/enhance/{TASK_ID}/content"},
            }
        )


class SmokeNode(enhance.XHCYVideoSuperResolution):
    saved_path = ""

    @classmethod
    def _save_video(cls, raw: bytes, task_id: str) -> str:
        path = os.path.join(tempfile.mkdtemp(prefix="xhcy_smoke_"), f"{task_id}.mp4")
        with open(path, "wb") as handle:
            handle.write(raw)
        cls.saved_path = path
        return path


def main() -> int:
    with socketserver.TCPServer(("127.0.0.1", 0), FakeGateway) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = SmokeNode().generate(
                api_key="test-key",
                source_task_id="task_seedance_source",
                video_url="",
                duration=5,
                resolution="2K",
                tool_version="standard",
                scene="aigc",
                bitrate_level="medium",
                fps=0,
                max_poll_attempts=5,
                poll_interval=1,
                base_url=f"http://127.0.0.1:{port}",
            )
        finally:
            server.shutdown()

    checks = []
    submit = next(c for c in FakeGateway.calls if c[0] == "POST")
    payload = submit[2]
    checks.append(("POST path", submit[1] == "/v1/video/enhance"))
    checks.append(("submit carries source_task_id", payload.get("source_task_id") == "task_seedance_source"))
    checks.append(("submit sends no content[]", "content" not in payload))
    checks.append(("submit sends the tier", payload.get("tool_version") == "standard"))
    checks.append(("submit sends no fps at 0", "fps" not in payload))
    poll_paths = [c[1] for c in FakeGateway.calls if c[0] == "GET" and not c[1].endswith("/content")]
    checks.append(("polls the enhance path", poll_paths and all(p.startswith("/v1/video/enhance/") for p in poll_paths)))
    content_calls = [c for c in FakeGateway.calls if c[0] == "GET" and c[1].endswith("/content")]
    checks.append(("downloads content with bearer", bool(content_calls) and content_calls[0][3] == "Bearer test-key"))
    checks.append(("returns 4 values", len(result) == 4))
    checks.append(("4th value is the task id", result[3] == TASK_ID))
    path = SmokeNode.saved_path
    checks.append(("saved file exists", os.path.isfile(path)))
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            checks.append(("saved bytes match", handle.read() == BODY))
        os.remove(path)
        os.rmdir(os.path.dirname(path))

    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
