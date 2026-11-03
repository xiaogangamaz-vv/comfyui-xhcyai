"""XHCY AI video node — 视频超分（Video Super-Resolution / 画质增强）。

站点接口（xhcy-one-api-commercial）：

    POST /v1/video/enhance
    GET  /v1/video/enhance/{task_id}
    GET  /v1/video/enhance/{task_id}/content

模型名固定为 ``Video Super-Resolution``，两种输入**二选一**：

  * ``source_task_id``：本平台已生成视频的任务号（Seedance / H3 节点的第 4 个输出）。
    网关会为这个任务签一个限时地址交给上游拉取，所以**不需要上传文件**，
    也不会把成片公开。这是 ComfyUI 里的推荐接法。
  * ``video_url``：一个公网可匿名访问的视频地址。平台自己的 ``/content`` 地址需要
    Bearer 鉴权，上游拉不到，不能填在这里。

计费按输出秒数 × 档位（分辨率 × tool_version），节点只在状态摘要里说明档位和秒数，
价格以站点为准。
"""

from __future__ import annotations

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_status,
        extract_task_id,
        extract_video_url,
    )
    from .xhcy_v3 import as_v3_node
    from .xhcy_credentials import resolve_credentials
    from .xhcy_video_base import (
        MAX_VIDEO_BYTES,
        XHCYVideoBase,
        _int_param,
        check_interrupt,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        STATUS_FAILURE,
        XHCYClient,
        XHCYError,
        extract_failure_reason,
        extract_status,
        extract_task_id,
        extract_video_url,
    )
    from xhcy_v3 import as_v3_node  # type: ignore
    from xhcy_credentials import resolve_credentials  # type: ignore
    from xhcy_video_base import (  # type: ignore
        MAX_VIDEO_BYTES,
        XHCYVideoBase,
        _int_param,
        check_interrupt,
    )

# 站点上的公开模型名，固定值。
MODEL = "Video Super-Resolution"

# 与站点 relay/adaptor/mediakit 的售卖集保持一致：
# 240p/360p/480p/540p/6k/8k 上游合法但平台没有定价行，选不到也就不会被拒。
RESOLUTIONS = ["720P", "1080P", "2K", "4K"]
TOOL_VERSIONS = ["standard", "professional"]
SCENES = ["common", "ugc", "short_series", "aigc", "old_film"]
BITRATE_LEVELS = ["low", "medium", "high"]

# 站点对源视频时长的售卖区间（用于按秒预留）。
MIN_SECONDS, MAX_SECONDS = 1, 300

# 站点只上架了 ≤30fps 档；更高帧率上游单价不同，平台会拒绝。
MAX_PRICED_FPS = 30


class XHCYVideoSuperResolution(XHCYVideoBase):
    """视频超分 / 画质增强：接任务号或公网地址，输出放大后的视频。"""

    VARIANT_MODELS: list[str] = [MODEL]
    NODE_ID = "xhcy_video_enhance"
    OUTPUT_PREFIX = "xhcy_enhance"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = (
        "XHCY AI · 视频超分（Video Super-Resolution）："
        "把已生成的视频提升到 720P / 1080P / 2K / 4K"
    )
    # 第 4 个输出是超分任务的号，可以继续接下一次超分或留给排查。
    RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video", "status", "video_path", "task_id")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "defaultInput": True,
                        "tooltip": "XHCY AI 访问密钥。每个节点单独填。",
                    },
                ),
                "source_task_id": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": (
                            "方式一（推荐）：把 Seedance / H3 节点的 task_id 输出接到这里。"
                            "平台会为该任务签一个限时地址交给上游，不需要上传，也不会公开成片。"
                            "与 video_url 二选一。"
                        ),
                    },
                ),
                "video_url": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": (
                            "方式二：公网可匿名访问的视频地址（http/https）。"
                            "平台自己的 /content 地址需要登录，上游拉不到，别填这里。"
                            "与 source_task_id 二选一。"
                        ),
                    },
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": MIN_SECONDS,
                        "max": MAX_SECONDS,
                        "tooltip": (
                            "秒。填**源视频时长**：输出长度跟随源视频，这个值只用于按秒计费。"
                            "不填对会按错误的秒数预留额度。"
                        ),
                    },
                ),
                "resolution": (
                    list(RESOLUTIONS),
                    {
                        "default": "2K",
                        "tooltip": "目标档位，直接决定单价档。480P/720P 源提升到 2K 是常见用法。",
                    },
                ),
                "tool_version": (
                    list(TOOL_VERSIONS),
                    {
                        "default": "standard",
                        "tooltip": (
                            "standard：快，日常分发够用；"
                            "professional：影视级画质，单价高一个量级。"
                        ),
                    },
                ),
                "scene": (
                    list(SCENES),
                    {
                        "default": "aigc",
                        "tooltip": "场景模板（通用 / UGC / 短剧 / AIGC / 老片修复）。**只对 standard 生效**。",
                    },
                ),
                "bitrate_level": (
                    list(BITRATE_LEVELS),
                    {
                        "default": "medium",
                        "tooltip": "输出码率档。high 更清晰、文件更大；medium 推荐。",
                    },
                ),
                "fps": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": MAX_PRICED_FPS,
                        "tooltip": (
                            "0 = 保持源帧率（不发送该字段）；15～30 可指定。"
                            "平台目前只上架 ≤30fps 档。"
                        ),
                    },
                ),
                "max_poll_attempts": (
                    "INT",
                    {"default": 240, "min": 1, "max": 600, "tooltip": "最多查询多少次结果。"},
                ),
                "poll_interval": (
                    "INT",
                    {"default": 5, "min": 1, "max": 60, "tooltip": "每次查询之间等几秒。"},
                ),
                "base_url": (
                    "STRING",
                    {
                        "default": DEFAULT_BASE_URL,
                        "multiline": False,
                        "tooltip": "站点地址，一般不用改。",
                    },
                ),
            },
        }

    def generate(self, api_key, source_task_id, video_url, duration, resolution,
                 tool_version, scene, bitrate_level, fps,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL):
        task_text = (source_task_id or "").strip()
        url_text = (video_url or "").strip()

        if task_text and url_text:
            raise XHCYError(
                "两个来源都填了：source_task_id 和 video_url 只能二选一。\n"
                "推荐保留 source_task_id（不用上传），把 video_url 清空。"
            )
        if not task_text and not url_text:
            raise XHCYError(
                "缺少源视频：请把 Seedance / H3 节点的 task_id 接到 source_task_id；"
                "或者填一个公网可访问的 video_url。"
            )
        if resolution not in RESOLUTIONS:
            raise XHCYError(f"不支持的目标分辨率：{resolution}；可选：{'、'.join(RESOLUTIONS)}")
        if tool_version not in TOOL_VERSIONS:
            raise XHCYError(f"不支持的版本：{tool_version}；可选：{'、'.join(TOOL_VERSIONS)}")
        if scene not in SCENES:
            raise XHCYError(f"不支持的场景模板：{scene}；可选：{'、'.join(SCENES)}")
        if bitrate_level not in BITRATE_LEVELS:
            raise XHCYError(f"不支持的码率档：{bitrate_level}；可选：{'、'.join(BITRATE_LEVELS)}")

        seconds = _int_param(duration, "源视频时长（秒）", MIN_SECONDS, MAX_SECONDS)
        fps_value = _int_param(fps, "目标帧率", 0, MAX_PRICED_FPS)
        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)

        if url_text and not (
            url_text.startswith("http://") or url_text.startswith("https://")
        ):
            raise XHCYError(
                "video_url 必须是 http(s) 公网地址。\n"
                "注意：平台自己的 /v1/video/.../content 地址需要 Bearer 鉴权，"
                "上游拉不到，不能填在这里——请改用 source_task_id。"
            )

        payload: dict = {
            "model": MODEL,
            "resolution": resolution,
            "duration": seconds,
            "tool_version": tool_version,
            "bitrate_level": bitrate_level,
        }
        # 上游文档：scene 只在 standard 生效。professional 下不发，避免看起来生效了。
        scene_note = ""
        if tool_version == "standard":
            payload["scene"] = scene
        else:
            scene_note = "\n场景模板（scene）只对 standard 生效，professional 已忽略。"

        if fps_value > 0:
            payload["fps"] = fps_value

        if task_text:
            payload["source_task_id"] = task_text
            mode_text = f"按平台任务号（{task_text}）"
        else:
            payload["content"] = [
                {
                    "type": "video_url",
                    "role": "base_video",
                    "video_url": {"url": url_text},
                }
            ]
            mode_text = "按公网视频地址"

        check_interrupt()

        api_key, base_url = resolve_credentials(api_key, base_url)
        client = XHCYClient(api_key, base_url)
        first = client.submit_video_enhancement(payload)
        status = extract_status(first)
        if status in STATUS_FAILURE:
            raise XHCYError(f"提交失败：{extract_failure_reason(first) or '服务端未给出原因'}")

        task_id = extract_task_id(first)
        if not task_id:
            raise XHCYError("服务端没有返回任务 ID，无法查询超分结果")

        # 超分任务的查询路径与生成任务不同，必须在这里换掉。
        result = self._wait_for_video(
            client, task_id, attempts, interval,
            poll_fn=client.poll_video_enhancement,
        )
        result_url = extract_video_url(result)
        if not result_url:
            raise XHCYError("任务已完成，但返回里没有找到视频地址")

        raw = client.download(result_url, max_bytes=MAX_VIDEO_BYTES)
        path = self._save_video(raw, task_id)

        fps_text = "保持源帧率" if fps_value == 0 else f"{fps_value} fps"
        summary = (
            f"XHCY 视频超分成功\n"
            f"方式：{mode_text}\n"
            f"模型：{MODEL}\n"
            f"目标：{resolution} · {tool_version} · {fps_text}\n"
            f"计费按 {seconds} 秒 × 该档单价{scene_note}\n"
            f"任务：{task_id}\n"
            f"文件：{path}"
        )
        return (self._video_object(path), summary, path, task_id)


NODE_CLASS_MAPPINGS = {
    "xhcy_video_enhance": as_v3_node(
        XHCYVideoSuperResolution,
        "xhcy_video_enhance",
        "XHCY 视频超分（Video Super-Resolution）",
    ),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_video_enhance": "XHCY 视频超分（Video Super-Resolution）",
}
