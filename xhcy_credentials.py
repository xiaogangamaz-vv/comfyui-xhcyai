"""本机凭据解析：节点上没填 key 时，回退到 DPAPI 配置里保存的那一份。

设计约束
--------
* 密钥只在内存里用，绝不写进工作流 JSON —— 所以 INPUT_TYPES 的默认值保持空串，
  而不是把 key 预填成默认值（那样每存一次工作流就泄露一次）。
* 配置存在时才回退；不存在就报一句能看懂的中文，而不是 401。
"""

from __future__ import annotations

try:
    from .xhcy_client import DEFAULT_BASE_URL, XHCYError
except ImportError:  # standalone debugging / unittest
    from xhcy_client import DEFAULT_BASE_URL, XHCYError  # type: ignore


def load_stored_config() -> dict:
    """读取本机 DPAPI 配置；没配过或解不开都返回空 dict。"""
    try:
        try:
            from .secure_config import load_config
        except ImportError:  # standalone debugging
            from secure_config import load_config  # type: ignore
        config = load_config()
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def resolve_credentials(api_key, base_url) -> tuple[str, str]:
    """返回 (api_key, base_url)；key 缺失时抛用户看得懂的错误。"""
    stored = load_stored_config()
    key = (api_key or "").strip() or str(stored.get("api_key") or "").strip()
    base = (base_url or "").strip() or str(stored.get("base_url") or "").strip().rstrip("/")
    if not key:
        raise XHCYError(
            "请填写 XHCY 访问密钥（api_key），或先在本机运行一次 secure_config.py 保存密钥"
        )
    return key, (base or DEFAULT_BASE_URL)
