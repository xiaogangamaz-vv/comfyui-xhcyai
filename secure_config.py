"""Local credential storage.

Optional credentials use Windows DPAPI and never enter a workflow.
"""

import base64
import ctypes
import getpass
import json
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


CONFIG_FILE = Path(__file__).with_name("xinghuo.secure.dpapi")
_SERVICE_PROFILE_NONCE = ""
_SERVICE_PROFILE_CIPHERTEXT = ""
_SERVICE_PROFILE_KEY_SHARES = ()
_SERVICE_PROFILE_AAD = ""
class ConfigError(RuntimeError):
    pass


def _decode_urlsafe(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


@lru_cache(maxsize=1)
def _locked_service_profile() -> dict:
    """Decrypt the portable service profile and reject tampered metadata.

    The embedded split key prevents plaintext endpoint strings in distributed
    source. Because the client must connect to the service, this is not a
    substitute for a server-side gateway against local reverse engineering.
    """
    try:
        shares = [_decode_urlsafe(value) for value in _SERVICE_PROFILE_KEY_SHARES]
        if len(shares) != 3 or any(len(value) != 32 for value in shares):
            raise ValueError("invalid service key shares")
        key = bytes(first ^ second ^ third for first, second, third in zip(*shares))
        plaintext = AESGCM(key).decrypt(
            _decode_urlsafe(_SERVICE_PROFILE_NONCE),
            _decode_urlsafe(_SERVICE_PROFILE_CIPHERTEXT),
            _decode_urlsafe(_SERVICE_PROFILE_AAD),
        )
        profile = json.loads(plaintext.decode("utf-8"))
        origin = profile.get("origin")
        routes = profile.get("routes")
        parsed = urlparse(origin if isinstance(origin, str) else "")
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid service origin")
        if not isinstance(routes, dict) or set(routes) != {"balance", "submit", "result"}:
            raise ValueError("invalid service routes")
        if any(not isinstance(value, str) or not value.startswith("/") or "://" in value for value in routes.values()):
            raise ValueError("invalid service route")
    except (InvalidTag, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigError("节点加密服务配置无效或已损坏") from exc
    return {"origin": origin.rstrip("/"), "routes": dict(routes)}


def load_locked_service_profile() -> dict:
    profile = _locked_service_profile()
    return {"origin": profile["origin"], "routes": dict(profile["routes"])}


def load_locked_service_origin() -> str:
    return load_locked_service_profile()["origin"]


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def _blob(data: bytes):
    backing = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _Blob(len(data), backing), backing


def _protect(data: bytes) -> bytes:
    source, _ = _blob(data)
    target = _Blob()
    if not _crypt32.CryptProtectData(ctypes.byref(source), "XINGHUO secure configuration", None, None, None, 0, ctypes.byref(target)):
        raise ConfigError(f"无法使用 Windows DPAPI 加密配置：{ctypes.get_last_error()}")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        _kernel32.LocalFree(target.pbData)


def _unprotect(data: bytes) -> bytes:
    source, _ = _blob(data)
    target = _Blob()
    if not _crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ConfigError("无法解密服务配置；请使用当前 Windows 用户重新执行 secure_config.py")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        _kernel32.LocalFree(target.pbData)


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        raise ConfigError("未配置 XINGHUO 加密凭据。请运行 secure_config.py 创建本机 DPAPI 配置。")
    try:
        config = json.loads(_unprotect(base64.b64decode(CONFIG_FILE.read_bytes())).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ConfigError("XINGHUO 加密配置无效或已损坏") from exc
    if not isinstance(config.get("base_url"), str) or not isinstance(config.get("api_key"), str) or not isinstance(config.get("profiles"), dict):
        raise ConfigError("XINGHUO 加密配置缺少必需字段")
    return config


def configure_interactively():
    print("所有值只写入当前 Windows 用户可解密的 XINGHUO DPAPI 文件，不会写入工作流。")
    base_url = input("XINGHUO 服务地址（例如 https://...）: ").strip().rstrip("/")
    api_key = getpass.getpass("访问密钥（输入不回显）: ").strip()
    profile_text = input("XINGHUO 模型配置（显示名=内部模型标识，逗号分隔）: ").strip()
    extended_text = input("支持扩展比例的显示名（可留空，逗号分隔）: ").strip()
    profiles = {}
    for pair in profile_text.split(","):
        label, separator, model = pair.partition("=")
        if not separator or not label.strip() or not model.strip():
            raise ConfigError("模型配置格式错误")
        profiles[label.strip()] = model.strip()
    if not base_url.startswith("https://") or not api_key or not profiles:
        raise ConfigError("服务地址必须为 HTTPS，且访问密钥与模型配置不能为空")
    config = {"base_url": base_url, "api_key": api_key, "profiles": profiles,
              "extended_ratio_profiles": [name.strip() for name in extended_text.split(",") if name.strip()]}
    if any(name not in profiles for name in config["extended_ratio_profiles"]):
        raise ConfigError("扩展比例配置中包含未定义的显示名")
    CONFIG_FILE.write_bytes(base64.b64encode(_protect(json.dumps(config, ensure_ascii=False).encode("utf-8"))))
    print(f"已创建加密配置：{CONFIG_FILE}")


if __name__ == "__main__":
    configure_interactively()
