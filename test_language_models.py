"""语言下拉、已下线模型，以及分析节点「无」角色。"""

import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import torch  # noqa: F401
except ModuleNotFoundError:
    torch = types.ModuleType("torch")
    torch.Tensor = type("Tensor", (), {})
    torch.nn = types.ModuleType("torch.nn")
    torch.nn.functional = types.ModuleType("torch.nn.functional")
    sys.modules["torch"] = torch
    sys.modules["torch.nn"] = torch.nn
    sys.modules["torch.nn.functional"] = torch.nn.functional

import nodes_analyze
import nodes_llm
from nodes_analyze import XHCYAnalyze
from nodes_llm import XHCYChat
from xhcy_client import XHCYError


ANALYZE_MODELS = [
    "gemini-3.8-flash",
    "gpt-6.1-sol",
    "kimi-k3.1-pro",
]
CHAT_MODELS = ANALYZE_MODELS + [
    "deepseek-v4.1-flash",
    "deepseek-v4.1-flash-1017",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
]
DELISTED = [
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-opus-5-5",
]
SKILL_NAMES = [
    "通用创意助手",
    "H3 视频导演",
    "广告创意策划",
    "分镜脚本师",
    "提示词工程师",
]


class _Batch:
    def __init__(self, count=1):
        self.ndim = 4
        self.count = count

    def __iter__(self):
        for _ in range(self.count):
            yield object()


class LanguageModelListTests(unittest.TestCase):
    def test_analyze_lists_only_three_vision_models(self):
        self.assertEqual(list(nodes_analyze.MODEL_CAPABILITY), ANALYZE_MODELS)
        self.assertEqual(set(nodes_analyze.MODEL_CAPABILITY.values()), {"vision"})
        self.assertEqual(nodes_analyze.MODEL_LIST, ANALYZE_MODELS)
        self.assertEqual(nodes_analyze.DEFAULT_MODEL, "gemini-3.8-flash")
        combo = XHCYAnalyze.INPUT_TYPES()["required"]["model"][0]
        self.assertEqual(combo, ANALYZE_MODELS + DELISTED)
        for model_id in (
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-v4.1-flash",
            "deepseek-v4.1-flash-1017",
            "gpt-image-2",
            "MiniMax-H3",
        ):
            self.assertNotIn(model_id, combo)

    def test_chat_lists_seven_public_ids_and_keeps_raw_delisted_values(self):
        self.assertEqual(nodes_llm.MODEL_LIST, CHAT_MODELS)
        self.assertEqual(nodes_llm.DEFAULT_MODEL, "gemini-3.8-flash")
        combo = XHCYChat.INPUT_TYPES()["required"]["model"][0]
        self.assertEqual(combo, CHAT_MODELS + DELISTED)
        self.assertEqual(combo[0], ANALYZE_MODELS[0])

    def test_dropdown_script_uses_the_same_ids(self):
        script = (ROOT / "web" / "xhcy_language_models.js").read_text(encoding="utf-8")
        start = script.index("[ANALYZE_NODE]: [")
        end = script.index("],", start)
        analyze_block = script[start:end]
        for model_id in ANALYZE_MODELS:
            self.assertIn(f'"{model_id}"', analyze_block)
        for model_id in (
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-v4.1-flash",
            "deepseek-v4.1-flash-1017",
        ):
            self.assertNotIn(model_id, analyze_block)
        for model_id in CHAT_MODELS + DELISTED:
            self.assertIn(f'"{model_id}"', script)
        self.assertIn("（不可用，请重选）", script)

    def test_skill_none_is_first_and_default_is_unchanged(self):
        self.assertEqual(nodes_analyze.SKILL_LIST[0], "无")
        self.assertEqual(nodes_analyze.DEFAULT_SKILL, "通用创意助手")
        self.assertNotIn("无", nodes_analyze.SKILLS)
        self.assertEqual(list(nodes_analyze.SKILLS), SKILL_NAMES)
        skill = XHCYAnalyze.INPUT_TYPES()["required"]["skill"]
        self.assertEqual(skill[0][0], "无")
        self.assertEqual(skill[1]["default"], "通用创意助手")

    def test_validation_accepts_a_saved_id_without_replacing_it(self):
        self.assertTrue(XHCYAnalyze.VALIDATE_INPUTS("claude-fable-5"))
        self.assertTrue(XHCYAnalyze.VALIDATE_INPUTS("not-published-anymore"))
        self.assertTrue(XHCYChat.VALIDATE_INPUTS("claude-opus-5-5"))


class _Capture:
    def __init__(self, text):
        self.text = text
        self.payloads = []
        self.calls = 0

    def install(self, module):
        capture = self

        class FakeClient:
            def __init__(self, api_key, base_url):
                capture.calls += 1

            def chat(self, payload):
                capture.payloads.append(payload)
                return {"choices": [{"message": {"content": capture.text}}]}

        module.XHCYClient = FakeClient
        return self


class AnalyzeBehaviorTests(unittest.TestCase):
    def test_delisted_and_unknown_models_ask_for_a_current_one(self):
        node = XHCYAnalyze()
        capture = _Capture("不应该发出").install(nodes_analyze)
        for model_id in DELISTED + ["some-old-model"]:
            with self.assertRaises(XHCYError) as caught:
                node.analyze("画一只猫", model_id, "无", "k", "", 0.6, 256)
            message = str(caught.exception)
            self.assertIn("请重新选择一个当前模型", message)
            self.assertIn(model_id, message)
            self.assertIn("gemini-3.8-flash", message)
            self.assertNotIn("deepseek-v4-flash", message)
        self.assertEqual(capture.calls, 0)

    def test_no_skill_sends_only_requirement_extra_and_frames(self):
        node = XHCYAnalyze()
        capture = _Capture("没有分段的原文").install(nodes_analyze)
        nodes_analyze.tensor_to_data_uri = lambda item: "data:image/png;base64,QQ=="
        prompt, storyboard, params, analysis, status = node.analyze(
            "只要这一句",
            "gemini-3.8-flash",
            "无",
            "k",
            "再冷一点",
            0.6,
            256,
            image1=_Batch(),
        )
        self.assertEqual(len(capture.payloads), 1)
        messages = capture.payloads[0]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user"])
        content = messages[0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "只要这一句\n\n再冷一点"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertNotIn("output_contract", str(messages))
        self.assertNotIn("【素材】", str(messages))
        self.assertNotIn("【额外要求】", str(messages))
        self.assertNotIn("你是一名", str(messages))
        self.assertEqual(prompt, "没有分段的原文")
        self.assertEqual(storyboard, "")
        self.assertEqual(params, "")
        self.assertIn("原文", analysis)
        self.assertIn("角色：无", status)
        self.assertNotIn("请按图片出现的顺序理解它们", str(messages))

    def test_no_skill_with_multiple_images_keeps_order_note_only(self):
        node = XHCYAnalyze()
        capture = _Capture("没有分段的原文").install(nodes_analyze)
        nodes_analyze.tensor_to_data_uri = lambda item: "data:image/png;base64,QQ=="
        node.analyze(
            "按顺序看",
            "kimi-k3.1-pro",
            "无",
            "k",
            "不要发明情节",
            0.6,
            256,
            image1=_Batch(2),
        )
        messages = capture.payloads[0]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user"])
        text = messages[0]["content"][0]["text"]
        self.assertIn("按顺序看", text)
        self.assertIn("不要发明情节", text)
        self.assertIn("请按图片出现的顺序理解它们（Image 1、Image 2 …）。", text)
        self.assertEqual(
            [part["type"] for part in messages[0]["content"][1:]],
            ["image_url", "image_url"],
        )
        blob = str(messages)
        self.assertNotIn("output_contract", blob)
        self.assertNotIn("【素材】", blob)
        self.assertNotIn("【额外要求】", blob)
        self.assertNotIn("你是一名", blob)
        self.assertNotIn("视觉创作导演", blob)

    def test_existing_skill_still_sends_its_methodology(self):
        node = XHCYAnalyze()
        capture = _Capture(
            "## 提示词\n一只猫\n\n## 参数建议\n比例=1:1\n\n## 分析说明\n清楚"
        ).install(nodes_analyze)
        prompt, storyboard, params, analysis, _status = node.analyze(
            "画一只猫",
            "gpt-6.1-sol",
            "通用创意助手",
            "k",
            "",
            0.6,
            256,
        )
        messages = capture.payloads[0]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("视觉创作导演", messages[0]["content"])
        self.assertIn("## 提示词", messages[1]["content"])
        self.assertIn("【用户需求】", messages[1]["content"])
        self.assertIn("画一只猫", messages[1]["content"])
        self.assertEqual(prompt, "一只猫")
        self.assertEqual(params, "比例=1:1")
        self.assertEqual(analysis, "清楚")
        self.assertEqual(storyboard, "")


class ChatBehaviorTests(unittest.TestCase):
    def test_delisted_model_is_not_sent(self):
        node = XHCYChat()
        capture = _Capture("不应该发出").install(nodes_llm)
        with self.assertRaises(XHCYError) as caught:
            node.chat("你好", "claude-fable-5", "k", "", 0.7, 0)
        self.assertIn("请重新选择一个当前模型", str(caught.exception))
        self.assertIn("kimi-k3.1-pro", str(caught.exception))
        self.assertIn("deepseek-v4-pro", str(caught.exception))
        self.assertEqual(capture.calls, 0)

    def test_current_model_is_passed_through_unchanged(self):
        node = XHCYChat()
        capture = _Capture("好的").install(nodes_llm)
        text, status = node.chat("你好", "deepseek-v4-flash", "k", "", 0.7, 0)
        self.assertEqual(text, "好的")
        self.assertEqual(capture.payloads[0]["model"], "deepseek-v4-flash")
        self.assertIn("deepseek-v4-flash", status)


if __name__ == "__main__":
    unittest.main()
