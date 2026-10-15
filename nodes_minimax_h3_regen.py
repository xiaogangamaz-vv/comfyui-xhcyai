"""XHCY AI video node — MiniMax H3, 768P -> 2K regeneration.

接口来自站点后端源码（``router/relay.go`` 与 ``relay/controller/video.go``）：

    POST /v1/video/regenerations
    {
      "model": "MiniMax-H3",
      "resolution": "2K",           # 只支持 2K，别的值站点直接 400
      "duration": 5,                # 必填；输出长度跟随源视频，这个值只用于计费
      "source_task_id": "..."       # 二选一：① 用已有任务的结果
    }
    # 或者
    {
      "model": "MiniMax-H3",
      "resolution": "2K",
      "duration": 5,
      "content": [                  # 二选一：② 直接给素材
        {"type": "text", "text": "..."},
        {"type": "video_url", "role": "base_video", "video_url": {"url": "<data URI>"}}
      ]
    }

两条硬性约束，节点里已经帮你挡掉：
    * ``source_task_id`` 与 ``content`` 只能二选一；
    * 用 content 时，必须**恰好一个** ``role`` 为 ``base_video`` 的视频项。

结果沿用普通视频任务的查询接口 ``GET /v1/video/generations/{task_id}``。
"""

from __future__ import annotations

try:
    from .xhcy_client import DEFAULT_BASE_URL, STATUS_FAILURE, XHCYClient, XHCYError, extract_status
    from .xhcy_client import extract_failure_reason, extract_task_id, extract_video_url
    from .xhcy_video_base import (
        MAX_VIDEO_BYTES,
        XHCYVideoBase,
        _int_param,
        check_interrupt,
        reset_material_budget,
        video_input_to_uri,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import DEFAULT_BASE_URL, STATUS_FAILURE, XHCYClient, XHCYError, extract_status  # type: ignore
    from xhcy_client import extract_failure_reason, extract_task_id, extract_video_url  # type: ignore
    from xhcy_video_base import (  # type: ignore
        MAX_VIDEO_BYTES,
        XHCYVideoBase,
        _int_param,
        check_interrupt,
        reset_material_budget,
        video_input_to_uri,
    )

# (STATUS_FAILURE 已并入上方 import)

# 该接口只认 2K，不做下拉
TARGET_RESOLUTION = "2K"

# 站点对 MiniMax-H3 的时长范围
_DURATION_LOW, _DURATION_HIGH = 4, 30


class XHCYMiniMaxH3Regeneration(XHCYVideoBase):
    """768P -> 2K regeneration, driven either by an existing task or a source video."""

    VARIANT_MODELS = ["MiniMax-H3"]
    NODE_ID = "xhcy_h3_regen"
    OUTPUT_PREFIX = "xhcy_h3_regen"
    CATEGORY = "XHCY/Video"
    DESCRIPTION = (
        "XHCY AI · MiniMax H3 视频再生成（768P → 2K）："
        "填源任务号，或直接接一段源视频"
    )

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
                "model": (
                    list(cls.VARIANT_MODELS),
                    {
                        "default": cls.VARIANT_MODELS[0],
                        "tooltip": "再生成是 H3 专属能力（输出 2K），H3-Lite 不支持。",
                    },
                ),
                "source_task_id": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": (
                            "方式一：填一个已生成视频的任务号，直接把它提升到 2K。"
                            "填了这里就不用再连源视频。留空则必须连接 base_video。"
                        ),
                    },
                ),
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": (
                            "方式二（连接源视频）时必填：说明要怎么处理这段视频。"
                            "用任务号的方式一可以留空。"
                        ),
                    },
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 60,
                        "tooltip": (
                            "秒。输出长度跟随源视频，这里填的只用于计费（按输出秒数计价）。"
                            "超出 4～30 秒会自动收进区间。"
                        ),
                    },
                ),
                "max_poll_attempts": (
                    "INT",
                    {"default": 120, "min": 1, "max": 600, "tooltip": "最多查询多少次结果。"},
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
            "optional": {
                "base_video": (
                    "VIDEO",
                    {
                        "tooltip": (
                            "方式二：要提升到 2K 的源视频。素材以数据流内嵌上传，"
                            "体积越大越慢。与 source_task_id 二选一。"
                        )
                    },
                ),
            },
        }

    def generate(self, api_key, model, source_task_id, prompt, duration,
                 max_poll_attempts, poll_interval, base_url=DEFAULT_BASE_URL, **kwargs):
        reset_material_budget()

        if self.VARIANT_MODELS and model not in self.VARIANT_MODELS:
            raise XHCYError(f"未知的模型：{model}")

        seconds = min(max(_int_param(duration, "时长（秒）", 1, 60), _DURATION_LOW), _DURATION_HIGH)
        attempts = _int_param(max_poll_attempts, "最大查询次数", 1, 600)
        interval = _int_param(poll_interval, "查询间隔", 1, 60)

        task_text = (source_task_id or "").strip()
        prompt_text = (prompt or "").strip()
        source_video = kwargs.get("base_video")

        payload: dict = {
            "model": model,
            "resolution": TARGET_RESOLUTION,
            "duration": seconds,
        }

        if task_text:
            if source_video is not None:
                raise XHCYError(
                    "source_task_id 和源视频只能二选一："
                    "已经填了任务号，请断开 base_video；或者清空任务号改用源视频。"
                )
            payload["source_task_id"] = task_text
            mode_text = f"按任务号再生成（{task_text}）"
        else:
            if source_video is None:
                raise XHCYError(
                    "缺少源视频：请连接 base_video，或者在 source_task_id 里填一个已有的视频任务号。"
                )
            if not prompt_text:
                raise XHCYError(
                    "用源视频再生成时，提示词不能为空（上游要求 content 里必须有一段文字）。"
                )
            content: list = [{"type": "text", "text": prompt_text}]
            content.append(
                {
                    "type": "video_url",
                    "role": "base_video",
                    "video_url": {"url": video_input_to_uri(source_video)},
                }
            )
            payload["content"] = content
            mode_text = "按源视频再生成"

        check_interrupt()

        client = XHCYClient(api_key, base_url)
        first = client.submit_video_regeneration(payload)
        status = extract_status(first)
        if status in STATUS_FAILURE:
            raise XHCYError(f"提交失败：{extract_failure_reason(first) or '服务端未给出原因'}")

        task_id = extract_task_id(first)
        if not task_id:
            raise XHCYError("服务端没有返回任务 ID，无法查询结果")

        result = self._wait_for_video(client, task_id, attempts, interval)
        video_url = extract_video_url(result)
        if not video_url:
            raise XHCYError("任务已完成，但返回里没有找到视频地址")

        raw = client.download(video_url, max_bytes=MAX_VIDEO_BYTES)
        path = self._save_video(raw, task_id)

        summary = (
            f"XHCY 视频再生成成功\n"
            f"方式：{mode_text}\n"
            f"模型：{model}\n"
            f"目标：{TARGET_RESOLUTION} · 计费按 {seconds} 秒\n"
            f"任务：{task_id}\n"
            f"文件：{path}"
        )
        return (self._video_object(path), summary, path)


NODE_CLASS_MAPPINGS = {
    "xhcy_h3_regen": XHCYMiniMaxH3Regeneration,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_h3_regen": "XHCY MiniMax H3（768P→2K 再生成）",
}
