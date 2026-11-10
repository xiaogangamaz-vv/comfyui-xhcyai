# comfyui-xhcyai

XHCY AI 的 ComfyUI 节点，用来调用官网的图像、视频与文本接口，其中包括低价 MiniMax H3。

官网：<https://ai.xhcyai.org>

## 更新了什么

- 修复部分网络下调用网关超时：握手不再被一条没有回应的地址拖住，结果文件优先从网关读取。
- 图像生成支持异步提交，也能接收内嵌图片；Banana 家族按站点当前的比例与档位调用。
- 视频侧提供 MiniMax H3、Seedance 2.0，以及视频超分。

## 支持的模型

### 图像

- Nano Banana：`gemini-2.5-flash-image`、`nano-banana-2`、`nano-banana-pro`、`gemini-nano-banana-2.1`
- GPT Image 2：`gpt-image-2`、`gpt-image-2-vip`
- GPT Image 2.5：`gpt-image-2.5`、`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`
- Seedream 5.0：`seedream-v5-flash`、`seedream-v5-pro`，以及对应的图层拆分变体
- 另保留旧版星火 Nano Banana 节点，供已有工作流兼容

### 视频

- MiniMax H3、MiniMax-H3-Lite：文生视频、首尾帧、多模态参考；H3 另有再生成与 Context-IR 提示词增强
- Seedance 2.0：`doubao-seedance-2-0`、`doubao-seedance-2-0-fast`、`doubao-seedance-2-0-mini`
- 视频超分：`Video Super-Resolution`

### 文本

- 对话：`deepseek-v4-flash`、`deepseek-v4-pro`、`deepseek-v4.1-flash`、`deepseek-v4.1-flash-1017`、`gpt-6.1-sol`、`claude-opus-5-5`、`claude-fable-5`、`claude-fable-5-1`、`gemini-3.8-flash`
- 智能分析：上述模型中的 Gemini、Claude 与 GPT 视觉变体

## 官网

<https://ai.xhcyai.org>

## 安装

将本仓库放入 ComfyUI 的 `custom_nodes` 目录后重启。

## 许可

本仓库采用专有许可，详见 [LICENSE](LICENSE)。未经授权，禁止商业使用与再分发。
