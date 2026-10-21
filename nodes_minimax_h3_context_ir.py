"""XHCY AI video node — MiniMax H3 Context-IR（提示词增强）.

接口来自站点后端源码（``router/relay.go`` 与 ``relay/controller/video_context_ir.go``）：

    POST /v1/video/context-ir
    {
      "model": "MiniMax-H3",
      "content": [{"type": "text", "text": "原始描述"}],   # 可附带图片/视频/音频
      "duration": 5,          # 上游要求，取值需在模型范围内
      "ratio": "16:9"         # 纯文本时必须显式给出，且不能是 adaptive
    }

响应是**同步**返回的（站点内部最多等约 120 秒），产物是一段增强后的提示词：

    {"success": true, "message": "", "data": {"task_id": "...", "model": "...", "prompt": "..."}}

它**不生成视频**，按次计费。典型用法是把输出接到下面的文生视频节点当提示词用。
"""

from __future__ import annotations

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_prompt,
        extract_task_id,
    )
    from .xhcy_v3 import as_v3_node
    from .xhcy_video_base import (
        audio_input_to_uri,
        image_tensor_to_uri,
        reset_material_budget,
        video_input_to_uri,
        _int_param,
    )
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_prompt,
        extract_task_id,
    )
    from xhcy_v3 import as_v3_node  # type: ignore
    from xhcy_video_base import (  # type: ignore
        audio_input_to_uri,
        image_tensor_to_uri,
        reset_material_budget,
        video_input_to_uri,
        _int_param,
    )

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3

_DURATION_LOW, _DURATION_HIGH = 4, 30

_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"]


class XHCYMiniMaxH3ContextIR:
    """MiniMax H3 Context-IR — turn a rough idea into a production-ready prompt."""

    VARIANT_MODELS = ["MiniMax-H3"]

    CATEGORY = "XHCY/Video"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("enhanced_prompt", "status", "task_id")
    FUNCTION = "enhance"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict = {}
        for i in range(1, MAX_REF_IMAGES + 1):
            optional[f"image{i}"] = (
                "IMAGE",
                {"tooltip": f"参考图 #{i}。接了就按「图像 + 文字」做增强；不接任何素材就是纯文本增强。"},
            )
        for i in range(1, MAX_REF_VIDEOS + 1):
            optional[f"video{i}"] = (
                "VIDEO",
                {"tooltip": f"参考视频 #{i}（多模态增强）。素材以数据流内嵌上传。"},
            )
        for i in range(1, MAX_REF_AUDIOS + 1):
            optional[f"audio{i}"] = (
                "AUDIO",
                {"tooltip": f"参考音频 #{i}（多模态增强）。"},
            )

        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "你现在的想法/草稿描述，越具体结果越准。留空会直接报错。",
                    },
                ),
                "model": (
                    list(cls.VARIANT_MODELS),
                    {
                        "default": cls.VARIANT_MODELS[0],
                        "tooltip": "Context-IR 是 H3 专属能力，H3-Lite 不支持。",
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "defaultInput": True,
                        "tooltip": "XHCY AI 访问密钥。每个节点单独填。",
                    },
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 60,
                        "tooltip": (
                            "秒。这只是上游要求的必填项（增强结果与它无关，费用也按次收），"
                            "超出 4～30 秒会自动收进区间。"
                        ),
                    },
                ),
                "ratio": (
                    list(_RATIOS),
                    {
                        "default": "16:9",
                        "tooltip": (
                            "画面比例。纯文本增强时**必须**显式指定，上游会拒绝 adaptive；"
                            "接了图片等素材才可以用 adaptive。"
                        ),
                    },
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
            "optional": optional,
        }

    # ------------------------------------------------------------------ #

    @classmethod
    def build_content(cls, prompt: str, kwargs: dict) -> tuple[list, bool]:
        content: list = [{"type": "text", "text": prompt}]
        has_media = False

        for i in range(1, MAX_REF_IMAGES + 1):
            batch = kwargs.get(f"image{i}")
            if batch is None:
                continue
            if not hasattr(batch, "ndim"):
                raise XHCYError(f"image{i} 必须是 ComfyUI 的 IMAGE 输入")
            items = batch if batch.ndim == 4 else batch.unsqueeze(0)
            for item in items:
                content.append(
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": image_tensor_to_uri(item)},
                    }
                )
                has_media = True

        for i in range(1, MAX_REF_VIDEOS + 1):
            video = kwargs.get(f"video{i}")
            if video is None:
                continue
            content.append(
                {
                    "type": "video_url",
                    "role": "reference_video",
                    "video_url": {"url": video_input_to_uri(video)},
                }
            )
            has_media = True

        for i in range(1, MAX_REF_AUDIOS + 1):
            audio = kwargs.get(f"audio{i}")
            if audio is None:
                continue
            content.append(
                {
                    "type": "audio_url",
                    "role": "reference_audio",
                    "audio_url": {"url": audio_input_to_uri(audio)},
                }
            )
            has_media = True

        return content, has_media

    # ------------------------------------------------------------------ #

    def enhance(self, prompt, model, api_key, duration, ratio, base_url=DEFAULT_BASE_URL, **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        if self.VARIANT_MODELS and model not in self.VARIANT_MODELS:
            raise XHCYError(f"未知的模型：{model}")

        seconds = min(max(_int_param(duration, "时长（秒）", 1, 60), _DURATION_LOW), _DURATION_HIGH)

        reset_material_budget()
        content, has_media = self.build_content(prompt, kwargs)

        # 上游在「没有素材可参照」时拒绝 adaptive：没有图，就没有可对齐的画幅。
        if not has_media and ratio == "adaptive":
            raise XHCYError(
                "纯文本增强时不能选 adaptive 比例（上游会拒绝，因为没有图可以对齐画幅）。"
                "请改成 16:9、1:1 这类明确的比例；接了图片素材后才可以用 adaptive。"
            )

        payload: dict = {"model": model, "content": content, "duration": seconds}
        if ratio:
            payload["ratio"] = ratio

        client = XHCYClient(api_key, base_url)
        response = client.submit_context_ir(payload)
        enhanced = extract_prompt(response)
        if not enhanced:
            raise XHCYError("服务端没有返回增强后的提示词")

        task_id = extract_task_id(response) or "-"
        media_note = "多模态增强（含素材）" if has_media else "纯文本增强"
        summary = (
            f"XHCY Context-IR 增强成功\n"
            f"方式：{media_note}\n"
            f"模型：{model}\n"
            f"比例：{ratio}\n"
            f"任务：{task_id}\n"
            f"提示词长度：{len(enhanced)} 字"
        )
        return (enhanced, summary, task_id)


NODE_CLASS_MAPPINGS = {
    "xhcy_h3_context_ir": as_v3_node(XHCYMiniMaxH3ContextIR, "xhcy_h3_context_ir", "XHCY MiniMax H3 Context-IR（提示词增强）"),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_h3_context_ir": "XHCY MiniMax H3 Context-IR（提示词增强）",
}
