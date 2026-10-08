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

| 节点 | 说明 |
| --- | --- |
| **XHCY GPT Image 2.5（文生图 / 多图参考）** | 一个节点两种用法：不接参考图 = 文生图，接 `image1`~`image16` = 多图参考。下拉切换 `gpt-image-2.5` / `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst` |
| **XHCY Nano Banana（文生图 / 多图参考）** | 同样两种用法。下拉切换 `nano-banana-2` / `nano-banana-pro` / `nano-banana-fast`。该家族**只支持 1024x1024**，所以节点上不显示画幅 / 分辨率 / 画质下拉 |
| **XHCY MiniMax H3（文生视频）** | 走 `POST /v1/video/generations`，下拉切换 `MiniMax-H3` / `MiniMax-H3-Max` / `MiniMax-H3-Lite` |
| **XHCY MiniMax H3（首尾帧 / 图生视频）** | 接 `first_frame` / `last_frame`，让视频从指定画面开始、到指定画面结束；只接一张就是普通图生视频 |
| **XHCY MiniMax H3（多模态参考）** | 接 `image1`~`image9`（参考图）、`video1`~`video3`（参考视频）、`audio1`~`audio3`（参考音频）；什么都不接就是纯文生视频 |
| comfyui xinghuo nano banana | 旧节点（打的是另一家服务，与本站无关，保留兼容） |

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

| 输出 | 说明 |
| --- | --- |
| `image` | 生成结果，可直接接 `SaveImage` / `PreviewImage` |
| `status` | 结果摘要（模式、模型、画幅、任务号、文件路径） |
| `saved_paths` | 落盘文件的完整路径 |

#### 两种用法

- **文生图**：只填 `prompt`，参考图一个都不连。
- **多图参考**：把参考图接到 `image1`、`image2` …，提示词描述「要拿这些图做什么」。
  实测接 2 张 512×512 参考图，生成结果正确合并了两张图的元素。

> **参考图越多越慢**：实测带 1 张参考图约 80 秒，而网关的等待上限约 100 秒。
> 建议一次不超过 3～4 张；真超时了节点会明确提示（HTTP 524），不会静默失败。

### XHCY Nano Banana 参数

控件顺序与常用参考节点一致：

| 输入 | 说明 |
| --- | --- |
| `image1` ~ `image16` | **可选**。一个都不接 = 文生图；接 1 张以上 = 多图参考 |
| `prompt` | 提示词，必填 |
| `model` | `nano-banana-2`（推荐，实测最稳）/ `gemini-nano-banana-2.1` / `nano-banana-pro` / `nano-banana-fast` |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | 画面比例，默认 `1:1`。**本站实测只支持 1:1**，选其它比例会被站点拒绝 |
| `image_size` | `1K` / `2K` / `4K`，默认 `1K`。**本站实测只支持 1K（1024×1024）** |
| `reply_type` | `async` / `sync`。本站禁用了异步图像生成，**选什么都不影响，都会按同步执行** |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔，默认 300 / 5 |
| `base_url` | 站点地址，默认 `https://ai.xhcyai.org` |

| 输出 | 说明 |
| --- | --- |
| `image` | 生成结果，可直接接 `SaveImage` / `PreviewImage` |
| `response_text` | 结果摘要（模式、模型、尺寸、文件路径） |
| `local_image_paths` | 落盘文件的完整路径 |

> **尺寸限制（实测）**：该家族只接受 `1024x1024`，传 `2048x2048` 或 `1536x1024`
> 都会返回 `size_not_supported`。所以 `aspect_ratio` / `image_size` 虽然按参考节点
> 给了全量选项，但真正可用的是 **1:1 + 1K**；选到别的组合时节点会直接说明原因，
> 不会让你对着服务端的报错猜。`auto` 会自动按 1024×1024 处理。
>
> **速度差异**：实测带一张参考图时，`nano-banana-2` 约 51 秒，
> 而 `gemini-nano-banana-2.1` 要约 **106 秒**——已经贴近网关的 100 秒等待上限，
> 参考图较多时建议优先用 `nano-banana-2`。

### XHCY MiniMax H3 参数

| 输入 | 说明 |
| --- | --- |
| `prompt` | 视频描述，必填 |
| `model` | 家族变体：`MiniMax-H3`（支持 2K）/ `MiniMax-H3-Max`（更快）/ `MiniMax-H3-Lite`（最短 1 秒） |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `resolution` | `768P` / `2K` / `480P`，按所选模型自动校验 |
| `duration` | 时长（秒），按秒计费 |
| `ratio` | 画面比例，`adaptive` 表示由服务端决定 |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔 |
| `base_url` | 站点地址，一般不用改 |

| 输出 | 说明 |
| --- | --- |
| `video` | ComfyUI 官方 VIDEO 类型，可直接接 `SaveVideo` / `PreviewVideo` |
| `status` | 结果摘要（模型、规格、任务号、文件路径） |
| `video_path` | 落盘 MP4 的完整路径 |

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
> 素材会被转成 **data URI 内嵌进请求**（站点没有上传接口），所以素材越大、请求越慢。
> 节点内已做压缩：参考图缩到长边 1536 并转 JPEG，参考视频单条上限 12 MiB，
> 参考音频转 WAV、上限同为 12 MiB（约 6 分钟）。

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
  `reference_image` / `reference_video` / `reference_audio`，都以 data URI 放进 `content` 数组。
- **不信任本地代理**：实测本机 `HTTP_PROXY` 在请求体稍大（带参考素材）时会直接掐断连接并报
  `ProxyError`，而同一请求直连正常。因此客户端**默认直连**，只有直连失败才回退到环境代理。
- 站点目前**没有**「视频再生成（768P→2K）」和「Context-IR 提示词增强」的接口：
  相关路径全部返回 404，也没有对应的模型名（`MiniMax-H3-Context-IR` 会报
  `no available channel`）。计费表里虽有这两项 SKU，但功能尚未开放。

## 新增图像模型（套用模板）

图像节点的公共逻辑全部集中在 `xhcy_image_base.py` 的 `XHCYImageBase`：
多图参考、提交、轮询、落盘、错误翻译都在基类里。
新增一个图像模型只需要复制 `nodes_gpt_image_25.py`，改这几处常量：

| 常量 | 作用 |
| --- | --- |
| `VARIANT_MODELS` | 下拉里出现的模型名 |
| `RATIOS` / `RESOLUTIONS` / `SIZE_MAP` | 画幅比例、分辨率档位、以及两者的像素换算表 |
| `RESOLUTION_LIMITS` / `QUALITIES` | 各变体支持的分辨率与画质档；`QUALITIES = []` 表示该模型没有画质档，节点不显示 `quality` |
| `FIXED_SIZE` | 模型只吃单一尺寸时填，例如 `"1024x1024"`；填了就不显示画幅 / 分辨率下拉 |
| `NODE_ID` / `OUTPUT_PREFIX` | 节点唯一 ID 与落盘文件名前缀 |
| `NODE_DISPLAY_NAME_MAPPINGS` | 节点在面板里的显示名 |

## 自测

不装 ComfyUI 也能验证密钥与接口：

```bash
python test_api.py --api-key sk-xxxx --models-only
python test_api.py --api-key sk-xxxx
python test_api.py --api-key sk-xxxx --model gpt-image-2.5-flare --size 1024x1024
```

产物输出到 `probe_out/`。
