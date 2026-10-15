"""XHCY AI text / chat node.

站点在 2026-10 新增了一批文本模型，全部走 OpenAI 兼容的
``POST /v1/chat/completions``：

    gpt-6.1-sol · claude-opus-5-5 · claude-fable-5 · claude-fable-5-1
    gemini-3.8-flash · gemini-3.1-pro · gemini-3-flash
    deepseek-v4.1-flash · MiniMax-Text-01 · MiniMax-VL-01 · abab5.5s-chat

一个节点覆盖全部，用下拉切换。接了图片输入时会组装成多模态消息
（``content`` 数组 + data URI），这条路径只有视觉模型支持
（例如 MiniMax-VL-01、gemini / claude / gpt 系列），纯文本模型接了图会被上游拒绝。

典型用法：把输出接到文生图 / 文生视频节点的提示词输入，让模型先帮你把想法写细。
"""

from __future__ import annotations

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_chat_text,
    )
    from .xhcy_image_base import tensor_to_data_uri
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_chat_text,
    )
    from xhcy_image_base import tensor_to_data_uri  # type: ignore


# 站点当前可用的文本模型（GET /v1/models，2026-10-15）
MODEL_LIST = [
    "deepseek-v4.1-flash",
    "gpt-6.1-sol",
    "claude-opus-5-5",
    "claude-fable-5",
    "claude-fable-5-1",
    "gemini-3.8-flash",
    "gemini-3.1-pro",
    "gemini-3-flash",
    "MiniMax-Text-01",
    "MiniMax-VL-01",
    "abab5.5s-chat",
]

DEFAULT_MODEL = "deepseek-v4.1-flash"

# 站点没有给出各模型的能力清单，这里按公开常识标注，仅用于提示
_VISION_HINT = (
    "接了图片就会按多模态消息发送（图片转成 data URI 内嵌）。"
    "只有视觉模型支持，例如 MiniMax-VL-01、gemini / claude / gpt 系列；"
    "纯文本模型接了图会被上游拒绝。"
)


class XHCYChat:
    """XHCY text model — chat completion, optionally with an image."""

    CATEGORY = "XHCY/Text"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "status")
    FUNCTION = "chat"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "你要问模型的内容。留空会直接报错，不会白白扣费。",
                    },
                ),
                "model": (
                    list(MODEL_LIST),
                    {"default": DEFAULT_MODEL, "tooltip": "站点上的文本/多模态模型。"},
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
                "system": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "系统提示词（角色设定），可以留空。",
                    },
                ),
                "temperature": (
                    "FLOAT",
                    {
                        "default": 0.7,
                        "min": 0.0,
                        "max": 2.0,
                        "step": 0.05,
                        "tooltip": "随机性。越低越稳定，越高越发散。",
                    },
                ),
                "max_tokens": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 65536,
                        "tooltip": "回复长度上限；0 表示不指定，交给服务端默认值。",
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
            "optional": {
                "image": ("IMAGE", {"tooltip": _VISION_HINT}),
            },
        }

    # ------------------------------------------------------------------ #

    def chat(self, prompt, model, api_key, system, temperature, max_tokens,
             base_url=DEFAULT_BASE_URL, **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        if MODEL_LIST and model not in MODEL_LIST:
            raise XHCYError(f"未知的模型：{model}")

        messages: list[dict] = []
        system_text = (system or "").strip()
        if system_text:
            messages.append({"role": "system", "content": system_text})

        batch = kwargs.get("image")
        if batch is not None:
            if not hasattr(batch, "ndim"):
                raise XHCYError("image 必须是 ComfyUI 的 IMAGE 输入")
            pieces: list[dict] = [{"type": "text", "text": prompt}]
            items = batch if batch.ndim == 4 else batch.unsqueeze(0)
            for item in items:
                pieces.append(
                    {"type": "image_url", "image_url": {"url": tensor_to_data_uri(item)}}
                )
            messages.append({"role": "user", "content": pieces})
            mode_text = f"多模态（{len(items)} 张图）"
        else:
            messages.append({"role": "user", "content": prompt})
            mode_text = "纯文本"

        payload: dict = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)

        client = XHCYClient(api_key, base_url)
        response = client.chat(payload)
        text = extract_chat_text(response)
        if not text.strip():
            raise XHCYError("服务端没有返回文本内容")

        usage = response.get("usage")
        usage_text = ""
        if isinstance(usage, dict) and usage:
            usage_text = (
                f"\n用量：输入 {usage.get('prompt_tokens', '-')} / "
                f"输出 {usage.get('completion_tokens', '-')} tokens"
            )
        summary = (
            f"XHCY 对话成功\n"
            f"模式：{mode_text}\n"
            f"模型：{model}\n"
            f"回复长度：{len(text)} 字{usage_text}"
        )
        return (text, summary)


NODE_CLASS_MAPPINGS = {
    "xhcy_chat": XHCYChat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_chat": "XHCY 文本 / 对话（LLM）",
}
