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
| **XHCY GPT Image 2.5（文生图 / 多图参考）** | XHCY/Image | 不接参考图 = 文生图，接 `image1`~`image16` = 多图参考。**基版只认 2 种尺寸，**`-flare` / `-sunburst`** 十四种画幅 × 1K/2K/4K 全开** |
| **XHCY GPT Image 2（文生图 / 多图参考）** | XHCY/Image | `gpt-image-2` 只认 1024×1024；`-all` 上游不收 size（只能 auto）；`-vip` 全开 |
| **XHCY Nano Banana（文生图 / 多图参考）** | XHCY/Image | **五种画幅**（1:1 / 2:3 / 3:2 / 16:9 / 9:16），1K 与 4K。能力随 `model` 变体不同，见下方对照表 |
| **XHCY Seedream 5.0（文生图 / 多图参考 / 图层拆分）** | XHCY/Image | 同一家族四个变体。带 `/layer-decomposition` 的两个变体做**图层拆分**，需要且只需要接 1 张图 |
| **XHCY MiniMax H3（文生视频）** | XHCY/Video | 走 `POST /v1/video/generations`，下拉切换 `MiniMax-H3` / `MiniMax-H3-Lite` |
| **XHCY MiniMax H3（首尾帧 / 图生视频）** | XHCY/Video | 接 `first_frame` / `last_frame`，让视频从指定画面开始、到指定画面结束；只接一张就是普通图生视频 |
| **XHCY MiniMax H3（多模态参考）** | XHCY/Video | **动态插槽**：接一个自动长一个。参考图最多 9 张、视频 3 段、音频 3 段；什么都不接就是纯文生视频 |
| **XHCY MiniMax H3（768P→2K 再生成）** | XHCY/Video | 把已有的 768P 视频提升到 2K。填任务号，或直接接一段源视频 |
| **XHCY MiniMax H3 Context-IR（提示词增强）** | XHCY/Video | 把粗略想法扩写成成片的提示词。可纯文本，也可带图/视频/音频做多模态增强 |
| **XHCY Seedance 2.0（文生 / 首尾帧 / 多模态参考）** | XHCY/Video | 一个节点四种用法。下拉切换 `doubao-seedance-2-0` / `-fast` / `-mini`；480P~4K（标准版）、4–15 秒，可生成同步音频 |
| **XHCY 文本 / 对话（LLM）** | XHCY/Text | 站点上的文本与多模态模型，走 `POST /v1/chat/completions` |
| **XHCY 智能分析（多模态·角色化）** | XHCY/Text | 上传素材 + 选角色 + 说需求 → 产出提示词 / 分镜 / 参数建议，可直接接给下游节点 |
| comfyui xinghuo nano banana | 星火/Secure Image | 旧节点（打的是另一家服务，与本站无关，保留兼容） |

---

## 图像节点

### 尺寸能力对照表（2026-10-23 按站点源码补齐）

站点的尺寸白名单是**逐模型**的，同一个家族里有的变体只认一个尺寸、有的认八种。
下表取自后端源码 `relay/billing/ratio/image.go`（`ImageSizeRatios`）与
`relay/billing/ratio/image_nano_banana_params.go`，是站点自己执行的规则。

| 模型 | 站点规则 | 可用画幅 × 档位 |
| --- | --- | --- |
| `nano-banana-2` | 严格白名单 | 1:1 @ 1K |
| `nano-banana-pro` | 严格白名单 | 1:1 @ 1K |
| `gemini-nano-banana-2.1` | 严格白名单 | 1:1 @ 1K / 4K；2:3、3:2、16:9、9:16 @ 1K 或 4K |
| `nano-banana-fast` | 不校验（直通） | 同 gemini 那八种组合 |
| `nano-banana` | 不校验（直通） | 同上 |
| `gpt-image-2` | 严格白名单 | 1:1 @ 1K |
| `gpt-image-2-all` | 直通，但**上游拒收 size** | 只能 `auto`（不传 size） |
| `gpt-image-2-vip` | 不校验（直通） | 14 种画幅 × 1K / 2K / 4K |
| `gpt-image-2.5` | 严格白名单 | 1:1 @ 1K、9:16 @ 1K |
| `gpt-image-2.5-flare` | 不校验（直通） | 14 种画幅 × 1K / 2K / 4K |
| `gpt-image-2.5-sunburst` | 不校验（直通） | 同上，画质另可到 xhigh / max |

**选到不支持的组合时，节点会在发请求前就拦下来**，并告诉你这个模型能用什么，
不会白扣费。例如：

```
nano-banana-2 不支持「16:9 + 1K」。
它在本站可用的组合只有：1:1 @ 1K
（选其它变体，或改成上面列出的组合）
```

> **⚠️ 关于 `gemini-nano-banana-2.1` 的档位**
>
> 这个模型的上游不接受像素尺寸，只接受「比例 + 档位」。站点内部会把像素框
> 换算成比例形式再发出去，而且**非正方形框统一按 4K 档出图**。
>
> 实测：选 `2:3 @ 1K`（1024×1536），实际出图是 **3392×5056**（约 17 MP）。
> 这是上游的既定行为，不是 bug——宽高比是对的，只是比你选的那一档更大。
> 好处是画质更高，代价是文件大（单张约 18 MB）。

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
| `gpt-image-2-all` | 只能 `auto` | **上游不接受 `size` 参数**（站点源码里标注为 "upstream rejects the size parameter"）。画幅必须选 `auto`，由模型自己决定尺寸；选具体画幅会被节点拦下 |
| `gpt-image-2-vip` | 1k / 2k / 4k | 任意画幅（默认值，14 种画幅全开） |

该家族没有画质档，所以节点上不显示 `quality`。

> 站点只对**定价模型**（`nano-banana-2` / `nano-banana-pro` / `gpt-image-2` /
> `gemini-nano-banana-2.1` / `gpt-image-2.5`）做尺寸预校验，其余是原样转发上游。
> 直通模型的像素表沿用 GPT Image 2.5 那套已验证的约束
> （长边 ≤ 3840、边长为 16 的倍数、比例不超过 3:1），**尚未逐个实测**。

### XHCY Nano Banana 参数

控件顺序与常用参考节点一致：

| 输入 | 说明 |
| --- | --- |
| `image1` ~ `image16` | **可选**。一个都不接 = 文生图；接 1 张以上 = 多图参考 |
| `prompt` | 提示词，必填 |
| `model` | `nano-banana-2`（推荐，实测最稳）/ `gemini-nano-banana-2.1`（画幅最全）/ `nano-banana-pro` / `nano-banana-fast` / `nano-banana` |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | `auto` / `1:1` / `2:3` / `3:2` / `16:9` / `9:16`。**能选哪些取决于 `model`**，见上面对照表 |
| `image_size` | `1K` / `4K`。同样取决于 `model` |
| `reply_type` | `async` / `sync`。本站禁用了异步图像生成，**选什么都不影响，都会按同步执行** |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔，默认 300 / 5 |
| `base_url` | 站点地址，默认 `https://ai.xhcyai.org` |

输出：`image` / `response_text`（摘要）/ `local_image_paths`（落盘路径）。

> **尺寸能力（2026-10-23 按站点源码补齐）**
>
> 这个家族里各变体的尺寸能力**差别很大**：
>
> | 变体 | 能用的 |
> | --- | --- |
> | `nano-banana-2` / `nano-banana-pro` | 只有 **1:1 @ 1K**（1024×1024） |
> | `gemini-nano-banana-2.1` | **五种画幅**：1:1 / 2:3 / 3:2 / 16:9 / 9:16；1:1 可选 1K 或 4K，其它走 4K 档 |
> | `nano-banana-fast` / `nano-banana` | 直通上游、站点不校验，按同族八种组合给 |
>
> 想要非方图或大图，**选 `gemini-nano-banana-2.1`**。
> 选了当前变体不支持的组合，节点会在发请求前拦下并列出它能用什么（不扣费）。
>
> **实测确认**：`gemini-nano-banana-2.1` + `2:3` + `1K` 成功出图，
> 实际尺寸 **3392×5056**（约 17 MP）——非方图会按 4K 档出，比选的档更大。
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
| **多模态参考** | **动态插槽**（见下） | 接一个就自动长出一个新插槽。全都不接 = 纯文生视频 |

> **多模态参考的插槽是动态的**（2026-10-21 改）
>
> 不再是一排固定空着的 `image1`~`image9`，而是三组「接一个长一个」的插槽：
>
> | 组 | 插槽名 | 上限 |
> | --- | --- | --- |
> | 参考图 | `ref_images.ref_image_0`、`ref_image_1` … | 9 张 |
> | 参考视频 | `ref_videos.ref_video_0`、`ref_video_1` … | 3 段 |
> | 参考音频 | `ref_audios.ref_audio_0`、`ref_audio_1` … | 3 段 |
>
> 序号从 **0** 开始，但提示词里仍按「Image 1」「Image 2」引用（节点内部会 +1 对齐）。
>
> ⚠️ **旧工作流需要重新连线**：原先接在 `image1` / `video1` / `audio1` 上的连线，
> 现在要改接到 `ref_images.ref_image_0` / `ref_videos.ref_video_0` /
> `ref_audios.ref_audio_0`。输入名变了，这是唯一的破坏性改动。

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

### XHCY Seedance 2.0 参数

走 `POST /v1/video/generations`（站点内部转发到火山引擎方舟）。
**一个节点覆盖四种用法**，靠「接了什么素材」自动判断：

| 你接了什么 | 实际走哪种模式 |
| --- | --- |
| 什么都不接 | 纯文生视频 |
| 只接 `first_frame` | 以这张图开头的图生视频 |
| `first_frame` + `last_frame` | 首尾帧过渡 |
| `image1`~`image9` / `video1`~`video3` / `audio1`~`audio3` | 多模态参考 |

**首尾帧与参考素材互斥**（Ark 的硬约束）：同时接会直接报中文错误，不会白扣费。
只接 `last_frame` 也会被拒——尾帧模式必须先给首帧。

| 输入 | 说明 |
| --- | --- |
| `prompt` | 视频描述，必填。参考图按顺序用「Image 1」「Image 2」引用 |
| `model` | `doubao-seedance-2-0`（标准）/ `-fast`（速度优先）/ `-mini`（经济） |
| `api_key` | XHCY AI 访问密钥 |
| `resolution` | `480P` / `720P` / `1080P` / `4K`（后两档只有标准版支持） |
| `duration` | 4～15 秒，按秒计费。填到范围外会自动收进合法区间并提示 |
| `ratio` | `adaptive` / `21:9` / `16:9` / `4:3` / `1:1` / `3:4` / `9:16` |
| `generate_audio` | 打开后视频带**原生同步音频**（人声/环境音/音效）。不影响价格 |
| `watermark` | 打开后右下角有平台水印。一般保持关闭 |
| `web_search` | 打开后允许模型联网检索现实资料再生成（真实地点、时事元素） |

输出：`video` / `status` / `video_path`。

**⚠️ 分辨率的写法和 H3 不一样**：Seedance 用 **720P / 4K**，H3 用 **768P / 2K**。
两套表不能混用，填错站点会直接拒。

**价格（按输出秒数，站点公示）**

| 变体 | 480P | 720P | 1080P | 4K |
| --- | --- | --- | --- | --- |
| 标准版 | 0.60 元/s | 1.29 元/s | 3.22 元/s | 6.57 元/s |
| Fast | 0.48 元/s | 1.04 元/s | — | — |
| Mini | 0.30 元/s | 0.64 元/s | — | — |

参考音频免费；**参考视频按输出分辨率同样计费**（相当于双份）。
4 秒 480P 的成本：Mini 约 1.2 元 / Fast 约 1.9 元 / 标准约 2.4 元。

**不支持 `seed` 和 `camera_fixed`**：这两个是 Seedance 1.0 的字段，
2.0 会静默忽略，所以节点里不提供，避免让你以为能控制随机性。

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

### XHCY 智能分析（多模态·角色化）

比上面的「一问一答」高一层：**上传素材 + 选角色 + 说需求 → 产出能直接接给下游节点的内容**。

| 输入 | 说明 |
| --- | --- |
| `requirement` | 你想做什么，大白话即可，必填 |
| `model` | 站点上的文本 / 多模态模型，默认 `gemini-3-flash` |
| `skill` | 角色说明书（见下表），决定模型用什么方法论、产出什么格式 |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `extra_instruction` | 额外要求，可留空 |
| `temperature` | 0～2，默认 0.6（创意任务 0.6~0.9） |
| `max_tokens` | 默认 4096，分镜类任务需要给足 |
| `image1`~`image8` | 可选参考图 |
| `video1`~`video3` | 可选参考视频，**节点会自动抽 4 帧**再发给模型 |

输出：`prompt`（提示词）/ `storyboard`（分镜）/ `params`（参数建议）/ `analysis`（分析说明）/ `status`（摘要）。

**角色（`skill`）一览**

| 角色 | 产出什么 |
| --- | --- |
| 通用创意助手 | 提示词 + 参数建议 + 分析说明 |
| H3 视频导演 | MiniMax H3 的生产级提示词 + 分镜（含 T2VA / I2VA / FL2VA / L2VA / Ref2VA 模式选择、参考图分工、连续性台账） |
| 广告创意策划 | 3 个不同角度的创意方向 + 选定方向的完整脚本 + 平台与人群建议 |
| 分镜脚本师 | 逐镜分镜表（镜号 / 时长 / 景别 / 运镜 / 光线 / 声音 / 转场） |
| 提示词工程师 | 改写后的完整版 + 精简版提示词，并指出原描述缺什么 |

**两个必须知道的限制**

- **视频要先抽帧**。站点的聊天通道只认 `image_url`，不认 `video_url`
  （源码里 `video_url` 只存在于视频适配器）。所以节点把每个视频均匀抽 4 帧
  （含首尾帧）转成图片再发过去。
- **只有视觉模型能看图**。给纯文本模型（`deepseek-v4.1-flash` / `MiniMax-Text-01` /
  `abab5.5s-chat`）接素材时，节点会直接报中文错误提示你换模型，不会白白发请求。

典型用法：`prompt` → 文生图节点的提示词；`storyboard` → 复制到别的工具；
`params` → 手动填进下游节点的分辨率 / 时长 / 比例。

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
