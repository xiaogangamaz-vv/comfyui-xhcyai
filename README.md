# comfyui-xhcyai

XHCY AI（[ai.xhcyai.org](https://ai.xhcyai.org)）的 ComfyUI 节点合集。

同一家族的模型合成一个节点，节点里用下拉切换变体；图像节点同时支持**文生图**和**多图参考**。

## 安装

1. 把整个仓库放进 ComfyUI 的插件目录：

   ```
   ComfyUI/custom_nodes/comfyui-xhcyai/
   ```

2. 安装依赖：

   ```
   pip install -r requirements.txt
   ```

3. 重启 ComfyUI，在节点面板 **XHCY** 分类下即可找到。

## 节点清单

| 节点 | 分类 | 说明 |
| --- | --- | --- |
| **XHCY GPT Image 2.5（文生图 / 多图参考）** | XHCY/Image | 不接参考图 = 文生图，接 `image1`~`image16` = 多图参考。下拉切换 `gpt-image-2.5` / `-flare` / `-sunburst` |
| **XHCY GPT Image 2（文生图 / 多图参考）** | XHCY/Image | 同上。下拉切换 `gpt-image-2`（本站只允许 1024×1024）/ `-all` / `-vip`（可到 4K） |
| **XHCY Nano Banana（文生图 / 多图参考）** | XHCY/Image | 同上。该家族**只支持 1024x1024**，所以节点上不显示画幅 / 分辨率 / 画质下拉 |
| **XHCY Seedream 5.0（文生图 / 多图参考 / 图层拆分）** | XHCY/Image | 同一家族四个变体。带 `/layer-decomposition` 的两个变体做**图层拆分**，需要且只需要接 1 张图 |
| **XHCY MiniMax H3（文生视频）** | XHCY/Video | 走 `POST /v1/video/generations`，下拉切换 `MiniMax-H3` / `MiniMax-H3-Lite` |
| **XHCY MiniMax H3（首尾帧 / 图生视频）** | XHCY/Video | 接 `first_frame` / `last_frame`，让视频从指定画面开始、到指定画面结束；只接一张就是普通图生视频 |
| **XHCY MiniMax H3（多模态参考）** | XHCY/Video | 接 `image1`~`image9`、`video1`~`video3`、`audio1`~`audio3`；什么都不接就是纯文生视频 |
| **XHCY MiniMax H3（768P→2K 再生成）** | XHCY/Video | 把已有的 768P 视频提升到 2K。填任务号，或直接接一段源视频 |
| **XHCY MiniMax H3 Context-IR（提示词增强）** | XHCY/Video | 把粗略想法扩写成成片的提示词。可纯文本，也可带图/视频/音频做多模态增强 |
| **XHCY 文本 / 对话（LLM）** | XHCY/Text | 站点上的文本与多模态模型，走 `POST /v1/chat/completions` |
| comfyui xinghuo nano banana | 星火/Secure Image | 旧节点（打的是另一家服务，与本站无关，保留兼容） |

---

## 图像节点

### XHCY GPT Image 2.5 参数

| 输入 | 说明 |
| --- | --- |
| `prompt` | 提示词，必填 |
| `model` | 家族变体：`gpt-image-2.5`（仅 1k）/ `-flare`（到 4k，质量到 high）/ `-sunburst`（到 4k，质量到 max） |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | 画幅比例，`auto` 表示交给服务端决定 |
| `resolution` | `1k` / `2k` / `4k`，节点内部换算成接口要求的像素 `size` |
| `quality` | `auto` / `low` / `medium` / `high` / `xhigh` / `max` |
| `image1` ~ `image16` | **可选**。一个都不接 = 文生图；接 1 张以上 = 多图参考。会自动缩到长边 ≤1536 并转 JPEG 后上传 |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔 |
| `base_url` | 站点地址，一般不用改 |

输出：`image`（可直接接 `SaveImage`）/ `status`（摘要）/ `saved_paths`（落盘路径）。

#### 两种用法

- **文生图**：只填 `prompt`，参考图一个都不连。
- **多图参考**：把参考图接到 `image1`、`image2` …，提示词描述「要拿这些图做什么」。
  实测接 2 张 512×512 参考图，生成结果正确合并了两张图的元素。

> **参考图越多越慢**：实测带 1 张参考图约 80 秒，而网关的等待上限约 100 秒。
> 建议一次不超过 3～4 张；真超时了节点会明确提示（HTTP 524），不会静默失败。

### XHCY GPT Image 2 参数

参数布局与 GPT Image 2.5 完全一致，只有变体与尺寸范围不同：

| 变体 | 档位 | 说明 |
| --- | --- | --- |
| `gpt-image-2` | 仅 1k | 站点定价模型，**尺寸白名单只有 1024×1024**。选到别的画幅时节点会直接告诉你改用下面两个变体，而不是让你去撞 `size_not_supported` |
| `gpt-image-2-all` | 1k / 2k / 4k | 能力对标 nano banana 2，任意画幅（默认值） |
| `gpt-image-2-vip` | 1k / 2k / 4k | 任意画幅 |

该家族没有画质档，所以节点上不显示 `quality`。

> 站点只对**定价模型**（`nano-banana-2` / `nano-banana-pro` / `gpt-image-2`）做尺寸预校验，
> `-all` / `-vip` 是原样转发上游。这两个变体的像素表沿用 GPT Image 2.5 那套已验证的约束
> （长边 ≤ 3840、边长为 16 的倍数、比例不超过 3:1），**尚未逐个实测**。

### XHCY Nano Banana 参数

控件顺序与常用参考节点一致：

| 输入 | 说明 |
| --- | --- |
| `image1` ~ `image16` | **可选**。一个都不接 = 文生图；接 1 张以上 = 多图参考 |
| `prompt` | 提示词，必填 |
| `model` | `nano-banana-2`（推荐，实测最稳）/ `gemini-nano-banana-2.1` / `nano-banana-pro` / `nano-banana-fast` |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | 画面比例。**本站只开放 `1:1`（另有 `auto` 等价）**，下拉里也只有这两项 |
| `image_size` | 分辨率档位。**本站只开放 `1K`（即 1024×1024）**，下拉里只有这一项 |
| `reply_type` | `async` / `sync`。本站禁用了异步图像生成，**选什么都不影响，都会按同步执行** |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔，默认 300 / 5 |
| `base_url` | 站点地址，默认 `https://ai.xhcyai.org` |

输出：`image` / `response_text`（摘要）/ `local_image_paths`（落盘路径）。

> **尺寸限制（实测）**：该家族**只接受 `1024x1024`**。
> 实测 `1024x1536` / `1536x1024` / `1280x720` / `2048x2048` / `4096x4096`
> **全部返回 `size_not_supported`**。所以下拉里只保留本站真正支持的值——
> 曾经给过全量选项，但那样会出现「选项在、一选就报错」的误导。
>
> **想要其它比例或更高分辨率，请换用 GPT Image 2.5 或`gpt-image-2-all`**。
>
> **速度差异**：实测带一张参考图时，`nano-banana-2` 约 51 秒，
> 而 `gemini-nano-banana-2.1` 要约 **106 秒**——已经贴近网关的 100 秒等待上限，
> 参考图较多时建议优先用 `nano-banana-2`。

### XHCY Seedream 5.0 参数

| 输入 | 说明 |
| --- | --- |
| `image1` ~ `image10` | **可选**。不接 = 文生图；接 1 张以上 = 多图参考（主体保持 / 局部改绘 / 多图融合）。**图层拆分变体必须且只能接 1 张** |
| `prompt` | 提示词，必填 |
| `model` | `seedream-v5-flash`（默认，单价低）/ `seedream-v5-pro` / `seedream-v5-flash/layer-decomposition` / `seedream-v5-pro/layer-decomposition` |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | `auto`、`1:1`、`4:3`、`3:4`、`16:9`、`9:16`、`3:2`、`2:3`、`21:9` |
| `resolution` | `1K` / `1.5K` / `2K` |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔 |
| `base_url` | 站点地址，一般不用改 |

输出：`image` / `status` / `saved_paths`。图层拆分的结果是多张图，会作为一批（batch）输出。

> 参数不是猜的：`比例 + 档位 → 像素` 的映射表取自**随站点一起分发的官方节点**
> `comfyui-xinghuo-seedream/nodes.py`（其中的 `_SIZE_MAP_PRO`），
> 站点后端 `relay/billing/ratio/image.go` 也确认 `size` 传的是像素。
>
> 图层拆分返回的图层通常带透明通道。**落盘的 PNG 保留原始数据**（含 alpha），
> 但传给下游 ComfyUI 节点的张量会统一转成 RGB，因为 `IMAGE` 类型不含透明通道。

---

## 视频节点

### XHCY MiniMax H3 参数

规格来自站点 `GET /api/video/models`（2026-10-15 核对），三个生成类 H3 节点共用规格表
`xhcy_h3_specs.py`，下拉选项会自动跟随它，不需要手工维护。

| 模型 | 分辨率 | 时长 | 比例 |
| --- | --- | --- | --- |
| `MiniMax-H3` | **480P / 768P / 1080P / 2K** | **4–30 秒** | adaptive、21:9、16:9、4:3、1:1、3:4、9:16 |
| `MiniMax-H3-Lite` | 480P / 768P | 1–15 秒 | adaptive、16:9、9:16、1:1 |

> ⚠️ **`MiniMax-H3-Max` 已下线**（站点后端白名单只剩 H3 与 H3-Lite，继续使用会被拒），
> 所以它从下拉里移除了。
>
> `MiniMax-H3` 的时长**超过 15 秒时，生成与素材费用翻倍**（站点计费规则）。

| 输入 | 说明 |
| --- | --- |
| `prompt` | 视频描述，必填 |
| `model` | 上面的两个变体，切换即可 |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `resolution` | 480P / 768P / 1080P / 2K，**按所选模型自动校验**（选到不支持的值会明确提示） |
| `duration` | 时长（秒），按秒计费；**超出所选模型范围时会自动收进合法区间并在状态里说明** |
| `ratio` | 画面比例，`adaptive` 表示由服务端决定 |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔 |
| `base_url` | 站点地址，一般不用改 |

输出：`video`（ComfyUI 官方 VIDEO 类型，可直接接 `SaveVideo` / `PreviewVideo`）/ `status` / `video_path`。

### XHCY MiniMax H3 首尾帧 / 多模态参考 参数

两个节点共用 H3 家族的 `model` / `resolution` / `duration` / `ratio` / `api_key` 参数，
只是素材输入不同：

| 节点 | 素材输入 | 说明 |
| --- | --- | --- |
| **首尾帧 / 图生视频** | `first_frame`、`last_frame` | 至少接一张。只接 `first_frame` = 以它为开头的图生视频；两张都接 = 从首帧过渡到尾帧 |
| **多模态参考** | `image1`~`image9`、`video1`~`video3`、`audio1`~`audio3` | 想接哪个接哪个。全都不接 = 纯文生视频 |

> **多图参考的提示词写法**：按顺序用「Image 1」「Image 2」引用对应编号的参考图，
> 例如「让 Image 1 里的女孩穿上 Image 2 的裙子」。不点名的话，模型不知道哪张是哪个。
>
> 素材会被转成 **data URI 内嵌进请求**（站点没有上传接口）。
>
> **画质策略：几乎不压。** 参考图只有超过 **2560** 长边才缩放，JPEG 质量 **95**
> （肉眼基本无损）；单个素材上限 **48 MiB**，整次请求上限 **60 MiB**
> （base64 后约 80 MB，低于 Cloudflare 的单请求 100 MB 硬顶）。
>
> **提交已改为异步，那 100 秒不再是问题。**
>
> Cloudflare 对源站响应只有约 **100 秒**（免费 / Pro / Business 固定，改不了；
> nginx 侧早已配到 3600 秒，不是它的问题）。站点原先在请求里同步等上游建任务，
> 参考素材一大就会撞上这道墙，返回 524 而任务其实还在后台跑。
>
> 现在站点支持把提交放进后台（`ASYNC_VIDEO_ENABLED`）：节点带上 `async: true`，
> **请求 1 秒内就返回任务号**，之后照常轮询结果。实测 768P/5 秒：提交 1 秒返回、
> 12 秒转「处理中」、24 秒出片。
>
> 站点若还是旧版本，会忽略这个字段、退回同步提交，节点行为不变。
> 万一仍撞上超时，节点还会去任务列表把可能已建好的任务找回来（最多等 32 秒）。

### XHCY MiniMax H3（768P→2K 再生成）参数

走 `POST /v1/video/regenerations`。**只支持输出 2K**，所以节点上没有分辨率下拉。

| 输入 | 说明 |
| --- | --- |
| `api_key` | XHCY AI 访问密钥 |
| `model` | 目前是 `MiniMax-H3`（这是 H3 专属能力，Lite 不支持） |
| `source_task_id` | **方式一**：填一个已生成视频的任务号，把它提升到 2K |
| `prompt` | **方式二**（接源视频）时必填；方式一可留空 |
| `base_video` | **方式二**：接一段源视频，与 `source_task_id` **二选一** |
| `duration` | 秒。**输出长度跟随源视频**，这里填的只用于计费（按输出秒数计价） |
| `max_poll_attempts` / `poll_interval` / `base_url` | 同上 |

输出与其它视频节点一致。

> 两条硬性约束节点已经帮你挡掉：`source_task_id` 与 `base_video` 不能同时给；
> 用源视频时 `content` 里必须**恰好一个** `role = base_video` 的视频项。

### XHCY MiniMax H3 Context-IR（提示词增强）参数

走 `POST /v1/video/context-ir`，**同步返回**一段增强后的提示词（不生成视频，按次计费）。

| 输入 | 说明 |
| --- | --- |
| `prompt` | 你现在的想法或草稿，必填 |
| `model` | 目前是 `MiniMax-H3` |
| `api_key` | XHCY AI 访问密钥 |
| `duration` | 秒。上游要求的必填项，**与增强结果无关**（费用按次收） |
| `ratio` | 画面比例。**纯文本时必须显式指定，不能选 `adaptive`**（没有图就没有可对齐的画幅）；接了素材才可以用 `adaptive` |
| `image1`~`image9` / `video1`~`video3` / `audio1`~`audio3` | 可选。接了就是多模态增强 |
| `base_url` | 站点地址 |

输出：`enhanced_prompt`（增强后的提示词，可直接接到文生视频节点的提示词输入）/ `status` / `task_id`。

---

## 文本节点

### XHCY 文本 / 对话（LLM）

| 输入 | 说明 |
| --- | --- |
| `prompt` | 要问模型的内容，必填 |
| `model` | `deepseek-v4.1-flash`（默认）/ `gpt-6.1-sol` / `claude-opus-5-5` / `claude-fable-5` / `claude-fable-5-1` / `gemini-3.8-flash` / `gemini-3.1-pro` / `gemini-3-flash` / `MiniMax-Text-01` / `MiniMax-VL-01` / `abab5.5s-chat` |
| `api_key` | XHCY AI 访问密钥 |
| `system` | 系统提示词（角色设定），可留空 |
| `temperature` | 0～2，默认 0.7 |
| `max_tokens` | 回复长度上限；`0` 表示不指定 |
| `image` | 可选。接了会组装成多模态消息（图片转 data URI 内嵌），**只有视觉模型支持**（如 `MiniMax-VL-01`、gemini / claude / gpt 系列） |

输出：`text`（回复正文）/ `status`（模式、模型、长度、token 用量）。

典型用法：把 `text` 接到文生图 / 文生视频节点的提示词输入，让模型先把想法写细。

---

## 实现说明

- **站点当前禁用了异步图像生成**：带 `async: true` 的请求会被直接拒绝
  （HTTP 400 `async image generation is disabled`，已实测确认），因此图像节点走**同步提交**。
  若服务端返回 task id，节点会自动切换为轮询 `GET /v1/images/tasks/{task_id}`。
- **多图参考的传参规则**（实测确定）：参考图必须以 **base64 data URI** 放进 `image` 数组，
  走 `POST /v1/images/generations`；传公网 URL 会被上游拒绝（HTTP 400）。
  站点的 `/v1/images/edits` 目前未实现（HTTP 501）。
- 参考图会自动缩到长边 ≤1536 并转成 JPEG（quality 90）后再上传——实测大体积 data URI
  会让整个请求撞上网关超时（HTTP 524）。
- 尺寸在节点内由 `(画幅比例, 分辨率)` 换算成像素尺寸，接口只接受像素格式。
- 失败一律抛出可读中文错误（密钥失效、余额不足、内容审核未通过、网关超时等），不会把坏图当成功返回。
- **上游抖动自动重试**：遇到 502 / 503 / 504 时节点会自己重试两次（间隔 2 秒、5 秒），
  因为这类状态码表示请求没被处理，重试不会重复扣费。仍在失败才会报错。
- **HTTP 451 是内容合规拦截**（不是故障）：提示词或参考素材被判为不合规，
  换一种描述或换一张参考图再试即可。
- **视频走异步**：`POST /v1/video/generations` 返回 `task_id` 后轮询
  `GET /v1/video/generations/{task_id}`，状态依次为 `queued → processing → succeeded`，
  成功后产物在 `content.url`。
- **视频产物需要鉴权**：该地址属于站点自身的 `/v1` 路径，节点会在下载时自动带上密钥
  （已实测：不带密钥返回 HTTP 401）。图片地址来自公开 CDN，则不会附带密钥。
- 视频以 ComfyUI 官方 **VIDEO** 类型输出，可直接接 `SaveVideo` / `PreviewVideo`。
- **素材的角色（role）**：首尾帧用 `first_frame` / `last_frame`，多模态参考用
  `reference_image` / `reference_video` / `reference_audio`，再生成用 `base_video`，
  都以 data URI 放进 `content` 数组。
- **不信任本地代理**：实测本机 `HTTP_PROXY` 在请求体稍大（带参考素材）时会直接掐断连接并报
  `ProxyError`，而同一请求直连正常。因此客户端**默认直连**，只有直连失败才回退到环境代理。
- **「视频再生成」与「Context-IR」已经实现**（站点 2026-10 开放）：
  - 再生成 `POST /v1/video/regenerations`，请求体是 `model` + `resolution: "2K"` +
    `duration`（仅用于计费）+ `source_task_id` 或 `content`（含恰好一个 `role=base_video`）。
    结果仍按 `/v1/video/generations/{task_id}` 轮询。
  - 增强 `POST /v1/video/context-ir`，同步返回 `data.prompt`。
  这两条路径的调用格式来自站点后端源码（`relay/controller/video.go`、
  `relay/adaptor/minimax/video.go`），并已通过离线校验；
  **真实生成尚未跑过**（验证时账户额度紧张），首次使用请留意。
- `MiniMax-H3` 的分辨率现为 **480P / 768P / 1080P / 2K**，时长上限 **30 秒**（超 15 秒费用翻倍）。

## 新增图像模型（套用模板）

图像节点的公共逻辑全部集中在 `xhcy_image_base.py` 的 `XHCYImageBase`：
多图参考、提交、轮询、落盘、错误翻译都在基类里。
新增一个图像模型只需要复制 `nodes_gpt_image_2.py`，改这几处常量：

| 常量 | 作用 |
| --- | --- |
| `VARIANT_MODELS` | 下拉里出现的模型名 |
| `RATIOS` / `RESOLUTIONS` / `SIZE_MAP` | 画幅比例、分辨率档位、以及两者的像素换算表 |
| `RESOLUTION_LIMITS` / `QUALITIES` | 各变体支持的分辨率与画质档；`QUALITIES = []` 表示该模型没有画质档，节点不显示 `quality` |
| `MAX_REFERENCES` | 节点上出现几个参考图入口（默认 16，Seedream 是 10） |
| `SIZE_FIELD` | 尺寸控件的字段名（`resolution` 或 `image_size`），用来对齐不同节点的习惯 |
| `FIXED_SIZE` | 模型只吃单一尺寸时填，例如 `"1024x1024"`；填了就不显示画幅 / 分辨率下拉 |
| `NODE_ID` / `OUTPUT_PREFIX` | 节点唯一 ID 与落盘文件名前缀 |
| `NODE_DISPLAY_NAME_MAPPINGS` | 节点在面板里的显示名 |

需要按变体做更细的限制时，覆盖这两个类方法即可（`nodes_gpt_image_2.py` 与
`nodes_seedream_v5.py` 就是例子）：

- `resolve_size(aspect_ratio, resolution, model)` —— 按变体裁剪可用的尺寸
- `check_references(model, references)` —— 按变体校验参考图数量

## 自测

不装 ComfyUI 也能验证密钥与接口：

```bash
python test_api.py --api-key sk-xxxx --models-only
python test_api.py --api-key sk-xxxx
python test_api.py --api-key sk-xxxx --model gpt-image-2.5-flare --size 1024x1024
```

产物输出到 `probe_out/`。
