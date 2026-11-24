import { app } from "../../scripts/app.js";

// 语言模型下拉：完整显示模型 ID，已下线的 ID 保持原值并标成不可用，
// 分析节点打开的菜单不要挡住下面的角色。
const ANALYZE_NODE = "xhcy_analyze";
const CHAT_NODE = "xhcy_chat";
const TARGET_NODES = new Set([ANALYZE_NODE, CHAT_NODE]);
const UNAVAILABLE_SUFFIX = "（不可用，请重选）";

const CURRENT_MODELS = {
    [ANALYZE_NODE]: ["gemini-3.8-flash", "gpt-6.1-sol", "kimi-k3.1-pro"],
    [CHAT_NODE]: [
        "gemini-3.8-flash",
        "gpt-6.1-sol",
        "kimi-k3.1-pro",
        "gpt-6.2-sol",
        "deepseek-v4.1-flash",
        "deepseek-v4.1-flash-1017",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ],
};

const DELISTED_MODEL_IDS = [
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-opus-5-5",
];

const measureCanvas = document.createElement("canvas");
const measureContext = measureCanvas.getContext("2d");

function nodeTypeName(node) {
    return node?.comfyClass || node?.type || "";
}

function labelFor(type, value) {
    const id = value == null ? "" : String(value);
    const current = CURRENT_MODELS[type] || [];
    if (current.indexOf(id) !== -1) return id;
    return `${id}${UNAVAILABLE_SUFFIX}`;
}

function looksLikeModelId(value) {
    return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value);
}

function modelWidget(node) {
    return node?.widgets?.find((widget) => widget.name === "model") || null;
}

function ownValues(widget) {
    const options = widget.options || (widget.options = {});
    if (options.__xhcyOwned) return options.values;
    // 替换 values 会同步再次进入配置。占位后直接返回，避免在标记完成前递归。
    if (options.__xhcyOwning) {
        return Array.isArray(options.values) ? options.values : [];
    }
    options.__xhcyOwning = true;
    try {
        const current = options.values;
        options.values = Array.isArray(current) ? current.slice() : [];
        options.__xhcyOwned = true;
        return options.values;
    } finally {
        options.__xhcyOwning = false;
    }
}

function savedModelValue(info) {
    const named = info?.widgets_values_named;
    if (named && typeof named.model === "string" && named.model) return named.model;
    const values = info?.widgets_values;
    if (!Array.isArray(values)) return "";
    const candidate = values[1];
    return looksLikeModelId(candidate) ? candidate : "";
}

function textWidth(text) {
    if (!measureContext) return String(text).length * 14;
    let widest = 0;
    for (const font of ["12px sans-serif", "14px sans-serif"]) {
        measureContext.font = font;
        widest = Math.max(widest, measureContext.measureText(String(text)).width);
    }
    return widest;
}

function minimumNodeWidth(node) {
    const type = nodeTypeName(node);
    const widget = modelWidget(node);
    const values = Array.isArray(widget?.options?.values)
        ? widget.options.values
        : (CURRENT_MODELS[type] || []).concat(DELISTED_MODEL_IDS);
    let widest = 0;
    for (const value of values) {
        widest = Math.max(widest, textWidth(labelFor(type, value)));
    }
    return Math.max(460, Math.ceil(widest + 210));
}

function findGraphNode(id) {
    const graph = app.graph;
    if (!graph) return null;
    if (typeof graph.getNodeById === "function") {
        const numeric = Number(id);
        const byNumber = Number.isNaN(numeric) ? null : graph.getNodeById(numeric);
        if (byNumber) return byNumber;
        const byId = graph.getNodeById(id);
        if (byId) return byId;
    }
    return (graph._nodes || []).find((node) => String(node.id) === String(id)) || null;
}

function nodeSelector(id) {
    const value = String(id).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return `[data-node-id="${value}"]`;
}

function whenNodeElement(node, apply) {
    let tries = 0;
    const tick = () => {
        const element = document.querySelector(nodeSelector(node.id));
        if (element) {
            apply(element);
            return;
        }
        if (tries++ < 40) requestAnimationFrame(tick);
    };
    tick();
}

function relaxModelField(nodeElement) {
    const trigger = nodeElement.querySelector('[aria-label="model"]');
    if (!trigger) return;
    const field = trigger.closest(".isolate") || trigger.parentElement;
    if (field) field.dataset.xhcyModelField = "1";
}

function applyWidth(node) {
    const minWidth = minimumNodeWidth(node);
    node.__xhcyMinWidth = minWidth;
    if (node.size && node.size[0] < minWidth && !node.__xhcyApplyingWidth) {
        node.__xhcyApplyingWidth = true;
        try {
            if (typeof node.setSize === "function") node.setSize([minWidth, node.size[1]]);
            else node.size[0] = minWidth;
        } finally {
            node.__xhcyApplyingWidth = false;
        }
    }
    whenNodeElement(node, (element) => {
        element.dataset.xhcyNode = nodeTypeName(node);
        element.style.setProperty("--xhcy-min-width", `${minWidth}px`);
        element.style.minWidth = `${minWidth}px`;
        relaxModelField(element);
    });
}

function enforceMinWidth(node) {
    applyWidth(node);
    if (node.__xhcyWidthPatched) return;
    node.__xhcyWidthPatched = true;
    const originalCompute = node.computeSize;
    node.computeSize = function computeSize() {
        const size = originalCompute
            ? originalCompute.apply(this, arguments)
            : [this.size?.[0] || 0, this.size?.[1] || 0];
        if (Array.isArray(size)) size[0] = Math.max(size[0], this.__xhcyMinWidth || 0);
        return size;
    };
    const originalResize = node.onResize;
    node.onResize = function onResize(size) {
        if (this.__xhcyResizing) {
            return originalResize ? originalResize.apply(this, arguments) : undefined;
        }
        this.__xhcyResizing = true;
        try {
            if (size && this.__xhcyMinWidth && size[0] < this.__xhcyMinWidth) {
                size[0] = this.__xhcyMinWidth;
            }
            return originalResize ? originalResize.apply(this, arguments) : undefined;
        } finally {
            this.__xhcyResizing = false;
        }
    };
}

function configureModelWidget(node) {
    const widget = modelWidget(node);
    if (!widget) return;
    const options = widget.options || (widget.options = {});
    const type = nodeTypeName(node);
    options.getOptionLabel = (value) => labelFor(type, value);
    ownValues(widget);
    enforceMinWidth(node);
}

function writeModelValue(widget, saved) {
    if (!widget || widget.value === saved || widget.__xhcyWritingValue) return;
    widget.__xhcyWritingValue = true;
    try {
        widget.value = saved;
    } finally {
        widget.__xhcyWritingValue = false;
    }
}

function retainSavedModel(node, saved) {
    if (!saved) return;
    const apply = () => {
        if (node.__xhcyRetainingModel) return;
        node.__xhcyRetainingModel = true;
        try {
            const widget = modelWidget(node);
            if (!widget) return;
            const values = ownValues(widget);
            if (!values.includes(saved)) values.push(saved);
            configureModelWidget(node);
            writeModelValue(widget, saved);
        } finally {
            node.__xhcyRetainingModel = false;
        }
    };
    apply();
    queueMicrotask(apply);
    requestAnimationFrame(apply);
    setTimeout(apply, 50);
}

function rectsOverlap(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function revealLabels(root) {
    root.style.setProperty("width", "max-content", "important");
    root.style.setProperty("min-width", "max-content", "important");
    root.style.setProperty("max-width", "none", "important");
    root.querySelectorAll(".truncate, .litemenu-entry").forEach((element) => {
        element.style.setProperty("white-space", "nowrap", "important");
        element.style.setProperty("overflow", "visible", "important");
        element.style.setProperty("text-overflow", "clip", "important");
        element.style.setProperty("max-width", "none", "important");
    });
}

function placeFixed(element, left, top) {
    element.style.setProperty("position", "fixed", "important");
    element.style.setProperty("transform", "none", "important");
    element.style.setProperty("right", "auto", "important");
    element.style.setProperty("bottom", "auto", "important");
    element.style.setProperty("left", `${Math.round(left)}px`, "important");
    element.style.setProperty("top", `${Math.round(top)}px`, "important");
    element.style.setProperty("z-index", "10000", "important");
}

function placeClearOf(floating, forbidden) {
    revealLabels(floating);
    const width = Math.max(floating.scrollWidth || 0, floating.offsetWidth || 0, 240);
    const height = Math.max(floating.scrollHeight || 0, floating.offsetHeight || 0, 32);
    let left = forbidden.right + 8;
    let top = forbidden.top;
    if (left + width > window.innerWidth - 8) {
        left = Math.max(8, forbidden.left - width - 8);
    }
    if (top + height > window.innerHeight - 8) {
        top = Math.max(8, window.innerHeight - height - 8);
    }
    placeFixed(floating, left, top);
    const placed = floating.getBoundingClientRect();
    if (rectsOverlap(placed, forbidden)) {
        placeFixed(floating, forbidden.left, Math.max(8, forbidden.top - placed.height - 8));
    }
}

function holdClear(floating, nodeElement) {
    const skill = nodeElement.querySelector('[aria-label="skill"]');
    let frames = 0;
    const tick = () => {
        const nodeBox = nodeElement.getBoundingClientRect();
        placeClearOf(floating, nodeBox);
        const menuBox = floating.getBoundingClientRect();
        const skillBox = skill ? skill.getBoundingClientRect() : null;
        if (rectsOverlap(menuBox, nodeBox) || (skillBox && rectsOverlap(menuBox, skillBox))) {
            const width = menuBox.width || floating.offsetWidth || 240;
            const left = nodeBox.right + 8 + width > window.innerWidth - 8
                ? Math.max(8, nodeBox.left - width - 8)
                : nodeBox.right + 8;
            placeFixed(floating, left, Math.max(8, nodeBox.top));
        }
        if (frames++ < 24) requestAnimationFrame(tick);
    };
    tick();
}

function floatingRoot(overlay) {
    return (
        overlay.closest("[data-reka-popper-content-wrapper]") ||
        overlay.closest("[data-radix-popper-content-wrapper]") ||
        overlay
    );
}

function presentVueMenu(overlay) {
    const trigger = document.querySelector(
        '[data-testid="widget-select-default-trigger"][aria-expanded="true"][aria-label="model"]'
    );
    if (!trigger) return;
    const nodeElement = trigger.closest("[data-node-id]");
    if (!nodeElement) return;
    const node = findGraphNode(nodeElement.dataset.nodeId);
    const type = nodeTypeName(node) || nodeElement.dataset.xhcyNode || "";
    if (!TARGET_NODES.has(type)) return;
    nodeElement.dataset.xhcyNode = type;
    relaxModelField(nodeElement);
    overlay.classList.add("xhcy-model-menu");
    revealLabels(overlay);
    const viewport = overlay.querySelector('[data-testid="widget-select-default-viewport"]');
    if (viewport) revealLabels(viewport);
    if (type !== ANALYZE_NODE) return;
    holdClear(floatingRoot(overlay), nodeElement);
}

function installVueMenuObserver() {
    if (installVueMenuObserver.started || !document.body) return;
    installVueMenuObserver.started = true;
    const seen = new WeakSet();
    const observer = new MutationObserver(() => {
        document.querySelectorAll('[data-testid="widget-select-default-overlay"]').forEach((overlay) => {
            if (overlay.dataset.xhcyWatching === "1") return;
            overlay.dataset.xhcyWatching = "1";
            if (seen.has(overlay)) return;
            seen.add(overlay);
            presentVueMenu(overlay);
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
}

function classicNodeRect(node) {
    const canvas = app.canvas;
    const element = canvas?.canvas;
    if (!element || !node?.pos || !node?.size) return null;
    const bounds = element.getBoundingClientRect();
    const scale = canvas.ds?.scale || 1;
    const offset = canvas.ds?.offset || [0, 0];
    const left = bounds.left + (node.pos[0] + offset[0]) * scale;
    const top = bounds.top + (node.pos[1] + offset[1]) * scale;
    const width = node.size[0] * scale;
    const height = node.size[1] * scale;
    return { left, top, right: left + width, bottom: top + height, width, height };
}

function adjustClassicMenu(menu) {
    const root = menu?.root;
    if (!root) return;
    const node = app.canvas?.current_node;
    const type = nodeTypeName(node);
    if (!TARGET_NODES.has(type)) return;
    const text = root.innerText || "";
    if (!text.includes("gemini-3.8-flash") && !text.includes("gpt-6.1-sol") && !text.includes("kimi-k3.1-pro")) {
        return;
    }
    if (text.includes("通用创意助手")) return;
    root.classList.add("xhcy-model-menu");
    revealLabels(root);
    if (type !== ANALYZE_NODE) return;
    const forbidden = classicNodeRect(node);
    if (!forbidden) return;
    let frames = 0;
    const tick = () => {
        placeClearOf(root, forbidden);
        if (frames++ < 6) requestAnimationFrame(tick);
    };
    tick();
}

function installClassicMenu() {
    const liteGraph = globalThis.LiteGraph;
    if (!liteGraph?.ContextMenu || liteGraph.ContextMenu.__xhcyModelMenu) return;
    const Original = liteGraph.ContextMenu;
    function Wrapped(values, options) {
        const menu = new Original(values, options);
        requestAnimationFrame(() => adjustClassicMenu(menu));
        return menu;
    }
    Wrapped.prototype = Original.prototype;
    Object.assign(Wrapped, Original);
    Wrapped.__xhcyModelMenu = true;
    liteGraph.ContextMenu = Wrapped;
}

function injectStyle() {
    if (document.getElementById("xhcy-language-model-style")) return;
    const style = document.createElement("style");
    style.id = "xhcy-language-model-style";
    style.textContent = `
[data-xhcy-node] {
  min-width: var(--xhcy-min-width, 460px);
}
[data-xhcy-model-field="1"],
[data-xhcy-model-field="1"] * {
  overflow: visible !important;
  text-overflow: clip !important;
  max-width: none !important;
}
[data-xhcy-model-field="1"] .truncate,
[data-xhcy-model-field="1"] [aria-label="model"] {
  white-space: nowrap !important;
  min-width: max-content !important;
}
.xhcy-model-menu,
.xhcy-model-menu .litemenu-entry,
.xhcy-model-menu .truncate {
  white-space: nowrap !important;
  overflow: visible !important;
  text-overflow: clip !important;
  max-width: none !important;
  width: max-content !important;
}
`;
    document.head.appendChild(style);
}

app.registerExtension({
    name: "xhcy.languageModels",
    setup() {
        injectStyle();
        installClassicMenu();
        installVueMenuObserver();
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET_NODES.has(nodeData?.name)) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            configureModelWidget(this);
            return result;
        };
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            // 写入已保存模型或调整宽度会同步再次进入这里。同一轮直接返回。
            if (this.__xhcyConfiguring || this.__xhcyRetainingModel) return;
            this.__xhcyConfiguring = true;
            try {
                const result = onConfigure?.apply(this, arguments);
                retainSavedModel(this, savedModelValue(info));
                configureModelWidget(this);
                return result;
            } finally {
                this.__xhcyConfiguring = false;
            }
        };
    },
    nodeCreated(node) {
        if (!TARGET_NODES.has(nodeTypeName(node))) return;
        configureModelWidget(node);
    },
});
