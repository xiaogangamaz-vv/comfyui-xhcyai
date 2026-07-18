import { app } from "../../scripts/app.js";

const LEGACY_NODE_NAME = atob("Y29tZnl1aV94aW5naHVvX2dwdF9pbWFnZV8y");
const NODE_NAMES = new Set([
    "comfyui_xinghuo_nano_banana_v3",
    LEGACY_NODE_NAME,
]);

const COST_LABELS = [
    "nano-banana-fast",
    "nano-banana-2",
    "nano-banana-pro",
];

const RATIO_VALUES = new Set([
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "5:4",
    "4:5",
    "21:9",
    "1:4",
    "4:1",
    "1:8",
    "8:1",
]);

const IMAGE_SIZE_VALUES = new Set(["1K", "2K", "4K"]);
const REPLY_TYPE_VALUES = new Set(["json", "async", "stream"]);
const PANEL_HEIGHT = 122;
const KEY_REFRESH_DELAY_MS = 500;
const SUCCESS_REFRESH_DELAY_MS = 1200;

function drawRoundRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, width, height, radius);
    } else {
        ctx.rect(x, y, width, height);
    }
}

function truncateText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (maxWidth <= 0) return "";
    if (ctx.measureText(value).width <= maxWidth) return value;

    let shortened = value;
    while (
        shortened.length &&
        ctx.measureText(`${shortened}\u2026`).width > maxWidth
    ) {
        shortened = shortened.slice(0, -1);
    }
    return shortened ? `${shortened}\u2026` : "";
}

function formatAmount(value) {
    if (typeof value === "string" && value) return value;
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2) : "-";
}

function getWidget(node, name) {
    return node.widgets?.find((item) => item.name === name) || null;
}

function clearApiKeyWidget(node) {
    const widget = getWidget(node, "api_key");
    if (!widget) return;

    widget.value = "";
    widget.serialize = false;
}

function clearApiKeyAfterWorkflowRestore(node) {
    clearApiKeyWidget(node);
    queueMicrotask(() => clearApiKeyWidget(node));
    requestAnimationFrame(() => clearApiKeyWidget(node));
}

function removeRestoredApiKeyFromConfig(node, config) {
    const widget = getWidget(node, "api_key");
    const restoredValue = String(widget?.value || "");

    if (
        restoredValue.length < 8 ||
        !Array.isArray(config?.widgets_values)
    ) {
        return;
    }

    const valueIndex = config.widgets_values.findIndex(
        (value) => value === restoredValue,
    );
    if (valueIndex >= 0) {
        config.widgets_values[valueIndex] = "";
    }
}

function normalizePollingWidget(node, name, fallback, minimum, maximum) {
    const widget = getWidget(node, name);
    if (!widget) return false;

    const value = Number(widget.value);
    if (
        !Number.isInteger(value) ||
        value < minimum ||
        value > maximum
    ) {
        widget.value = fallback;
        return true;
    }

    widget.value = value;
    return false;
}

function repairGenerationWidgets(node) {
    const ratioWidget = getWidget(node, "aspect_ratio");
    const sizeWidget = getWidget(node, "image_size");
    const replyWidget = getWidget(node, "reply_type");

    if (!ratioWidget || !sizeWidget) return false;

    let changed = false;
    let ratio = String(ratioWidget.value || "").trim();
    let size = String(sizeWidget.value || "").trim().toUpperCase();
    let reply = String(replyWidget?.value || "async").trim().toLowerCase();

    /*
     * Old workflows saved widget values by position.
     * Known shifted state:
     *   image_size = 16:9
     *   reply_type = 2K
     * Repair it to:
     *   aspect_ratio = 16:9
     *   image_size = 2K
     *   reply_type = async
     */
    const legacySize = String(replyWidget?.value || "")
        .trim()
        .toUpperCase();

    if (RATIO_VALUES.has(size) && IMAGE_SIZE_VALUES.has(legacySize)) {
        ratio = size;
        size = legacySize;
        reply = "async";
        changed = true;
    }

    if (!RATIO_VALUES.has(ratio)) {
        ratio = "1:1";
        changed = true;
    }

    if (!IMAGE_SIZE_VALUES.has(size)) {
        size = "1K";
        changed = true;
    }

    if (replyWidget && !REPLY_TYPE_VALUES.has(reply)) {
        reply = "async";
        changed = true;
    }

    ratioWidget.value = ratio;
    sizeWidget.value = size;
    if (replyWidget) {
        replyWidget.value = reply;
    }

    return changed;
}

function repairNodeState(node) {
    const changedGeneration = repairGenerationWidgets(node);
    const changedAttempts = normalizePollingWidget(
        node,
        "max_poll_attempts",
        300,
        1,
        1000,
    );
    const changedInterval = normalizePollingWidget(
        node,
        "poll_interval",
        5,
        1,
        60,
    );

    if (changedGeneration || changedAttempts || changedInterval) {
        node.setDirtyCanvas?.(true, true);
    }
}

function scheduleRepairPasses(node) {
    repairNodeState(node);
    queueMicrotask(() => repairNodeState(node));
    requestAnimationFrame(() => repairNodeState(node));
    setTimeout(() => repairNodeState(node), 80);
    setTimeout(() => repairNodeState(node), 250);
}

function createBalancePreviewWidget() {
    return {
        name: "xinghuo_balance_preview",
        type: "custom",
        value: "",
        serialize: false,

        computeSize(width) {
            return [Math.max(0, Number(width) || 0), PANEL_HEIGHT];
        },

        draw(ctx, node, width, y, height) {
            const cardX = 8;
            const cardY = y + 4;
            const cardWidth = Math.max(0, width - 16);
            const cardHeight = Math.max(0, height - 8);

            if (cardWidth <= 0 || cardHeight <= 0) return;

            const textX = cardX + 12;
            const textWidth = Math.max(0, cardWidth - 24);

            ctx.save();
            drawRoundRect(
                ctx,
                cardX,
                cardY,
                cardWidth,
                cardHeight,
                6,
            );
            ctx.fillStyle = "#242424";
            ctx.fill();
            ctx.strokeStyle = "#555";
            ctx.lineWidth = 1;
            ctx.stroke();

            const balance = node._xinghuoBalance;

            if (balance) {
                ctx.font = "600 14px sans-serif";
                ctx.fillStyle = "#f0f0f0";
                ctx.textAlign = "left";
                ctx.fillText("\u603b\u91d1\u989d", textX, cardY + 29);
                ctx.textAlign = "right";
                ctx.fillText(
                    `\u00a5${formatAmount(balance.balance)}`,
                    cardX + cardWidth - 12,
                    cardY + 29,
                );

                ctx.textAlign = "left";
                ctx.strokeStyle = "#484848";
                ctx.beginPath();
                ctx.moveTo(textX, cardY + 42);
                ctx.lineTo(cardX + cardWidth - 12, cardY + 42);
                ctx.stroke();

                const costs = Array.isArray(balance.preview_costs)
                    ? balance.preview_costs
                    : [];

                ctx.font = "12px sans-serif";
                ctx.fillStyle = "#b8b8b8";

                COST_LABELS.forEach((label, index) => {
                    const amount = formatAmount(costs[index]);
                    const rowY = cardY + 64 + index * 19;

                    ctx.textAlign = "left";
                    ctx.fillText(
                        truncateText(ctx, label, textWidth - 96),
                        textX,
                        rowY,
                    );

                    ctx.textAlign = "right";
                    ctx.fillText(
                        `\u00a5${amount} / \u6b21`,
                        cardX + cardWidth - 12,
                        rowY,
                    );
                });

                ctx.textAlign = "left";
            } else {
                ctx.font = "11px sans-serif";
                ctx.fillStyle = node._xinghuoBalanceError
                    ? "#e0a0a0"
                    : "#b8b8b8";

                ctx.fillText(
                    truncateText(
                        ctx,
                        node._xinghuoBalanceError ||
                            "\u7c98\u8d34 API Key \u540e\u81ea\u52a8\u67e5\u8be2\u4f59\u989d",
                        textWidth,
                    ),
                    textX,
                    cardY + 42,
                );

                ctx.fillStyle = "#9a9a9a";
                ctx.fillText(
                    truncateText(
                        ctx,
                        "\u751f\u6210\u6210\u529f\u540e\u4f1a\u81ea\u52a8\u5237\u65b0",
                        textWidth,
                    ),
                    textX,
                    cardY + 64,
                );
            }

            ctx.restore();
        },
    };
}

function publicBalanceError(response, data, hasKey) {
    if (!hasKey) return "\u8bf7\u5148\u586b\u5199 API Key";

    if (
        response?.status === 401 ||
        /\u5bc6\u94a5|key/i.test(String(data?.error || ""))
    ) {
        return "API Key \u65e0\u6548\u6216\u5df2\u5931\u6548";
    }

    return "\u4f59\u989d\u67e5\u8be2\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u6216\u7a0d\u540e\u91cd\u8bd5";
}

function firstStatusValue(value) {
    let current = value;
    while (Array.isArray(current) && current.length > 0) {
        current = current[0];
    }
    return String(current || "").trim().toLowerCase();
}

function installBalanceUi(node) {
    if (node._xinghuoBalancePanelAttached) return;
    node._xinghuoBalancePanelAttached = true;

    clearApiKeyAfterWorkflowRestore(node);
    scheduleRepairPasses(node);

    node._xinghuoBalance = null;
    node._xinghuoBalanceError =
        "\u7c98\u8d34 API Key \u540e\u81ea\u52a8\u67e5\u8be2\u4f59\u989d";
    node._xinghuoBalanceLoading = false;

    let keyRefreshTimer = null;
    let successRefreshTimer = null;
    let keyWatchTimer = null;
    let lastObservedKey = "";
    let requestToken = 0;
    let activeController = null;

    const button = node.addWidget(
        "button",
        "\ud83d\udcb0 \u5237\u65b0\u8d26\u6237\u4f59\u989d",
        "query_account_balance",
        () => refreshBalance("manual"),
    );
    button.serialize = false;

    async function refreshBalance(reason) {
        if (node._xinghuoBalanceLoading && reason !== "generation_success") {
            return;
        }

        repairNodeState(node);

        const keyWidget = getWidget(node, "api_key");
        const modelWidget = getWidget(node, "model");
        const apiKey = String(keyWidget?.value || "").trim();

        if (!apiKey) {
            activeController?.abort();
            node._xinghuoBalance = null;
            node._xinghuoBalanceError = publicBalanceError(
                null,
                null,
                false,
            );
            node.setDirtyCanvas?.(true, true);
            return;
        }

        const currentToken = ++requestToken;
        activeController?.abort();
        activeController = new AbortController();

        node._xinghuoBalanceLoading = true;
        node._xinghuoBalanceError = null;
        button.name = "\u23f3 \u6b63\u5728\u5237\u65b0\u2026";
        node.setDirtyCanvas?.(true, true);

        try {
            const response = await fetch(
                "/xinghuo_nano_banana/balance",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        api_key: apiKey,
                        model: modelWidget?.value || "",
                    }),
                    cache: "no-store",
                    signal: activeController.signal,
                },
            );

            let data = {};
            try {
                data = await response.json();
            } catch {
                data = {};
            }

            if (currentToken !== requestToken) return;

            if (!response.ok || !data.success) {
                throw { response, data };
            }

            node._xinghuoBalance = data;
            node._xinghuoBalanceError = null;
            button.name = "\ud83d\udcb0 \u5237\u65b0\u8d26\u6237\u4f59\u989d";
        } catch (failure) {
            if (failure?.name === "AbortError") return;

            node._xinghuoBalance = null;
            node._xinghuoBalanceError = publicBalanceError(
                failure?.response,
                failure?.data,
                true,
            );
            button.name =
                "\u26a0 \u67e5\u8be2\u5931\u8d25\uff0c\u70b9\u51fb\u91cd\u8bd5";
        } finally {
            if (currentToken === requestToken) {
                node._xinghuoBalanceLoading = false;
                node.setDirtyCanvas?.(true, true);
            }
        }
    }

    function scheduleKeyRefresh(delay = KEY_REFRESH_DELAY_MS) {
        clearTimeout(keyRefreshTimer);
        keyRefreshTimer = setTimeout(() => {
            refreshBalance("api_key_change");
        }, delay);
    }

    function scheduleSuccessRefresh() {
        clearTimeout(successRefreshTimer);
        successRefreshTimer = setTimeout(() => {
            refreshBalance("generation_success");
        }, SUCCESS_REFRESH_DELAY_MS);
    }

    node._xinghuoRefreshBalanceAfterSuccess = scheduleSuccessRefresh;

    const apiKeyWidget = getWidget(node, "api_key");
    if (apiKeyWidget) {
        const originalCallback = apiKeyWidget.callback;

        apiKeyWidget.callback = function () {
            const result =
                typeof originalCallback === "function"
                    ? originalCallback.apply(this, arguments)
                    : undefined;

            const currentKey = String(apiKeyWidget.value || "").trim();
            if (currentKey !== lastObservedKey) {
                lastObservedKey = currentKey;
                scheduleKeyRefresh();
            }

            return result;
        };
    }

    const modelWidget = getWidget(node, "model");
    if (modelWidget) {
        const originalModelCallback = modelWidget.callback;

        modelWidget.callback = function () {
            const result =
                typeof originalModelCallback === "function"
                    ? originalModelCallback.apply(this, arguments)
                    : undefined;

            if (String(apiKeyWidget?.value || "").trim()) {
                scheduleKeyRefresh(250);
            }

            return result;
        };
    }

    keyWatchTimer = setInterval(() => {
        const currentKey = String(apiKeyWidget?.value || "").trim();
        if (currentKey === lastObservedKey) return;

        lastObservedKey = currentKey;

        if (currentKey) {
            scheduleKeyRefresh();
        } else {
            node._xinghuoBalance = null;
            node._xinghuoBalanceError = publicBalanceError(
                null,
                null,
                false,
            );
            node.setDirtyCanvas?.(true, true);
        }
    }, 350);

    node.addCustomWidget(createBalancePreviewWidget());

    requestAnimationFrame(() => {
        scheduleRepairPasses(node);

        const size = node.computeSize?.();
        if (Array.isArray(size) && node.size) {
            node.setSize([
                node.size[0],
                Math.max(node.size[1], size[1]),
            ]);
        }

        node.setDirtyCanvas?.(true, true);
    });

    const originalRemoved = node.onRemoved;
    node.onRemoved = function () {
        clearTimeout(keyRefreshTimer);
        clearTimeout(successRefreshTimer);
        clearInterval(keyWatchTimer);
        activeController?.abort();
        delete node._xinghuoRefreshBalanceAfterSuccess;

        if (typeof originalRemoved === "function") {
            return originalRemoved.apply(this, arguments);
        }
    };
}

app.registerExtension({
    name: "xinghuo.nano_banana.balance.v3",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.has(nodeData.name)) return;

        const originalCreated = nodeType.prototype.onNodeCreated;
        const originalConfigure = nodeType.prototype.onConfigure;
        const originalExecuted = nodeType.prototype.onExecuted;

        nodeType.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);

            removeRestoredApiKeyFromConfig(this, arguments[0]);
            clearApiKeyAfterWorkflowRestore(this);
            scheduleRepairPasses(this);

            return result;
        };

        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            installBalanceUi(this);
            return result;
        };

        nodeType.prototype.onExecuted = function (message) {
            const result = originalExecuted?.apply(this, arguments);

            const status = firstStatusValue(
                message?.xinghuo_generation_status,
            );

            if (status === "success") {
                this._xinghuoRefreshBalanceAfterSuccess?.();
            }

            return result;
        };
    },
});
