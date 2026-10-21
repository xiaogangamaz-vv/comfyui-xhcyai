"""XHCY AI 智能分析节点（方案 A）。

定位
----
原来的 ``XHCY/Text`` 节点是「一问一答」：给一句提示词，出一段文字。
这个节点把能力往上提一层：**上传素材 + 选角色 + 说需求 → 产出能直接接给
下游节点的内容**（提示词 / 分镜 / 建议参数）。

设计思路借鉴 ComfyTV 的 Agent Skill：方法论写进 ``SKILL`` 字典，
模型按角色说明产出结构化结果，而不是自由发挥。

关键约束（都已核实）
--------------------
* 站点聊天通道 ``/v1/chat/completions`` 只认 ``image_url``，**不认
  ``video_url``**（源码里 ``video_url`` 只存在于视频适配器）。所以视频
  要先抽帧成图片再送进模型。
* 只有视觉模型能吃图。纯文本模型接了图会被上游拒绝，所以节点会按
  所选模型自动决定要不要附图，并在报错时给清楚的人话说明。
* 密钥由用户在节点上单独填，不做加密。

输出
----
``prompt``      给文生图 / 文生视频用的提示词
``storyboard``  分镜（若角色要求）
``params``      建议参数（分辨率 / 时长 / 比例等）
``analysis``    模型的分析说明
``status``      运行摘要
"""

from __future__ import annotations

import json

try:
    from .xhcy_client import (
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_chat_text,
    )
    from .xhcy_frames import video_to_frames
    from .xhcy_image_base import tensor_to_data_uri
    from .xhcy_v3 import as_v3_node
except ImportError:  # allow running this file standalone for debugging
    from xhcy_client import (  # type: ignore
        DEFAULT_BASE_URL,
        XHCYClient,
        XHCYError,
        extract_chat_text,
    )
    from xhcy_frames import video_to_frames  # type: ignore
    from xhcy_image_base import tensor_to_data_uri  # type: ignore
    from xhcy_v3 import as_v3_node  # type: ignore


# ---------------------------------------------------------------------- #
# 模型清单
# ---------------------------------------------------------------------- #

# 站点当前登记的文本模型。是否支持看图按公开常识标注，
# 实际以站点渠道为准；选错时节点会用人话报错而不是把失败藏起来。
#
# ⚠️ 2026-10-21 实测（从生产机线路，避免本机 Cloudflare 拦截）：
#   可用：gemini-3-flash / claude-fable-5 / claude-fable-5-1 /
#         claude-opus-5-5 / gpt-6.1-sol
#   不可用：gemini-3.8-flash、gemini-3.1-pro（渠道不可用）、
#           deepseek-v4.1-flash（渠道不可用）、
#           MiniMax-Text-01 / MiniMax-VL-01 / abab5.5s-chat（请求失败）
# 按「下拉里只放真正能用的选项」的原则，这里只列实测通过的。
MODEL_CAPABILITY = {
    "gemini-3-flash": "vision",
    "claude-fable-5": "vision",
    "claude-fable-5-1": "vision",
    "claude-opus-5-5": "vision",
    "gpt-6.1-sol": "vision",
}

MODEL_LIST = list(MODEL_CAPABILITY.keys())
DEFAULT_MODEL = "gemini-3-flash"

# 站点若临时不可用，可用这里的顺序做降级提示
VISION_HINT = (
    "只有视觉模型能看图。下面列的都是实测可用的视觉模型，"
    "接了素材会按多模态消息发送。"
)

# 报错时列给用户看的可选视觉模型
VISION_MODELS_HINT = " / ".join(
    m for m in MODEL_CAPABILITY if MODEL_CAPABILITY[m] == "vision"
)


# ---------------------------------------------------------------------- #
# 角色说明书（对应 ComfyTV 的 skill 思路）
# ---------------------------------------------------------------------- #

# 每个角色 = 一段方法论 + 一份输出契约。
# 模型被要求**按固定格式**输出，我们再把格式拆成多个输出口。

SKILLS: dict[str, dict] = {
    "通用创意助手": {
        "summary": "把想法说清楚，适合给文生图 / 文生视频写提示词。",
        "system": (
            "你是一名资深的 AI 视觉创作导演。用户会给你需求和参考素材，"
            "你的任务是把它变成可以直接用于生成模型的提示词。\n\n"
            "要求：\n"
            "1. 提示词用中文，描述具体的画面内容、镜头、光线、风格、氛围；\n"
            "2. 不要写抽象形容词堆砌（不要「震撼」「绝美」），要写可看见的东西；\n"
            "3. 有参考素材时，先用一句话概括素材的主体特征，再基于它写提示词；\n"
            "4. 只输出需要的部分，不要寒暄。"
        ),
        "output_contract": (
            "请严格按下面三段输出，每段标题原样保留：\n\n"
            "## 提示词\n"
            "（一段可以直接复制使用的提示词）\n\n"
            "## 参数建议\n"
            "（形如 比例=16:9；时长=5秒；风格=电影感，写成一行行 key=value）\n\n"
            "## 分析说明\n"
            "（两三句话，说明你怎么理解用户需求、素材里有什么）"
        ),
    },
    "H3 视频导演": {
        "summary": "专门给 MiniMax H3 写生产级提示词，含分镜。",
        "system": (
            "你是一名电影导演，专精 MiniMax H3 视频生成。"
            "用户会给你需求和参考素材，你要产出可以直接喂给 H3 的镜头设计。\n\n"
            "方法论要点：\n"
            "1. 先锁定这一镜的戏剧目的：信息、情绪、关系、空间上发生了什么变化；\n"
            "2. 生成模式：T2VA（纯文字探索）/ I2VA（有确定首帧）/ "
            "FL2VA（有首尾帧需要连续运动）/ L2VA（需要收敛到某帧）/ "
            "Ref2VA（多张参考图分别控制身份、场景、道具、动作、镜头、风格）；\n"
            "3. 参考素材分工排序：身份 > 场景布局 > 道具状态 > 动作姿态 > 镜头示例 > 风格装饰；\n"
            "4. 导演控制项要具体：机位与高度、景别、运镜（方向/幅度/速度/停点）、"
            "人物表演（视线、呼吸、肩膀、双手、重心）、物理反馈（重力、动量、接触、"
            "衣料与头发惯性）、光线（来源方向、色温、对比）、环境声与音效；\n"
            "5. 连续性台账：角色外观、道具状态、场景方位、光线方向必须前后一致。"
        ),
        "output_contract": (
            "请严格按下面四段输出，每段标题原样保留：\n\n"
            "## 提示词\n"
            "（H3 提示词正文，包含模式选择、参考图分工、镜头与表演控制）\n\n"
            "## 分镜\n"
            "（逐镜列表，每镜包含：镜号、时长、戏剧目的、景别与机位、"
            "起止状态、运镜、表演与物理反馈、参考素材标注、已知风险）\n\n"
            "## 参数建议\n"
            "（比例=；时长=秒；分辨率=，每行一个 key=value）\n\n"
            "## 分析说明\n"
            "（说明素材可用性、连续性台账要点、潜在风险）"
        ),
    },
    "广告创意策划": {
        "summary": "从商品素材出发，产出卖点、脚本和投放文案。",
        "system": (
            "你是一名广告创意策划。用户给你商品或场景素材和一句需求，"
            "你要产出可以直接用的广告方案。\n\n"
            "要求：\n"
            "1. 先提炼素材里真实存在的卖点，不要编造功能或功效；\n"
            "2. 给出 3 个不同方向的创意角度（如 场景化 / 痛点式 / 反差式），"
            "彼此要有实质区别，不是同义改写；\n"
            "3. 选中的方向再写完整脚本（15 秒或 30 秒，分镜 + 旁白 + 字幕）；\n"
            "4. 每个方向都要写清它适合的平台与人群。"
        ),
        "output_contract": (
            "请严格按下面四段输出，每段标题原样保留：\n\n"
            "## 提示词\n"
            "（选定方向的完整脚本，含分镜时间轴、旁白、字幕）\n\n"
            "## 分镜\n"
            "（3 个创意方向的对比清单，各写清角度、平台、人群、风险）\n\n"
            "## 参数建议\n"
            "（建议时长、比例、发布平台，每行一个 key=value）\n\n"
            "## 分析说明\n"
            "（素材里能提炼出什么卖点，哪些是推测而非事实）"
        ),
    },
    "分镜脚本师": {
        "summary": "把一段文字拆成可拍摄/可生成的分镜表。",
        "system": (
            "你是一名分镜师。用户给你一段文字或一堆素材，"
            "你要把它拆成逐镜分镜表。\n\n"
            "要求：\n"
            "1. 每镜必须写清：镜号、时长、景别、机位高度、"
            "画面内容、人物动作、运镜、光线、声音、转场方式；\n"
            "2. 镜头之间要有动因——为什么切、怎么接；\n"
            "3. 开头 3 秒必须抓人，结尾要有落点；\n"
            "4. 总时长要符合用户给的约束。"
        ),
        "output_contract": (
            "请严格按下面三段输出，每段标题原样保留：\n\n"
            "## 提示词\n"
            "（整体创意概述 + 风格基调）\n\n"
            "## 分镜\n"
            "（分镜表，每镜一段，用「镜号 / 时长 / 景别 / 画面 / 动作 / "
            "运镜 / 光线 / 声音 / 转场」逐项列出）\n\n"
            "## 参数建议\n"
            "（总时长、比例、每镜平均时长，每行一个 key=value）"
        ),
    },
    "提示词工程师": {
        "summary": "专门把模糊描述改写成高质量生成提示词。",
        "system": (
            "你是一名提示词工程师，擅长把模糊描述改写成高质量生成提示词。\n\n"
            "要求：\n"
            "1. 先指出原描述里含糊或缺失的地方（主体不清、风格不明、缺少光线与镜头）；\n"
            "2. 给出改写后的完整提示词，按「主体 → 动作 → 环境 → 构图 → 镜头 → "
            "光线 → 材质细节 → 风格 → 画质」的顺序组织；\n"
            "3. 再给一个「精简版」（适合参数受限的模型）；\n"
            "4. 有参考素材时说明它承担什么作用（身份 / 场景 / 风格 / 构图参考）。"
        ),
        "output_contract": (
            "请严格按下面三段输出，每段标题原样保留：\n\n"
            "## 提示词\n"
            "（完整版 + 精简版，用空行隔开）\n\n"
            "## 参数建议\n"
            "（建议的负面提示词要点、比例、每行一个 key=value）\n\n"
            "## 分析说明\n"
            "（原描述缺什么、你是怎么补的、参考素材的作用）"
        ),
    },
}

SKILL_LIST = list(SKILLS.keys())
DEFAULT_SKILL = "通用创意助手"


# ---------------------------------------------------------------------- #
# 节点
# ---------------------------------------------------------------------- #

MAX_IMAGES = 8
MAX_VIDEOS = 3
VIDEO_FRAME_COUNT = 4          # 每个视频抽几帧
VIDEO_FRAME_MAX_EDGE = 1024    # 抽帧后的长边上限
MAX_IMAGE_EDGE = 1536          # 参考图长边上限（base64 体积控制）


class XHCYAnalyze:
    """XHCY 智能分析 —— 素材 + 角色 → 结构化产出。"""

    NODE_ID = "xhcy_analyze"
    DISPLAY_NAME = "XHCY 智能分析（多模态·角色化）"
    CATEGORY = "XHCY/Text"
    DESCRIPTION = "上传素材 + 选角色 + 说需求 → 产出提示词 / 分镜 / 参数建议"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "storyboard", "params", "analysis", "status")
    FUNCTION = "analyze"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict = {}
        for i in range(1, MAX_IMAGES + 1):
            optional[f"image{i}"] = (
                "IMAGE",
                {"tooltip": f"参考图 #{i}。会随需求一起发给模型。"},
            )
        for i in range(1, MAX_VIDEOS + 1):
            optional[f"video{i}"] = (
                "VIDEO",
                {"tooltip": f"参考视频 #{i}。会先抽帧成图片再发给模型。"},
            )
        return {
            "required": {
                "requirement": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "你想做什么。用大白话说就行，模型会自己拆解。",
                    },
                ),
                "model": (
                    list(MODEL_LIST),
                    {
                        "default": DEFAULT_MODEL,
                        "tooltip": f"站点上的文本/多模态模型。{VISION_HINT}",
                    },
                ),
                "skill": (
                    list(SKILL_LIST),
                    {
                        "default": DEFAULT_SKILL,
                        "tooltip": "角色说明书，决定模型用什么方法论产出什么。",
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
                "extra_instruction": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "额外要求（可留空）。例如「只用冷色调」「控制在 8 秒内」。",
                    },
                ),
                "temperature": (
                    "FLOAT",
                    {
                        "default": 0.6,
                        "min": 0.0,
                        "max": 2.0,
                        "step": 0.05,
                        "tooltip": "随机性。创意任务建议 0.6~0.9，要稳定就调低。",
                    },
                ),
                "max_tokens": (
                    "INT",
                    {
                        "default": 4096,
                        "min": 256,
                        "max": 32768,
                        "tooltip": "回复长度上限。分镜类任务需要给足。",
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

    def analyze(self, requirement, model, skill, api_key, extra_instruction,
                temperature, max_tokens, base_url=DEFAULT_BASE_URL, **kwargs):
        requirement = (requirement or "").strip()
        if not requirement:
            raise XHCYError("需求（requirement）不能为空")
        if model not in MODEL_CAPABILITY:
            raise XHCYError(
                f"未知的模型：{model}\n"
                f"当前可用的模型：{' / '.join(MODEL_LIST)}"
            )
        if skill not in SKILLS:
            raise XHCYError(f"未知的角色：{skill}")

        capability = MODEL_CAPABILITY[model]
        spec = SKILLS[skill]

        # ---- 收集素材 ------------------------------------------------ #
        pieces: list[dict] = []
        image_count = 0
        frame_count = 0
        notes: list[str] = []

        for i in range(1, MAX_IMAGES + 1):
            batch = kwargs.get(f"image{i}")
            if batch is None:
                continue
            if not hasattr(batch, "ndim"):
                raise XHCYError(f"image{i} 必须是 ComfyUI 的 IMAGE 输入")
            items = batch if batch.ndim == 4 else batch.unsqueeze(0)
            for item in items:
                pieces.append(
                    {"type": "image_url", "image_url": {"url": tensor_to_data_uri(item)}}
                )
                image_count += 1

        for i in range(1, MAX_VIDEOS + 1):
            video = kwargs.get(f"video{i}")
            if video is None:
                continue
            frames = self._extract_frames(video, i)
            if not frames:
                notes.append(f"参考视频 #{i} 没能抽出帧，已跳过。")
                continue
            for frame in frames:
                pieces.append(
                    {"type": "image_url", "image_url": {"url": tensor_to_data_uri(frame)}}
                )
                frame_count += 1
            notes.append(f"参考视频 #{i} 抽了 {len(frames)} 帧。")

        if pieces and capability != "vision":
            raise XHCYError(
                f"模型 {model} 看不了图片，只能处理文字。"
                f"请换一个视觉模型（{VISION_MODELS_HINT}），"
                f"或者把素材断开只留文字。"
            )

        # ---- 组装请求 ------------------------------------------------ #
        material_note = ""
        if pieces:
            material_note = (
                f"\n\n【素材】一共 {image_count + frame_count} 张："
                f"参考图 {image_count} 张，视频抽帧 {frame_count} 张。"
                f"请按图片出现的顺序理解它们（Image 1、Image 2 …）。"
            )

        user_text = requirement + material_note
        if (extra_instruction or "").strip():
            user_text += f"\n\n【额外要求】\n{extra_instruction.strip()}"

        messages: list[dict] = [
            {"role": "system", "content": spec["system"]},
            {"role": "user", "content": spec["output_contract"] + "\n\n【用户需求】\n" + user_text},
        ]

        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if pieces:
            # 多模态：正文和素材放在同一条 user 消息里
            messages[1] = {
                "role": "user",
                "content": [{"type": "text", "text": spec["output_contract"] + "\n\n【用户需求】\n" + user_text}]
                + pieces,
            }

        client = XHCYClient(api_key, base_url)
        try:
            response = client.chat(payload)
        except XHCYError as exc:
            raise XHCYError(self._explain_error(exc, model)) from exc
        text = extract_chat_text(response)
        if not text.strip():
            raise XHCYError("服务端没有返回文本内容")

        prompt, storyboard, params, analysis = self._split_sections(text)

        usage = response.get("usage")
        usage_text = ""
        if isinstance(usage, dict) and usage:
            usage_text = (
                f"\n用量：输入 {usage.get('prompt_tokens', '-')} / "
                f"输出 {usage.get('completion_tokens', '-')} tokens"
            )
        summary = (
            f"XHCY 智能分析完成\n"
            f"角色：{skill}\n"
            f"模型：{model}（{'看图' if capability == 'vision' else '纯文本'}）\n"
            f"素材：图 {image_count} 张 + 视频抽帧 {frame_count} 张\n"
            f"输出长度：{len(text)} 字{usage_text}"
        )
        if notes:
            summary += "\n" + "\n".join(notes)

        return (prompt, storyboard, params, analysis, summary)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _explain_error(exc: Exception, model: str) -> str:
        """把站点的英文报错翻成人话，并指出下一步该做什么。"""
        raw = str(exc)
        low = raw.lower()

        if "authentication failed" in low or "invalid token" in low:
            return (
                f"模型 {model} 的上游渠道认证失败——站点里该渠道的密钥失效了。\n"
                f"这不是你的操作问题，需要站点管理员更新该渠道的 key。\n"
                f"（原始报错：{raw[:120]}）"
            )
        if "is unavailable" in low or "no available channel" in low:
            return (
                f"模型 {model} 现在没有可用渠道——上游临时不可用或该渠道被停用了。\n"
                f"可以换一个模型试试，或者等渠道恢复。\n"
                f"（原始报错：{raw[:120]}）"
            )
        if "insufficient" in low or "quota" in low or "403" in low:
            return (
                f"模型 {model} 调用被拒——多半是账户额度不足或权限不够。\n"
                f"请检查站点的额度与该模型的授权。\n"
                f"（原始报错：{raw[:120]}）"
            )
        if "upstream provider request failed" in low:
            return (
                f"模型 {model} 的上游拒绝了请求。常见原因：请求体太大"
                f"（素材太多）、参数不被接受，或上游临时故障。\n"
                f"可以少接几张图再试。\n"
                f"（原始报错：{raw[:120]}）"
            )
        return f"调用模型 {model} 失败：{raw[:200]}"

    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_frames(video, index: int) -> list:
        """从 ComfyUI VIDEO 对象里抽几帧，返回 IMAGE 张量列表。

        站点聊天通道不认 video_url，只能把视频变成图片送过去。
        """
        try:
            return video_to_frames(video, VIDEO_FRAME_COUNT, VIDEO_FRAME_MAX_EDGE)
        except XHCYError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise XHCYError(f"参考视频 #{index} 抽帧失败：{exc}") from exc

    @staticmethod
    def _split_sections(text: str) -> tuple[str, str, str, str]:
        """按「## 提示词 / ## 分镜 / ## 参数建议 / ## 分析说明」拆段。"""
        aliases = {
            "prompt": ("提示词",),
            "storyboard": ("分镜", "分镜表", "脚本"),
            "params": ("参数建议", "参数", "建议参数"),
            "analysis": ("分析说明", "分析", "说明"),
        }
        lines = text.splitlines()
        buckets: dict[str, list[str]] = {k: [] for k in aliases}
        current = None
        for line in lines:
            stripped = line.strip()
            matched = None
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip().rstrip(":：").strip()
                for key, names in aliases.items():
                    if heading in names:
                        matched = key
                        break
            if matched:
                current = matched
                continue
            if current:
                buckets[current].append(line)

        def join(key: str) -> str:
            return "\n".join(buckets[key]).strip()

        prompt = join("prompt")
        storyboard = join("storyboard")
        params = join("params")
        analysis = join("analysis")

        # 模型没按格式输出时，别让用户什么都拿不到
        if not prompt and not storyboard and not params:
            prompt = text.strip()
            analysis = "模型没有按约定的分段格式输出，已把原文放在「提示词」里。"
        return prompt, storyboard, params, analysis


NODE_CLASS_MAPPINGS = {
    "xhcy_analyze": as_v3_node(
        XHCYAnalyze, "xhcy_analyze", "XHCY 智能分析（多模态·角色化）"
    ),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "xhcy_analyze": "XHCY 智能分析（多模态·角色化）",
}
