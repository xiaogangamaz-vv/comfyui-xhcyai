# comfyui-xhcyai

XHCY AI（[ai.xhcyai.org](https://ai.xhcyai.org)）的 ComfyUI 节点合集。
同一家族的模型合成一个节点，节点里用下拉切换变体。

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
| **XHCY GPT Image 2.5（文生图）** | 走 `POST /v1/images/generations`，下拉切换 `gpt-image-2.5` / `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst` |
| comfyui xinghuo nano banana | Nano Banana 系列（原有节点，独立于本站服务配置） |

### XHCY GPT Image 2.5 参数

| 输入 | 说明 |
| --- | --- |
| `prompt` | 图片描述，必填 |
| `model` | 家族变体：`gpt-image-2.5`（仅 1k）/ `-flare`（到 4k，质量到 high）/ `-sunburst`（到 4k，质量到 max） |
| `api_key` | XHCY AI 访问密钥，每个节点单独填 |
| `aspect_ratio` | 画幅比例，`auto` 表示交给服务端决定 |
| `resolution` | `1k` / `2k` / `4k`，节点内部换算成接口要求的像素 `size` |
| `quality` | `auto` / `low` / `medium` / `high` / `xhigh` / `max` |
| `max_poll_attempts` / `poll_interval` | 结果查询次数与间隔 |
| `base_url` | 站点地址，一般不用改 |

| 输出 | 说明 |
| --- | --- |
| `image` | 生成结果，可直接接 `SaveImage` / `PreviewImage` |
| `status` | 结果摘要（模型、画幅、任务号、文件路径） |
| `saved_paths` | 落盘文件的完整路径 |

## 实现说明

- **站点当前禁用了异步图像生成**：带 `async: true` 的请求会被直接拒绝
  （HTTP 400 `async image generation is disabled`，已实测确认），因此节点走**同步提交**。
  若服务端返回 task id，节点会自动切换为轮询 `GET /v1/images/tasks/{task_id}`。
- 尺寸在节点内由 `(画幅比例, 分辨率)` 换算成像素尺寸，接口只接受像素格式。
- 失败一律抛出可读中文错误（密钥失效、余额不足、内容审核未通过等），不会把坏图当成功返回。

## 自测

不装 ComfyUI 也能验证密钥与接口：

```bash
python test_api.py --api-key sk-xxxx --models-only
python test_api.py --api-key sk-xxxx
python test_api.py --api-key sk-xxxx --model gpt-image-2.5-flare --size 1024x1024
```

产物输出到 `probe_out/`。
