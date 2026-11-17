"""工作流重新加载时，语言节点和余额脚本不得再进入同一轮配置。"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LANGUAGE_SCRIPT = ROOT / "web" / "xhcy_language_models.js"
BALANCE_SCRIPT = ROOT / "web" / "xinghuo_nano_banana_balance.js"

RUNNER = r"""
globalThis.document = {
    createElement() {
        return {
            getContext() {
                return {
                    font: "",
                    measureText(text) {
                        return { width: String(text).length * 8 };
                    },
                };
            },
        };
    },
    getElementById() { return null; },
    querySelector() { return null; },
    head: { appendChild() {} },
    body: null,
};
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(0), 16);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);

const { app } = await import("./scripts/app.js");
await import("./extensions/comfyui-xhcyai/xhcy_language_models.js");
await import("./extensions/comfyui-xhcyai/xinghuo_nano_banana_balance.js");

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

function track(node, proto) {
    let depth = 0;
    node.configureDepth = 0;
    node.configureEntries = 0;
    node.onConfigure = function (info) {
        node.configureEntries += 1;
        depth += 1;
        node.configureDepth = Math.max(node.configureDepth, depth);
        try {
            return proto.onConfigure.call(node, info);
        } finally {
            depth -= 1;
        }
    };
}

const language = app.extensions.find((item) => item.name === "xhcy.languageModels");
function LanguageNode() {}
let originalCalls = 0;
LanguageNode.prototype.onConfigure = function () {
    originalCalls += 1;
    return "configured";
};
await language.beforeRegisterNodeDef(LanguageNode, { name: "xhcy_analyze" });

function languageNode(saved) {
    const info = {
        widgets_values: ["通用创意助手", saved],
        widgets_values_named: { model: saved },
    };
    const node = {
        comfyClass: "xhcy_analyze",
        type: "xhcy_analyze",
        id: 7,
        size: [200, 120],
        __info: info,
        setSize(size) {
            this.size = size.slice();
            this.onResize?.(this.size);
            this.onConfigure?.(info);
        },
    };
    let values = ["gemini-3.8-flash", "gpt-6.1-sol", "kimi-k3.1-pro"];
    const options = {};
    Object.defineProperty(options, "values", {
        configurable: true,
        enumerable: true,
        get() { return values; },
        set(next) {
            values = next;
            node.onConfigure?.(info);
        },
    });
    let stored = "gemini-3.8-flash";
    const model = { name: "model", type: "combo", options, serialize: true };
    Object.defineProperty(model, "value", {
        configurable: true,
        enumerable: true,
        get() { return stored; },
        set(next) {
            stored = next;
            node.onConfigure?.(info);
        },
    });
    node.widgets = [{ name: "skill", value: "通用创意助手" }, model];
    track(node, LanguageNode.prototype);
    return node;
}

const delisted = languageNode("claude-fable-5");
const delistedResult = delisted.onConfigure(delisted.__info);
const delistedModel = delisted.widgets[1];
assert(delistedResult === "configured", "original configure result was dropped");
assert(originalCalls === 1, "original configure ran more than once");
assert(delistedModel.value === "claude-fable-5", "delisted id was rewritten");
assert(delistedModel.options.values.includes("claude-fable-5"), "delisted id is not selectable");
assert(
    delistedModel.options.getOptionLabel("claude-fable-5") === "claude-fable-5（不可用，请重选）",
    "delisted label changed",
);
assert(
    delistedModel.options.getOptionLabel("gemini-3.8-flash") === "gemini-3.8-flash",
    "current model label changed",
);
assert(delisted.configureDepth < 8, "language configure recursed: " + delisted.configureDepth);

const current = languageNode("gemini-3.8-flash");
current.onConfigure(current.__info);
assert(current.widgets[1].value === "gemini-3.8-flash", "current model was rewritten");
assert(current.configureDepth < 8, "current model configure recursed");

const positionalInfo = { widgets_values: ["hello", "claude-opus-5-5"] };
const positional = languageNode("claude-opus-5-5");
positional.__info = positionalInfo;
positional.onConfigure = function (info) {
    positional.configureEntries += 1;
    return LanguageNode.prototype.onConfigure.call(positional, info);
};
positional.onConfigure(positionalInfo);
assert(positional.widgets[1].value === "claude-opus-5-5", "positional saved id was dropped");

const balance = app.extensions.find((item) => item.name === "xinghuo.nano_banana.balance.v3");
function BalanceNode() {}
await balance.beforeRegisterNodeDef(BalanceNode, { name: "comfyui_xinghuo_nano_banana_v3" });

function balanceNode(widgets, config) {
    const node = {
        type: "comfyui_xinghuo_nano_banana_v3",
        id: 9,
        size: [300, 180],
        widgets: [],
        setDirtyCanvas() {},
        computeSize() { return [300, 240]; },
        setSize(size) { this.size = size.slice(); },
    };
    node.widgets = widgets.map(([name, initial]) => {
        let stored = initial;
        const item = { name, options: {}, serialize: true };
        Object.defineProperty(item, "value", {
            configurable: true,
            enumerable: true,
            get() { return stored; },
            set(next) {
                stored = next;
                node.onConfigure?.(config);
            },
        });
        return item;
    });
    track(node, BalanceNode.prototype);
    return node;
}

const legacyConfig = {
    widgets_values: ["restored-workflow-value", "1:1", "16:9", "2K", "async", "nope", 0],
};
const legacy = balanceNode([
    ["api_key", "restored-workflow-value"],
    ["aspect_ratio", "1:1"],
    ["image_size", "16:9"],
    ["reply_type", "2K"],
    ["max_poll_attempts", "nope"],
    ["poll_interval", 0],
], legacyConfig);
legacy.onConfigure(legacyConfig);
const read = (node, name) => node.widgets.find((item) => item.name === name).value;
assert(read(legacy, "api_key") === "", "api key was kept on the widget");
assert(legacy.widgets.find((item) => item.name === "api_key").serialize === false, "api key stays serialized");
assert(legacyConfig.widgets_values[0] === "", "restored api key stayed in the workflow snapshot");
assert(read(legacy, "aspect_ratio") === "16:9", "legacy aspect ratio was not repaired");
assert(read(legacy, "image_size") === "2K", "legacy image size was not repaired");
assert(read(legacy, "reply_type") === "async", "legacy reply type was not repaired");
assert(read(legacy, "max_poll_attempts") === 300, "invalid poll attempts were not normalized");
assert(read(legacy, "poll_interval") === 5, "invalid poll interval was not normalized");
assert(legacy.configureDepth < 8, "balance configure recursed: " + legacy.configureDepth);

const shortConfig = { widgets_values: ["short", "1:1", "1K", "async", "async", 300, 5] };
const shortKey = balanceNode([
    ["api_key", "short"],
    ["aspect_ratio", "1:1"],
    ["image_size", "1K"],
    ["reply_type", "async"],
    ["max_poll_attempts", 300],
    ["poll_interval", 5],
], shortConfig);
shortKey.onConfigure(shortConfig);
assert(read(shortKey, "api_key") === "", "short api key was not cleared");
assert(shortConfig.widgets_values[0] === "short", "short snapshot value was rewritten");
assert(read(shortKey, "aspect_ratio") === "1:1", "valid ratio changed");
assert(read(shortKey, "image_size") === "1K", "valid size changed");

await new Promise((resolve) => setTimeout(resolve, 800));
assert(delistedModel.value === "claude-fable-5", "deferred pass rewrote the delisted id");
assert(delistedModel.options.values.includes("claude-fable-5"), "deferred pass dropped the delisted id");
assert(read(legacy, "api_key") === "", "deferred pass restored the api key");
assert(read(legacy, "aspect_ratio") === "16:9", "deferred pass undid the ratio repair");
assert(read(legacy, "image_size") === "2K", "deferred pass undid the size repair");
assert(read(legacy, "reply_type") === "async", "deferred pass undid the reply repair");
const afterWait = delisted.configureEntries + legacy.configureEntries;
await new Promise((resolve) => setTimeout(resolve, 200));
assert(
    delisted.configureEntries + legacy.configureEntries === afterWait,
    "configure kept scheduling itself",
);

console.log(JSON.stringify({
    languageDepth: delisted.configureDepth,
    languageEntries: delisted.configureEntries,
    balanceDepth: legacy.configureDepth,
    balanceEntries: legacy.configureEntries,
}));
"""


class WorkflowLoadReentrancyTests(unittest.TestCase):
    def test_configure_value_writes_do_not_recurse(self):
        node = shutil.which("node")
        if not node:
            self.fail("node is required to load the frontend scripts")

        work = Path(tempfile.mkdtemp(prefix="xhcy-reentrancy-"))
        try:
            script_dir = work / "extensions" / "comfyui-xhcyai"
            script_dir.mkdir(parents=True)
            (work / "scripts").mkdir()
            shutil.copyfile(LANGUAGE_SCRIPT, script_dir / "xhcy_language_models.js")
            shutil.copyfile(BALANCE_SCRIPT, script_dir / "xinghuo_nano_banana_balance.js")
            (work / "scripts" / "app.js").write_text(
                "export const app = { extensions: [], registerExtension(extension) { this.extensions.push(extension); }, graph: null, canvas: null };\n",
                encoding="utf-8",
            )
            runner = work / "runner.mjs"
            runner.write_text(RUNNER, encoding="utf-8")
            completed = subprocess.run(
                [node, str(runner)],
                cwd=work,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + "\n" + completed.stderr,
            )
            summary = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertLess(summary["languageDepth"], 8)
            self.assertLess(summary["balanceDepth"], 8)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
