"""XHCY AI text / chat node.

语言模型下拉已于 2026-11-16 按
GET https://ai.xhcyai.org/api/public-models 同步，只保留当时公开的语言 / 对话模型。
已移除不再发布的 claude-fable-5、claude-fable-5-1、claude-opus-5-5，
并加入 kimi-k3.1-pro。

这些模型走 OpenAI 兼容的 ``POST /v1/chat/completions``。
一个节点用下拉切换。接了图片时会组装成多模态消息
（``content`` 数组 + data URI）。这条路径只有视觉模型支持；
纯文本模型接了图会被拒绝。

已下线的模型仍以原始 ID 留在下拉值里，避免旧工作流被改成别的模型。
运行时会要求重新选择当前模型。

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
    from .xhcy_credentials import resolve_credentials
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_chat_text,
    )
    from xhcy_image_base import tensor_to_data_uri  # type: ignore
    from xhcy_credentials import resolve_credentials  # type: ignore


# 2026-11-16 按 GET https://ai.xhcyai.org/api/public-models 同步。
# 只保留当时公开的语言 / 对话模型。顺序与分析节点里重叠的三项一致。
MODEL_LIST = [
    "gemini-3.8-flash",
    "gpt-6.1-sol",
    "kimi-k3.1-pro",
    "deepseek-v4.1-flash",
    "deepseek-v4.1-flash-1017",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
]

DEFAULT_MODEL = "gemini-3.8-flash"

# 值必须是原始 ID，这样已保存的工作流不会被改成默认模型。
DELISTED_MODEL_IDS = (
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-opus-5-5",
)


def model_combo_values() -> list[str]:
    values = list(MODEL_LIST)
    for model_id in DELISTED_MODEL_IDS:
        if model_id not in values:
            values.append(model_id)
    return values


def unavailable_model_message(model, current_ids) -> str:
    name = model if isinstance(model, str) and model.strip() else "（空）"
    return (
        f"模型「{name}」已不在当前可用清单中，请重新选择一个当前模型。\n"
        f"当前可用：{' / '.join(current_ids)}"
    )


# 视觉 / 文本按公开模型能力区分，站点清单是最终依据。
_VISION_HINT = (
    "接了图片就会按多模态消息发送（图片转成 data URI 内嵌）。"
    "只有视觉模型支持；纯文本模型接了图会被拒绝。"
    "不在当前清单里的模型会保留原来的 ID，运行前请改选一个当前模型。"
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
                        "tooltip": "你要问模型的内容。留空会直接报错，不会发出请求。",
                    },
                ),
                "model": (
                    model_combo_values(),
                    {
                        "default": DEFAULT_MODEL,
                        "tooltip": "当前公开的语言 / 对话模型。已下线的模型会保留原 ID，运行前请重选。",
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

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        # 收下任意已保存的模型 ID，避免校验阶段把它判掉或换成默认值。
        # 不在当前清单里的 ID 由 chat() 用中文要求重选。
        return True

    # ------------------------------------------------------------------ #

    def chat(self, prompt, model, api_key, system, temperature, max_tokens,
             base_url=DEFAULT_BASE_URL, **kwargs):
        prompt = (prompt or "").strip()
        if not prompt:
            raise XHCYError("提示词（prompt）不能为空")
        if model not in MODEL_LIST:
            raise XHCYError(unavailable_model_message(model, MODEL_LIST))

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

        api_key, base_url = resolve_credentials(api_key, base_url)
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
