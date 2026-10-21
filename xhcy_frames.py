"""ComfyUI VIDEO → 图片帧。

为什么需要它
------------
站点的聊天通道 ``/v1/chat/completions`` 只认 ``image_url``，**不认
``video_url``**（源码里 ``video_url`` 只存在于视频适配器
``relay/adaptor/minimax`` 与 ``relay/adaptor/ark``）。
所以要把视频喂给 LLM，只能先抽成图片。

抽帧策略
--------
* 均匀取 N 帧，覆盖首尾（首帧往往就是主体，尾帧决定落点）；
* 长边压到 ``max_edge`` 以内，控制 base64 体积；
* 视频很短时按实际帧数取，不重复。
"""

from __future__ import annotations

import torch


def _resize_long_edge(tensor: torch.Tensor, max_edge: int) -> torch.Tensor:
    """把 [B,H,W,C] 张量的长边压到 max_edge 以内（等比缩放）。"""
    if tensor.ndim != 4:
        return tensor
    _, height, width, channels = tensor.shape
    longest = max(height, width)
    if longest <= max_edge or longest == 0:
        return tensor

    scale = max_edge / float(longest)
    new_h = max(1, int(round(height * scale)))
    new_w = max(1, int(round(width * scale)))

    # 用双线性插值缩放（不依赖 torchvision）
    # [B,H,W,C] -> [B,C,H,W]，插值后转回 [B,H,W,C]
    src = tensor.permute(0, 3, 1, 2).contiguous()
    out = torch.nn.functional.interpolate(
        src, size=(new_h, new_w), mode="bilinear", align_corners=False
    )
    return out.permute(0, 2, 3, 1).contiguous().to(dtype=tensor.dtype)


def _pick_indices(total: int, wanted: int) -> list[int]:
    """在 total 帧里均匀取 wanted 帧，保证包含首尾。"""
    if total <= 0:
        return []
    if total <= wanted:
        return list(range(total))
    if wanted <= 1:
        return [0]
    step = (total - 1) / float(wanted - 1)
    return [min(total - 1, int(round(i * step))) for i in range(wanted)]


def video_to_frames(video, frame_count: int = 4, max_edge: int = 1024) -> list:
    """ComfyUI VIDEO 对象 → 若干 IMAGE 张量。

    返回的每一项都是 [1,H,W,C] 的 IMAGE 张量，可直接转 data URI。
    抽不出帧时返回空列表（调用方负责给用户人话提示）。
    """
    if video is None:
        return []

    frames = None

    # 1) 标准 VideoFromFile / VideoFromComponents：走 get_components()
    getter = getattr(video, "get_components", None)
    if callable(getter):
        try:
            components = getter()
            images = getattr(components, "images", None)
            if images is not None and hasattr(images, "ndim") and images.ndim == 4:
                frames = images
        except Exception:
            frames = None

    # 2) 有些节点直接给 IMAGE 张量（VideoHelperSuite 之类）
    if frames is None and hasattr(video, "ndim"):
        if video.ndim == 4:
            frames = video
        elif video.ndim == 3:
            frames = video.unsqueeze(0)

    if frames is None:
        return []

    total = int(frames.shape[0])
    if total == 0:
        return []

    wanted = max(1, int(frame_count))
    indices = _pick_indices(total, wanted)

    picked = frames[torch.tensor(indices, dtype=torch.long)]
    picked = _resize_long_edge(picked, int(max_edge))

    # 拆成单帧列表，每帧 [1,H,W,C]
    return [picked[i:i + 1] for i in range(picked.shape[0])]
