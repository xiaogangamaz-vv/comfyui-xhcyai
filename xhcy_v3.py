"""XHCY v3 适配层：让旧式 INPUT_TYPES 节点在前端能正确接收 VIDEO / AUDIO 复合类型。

背景
----
ComfyUI 新前端把 VIDEO / AUDIO 当作**复合类型**（composite type）。官方所有能
正常连线的节点都用 v3 API 声明：

    io.Video.Input("video")        # 复合类型，前端认
    ("VIDEO", {"tooltip": "..."})   # 裸字符串，前端不认 → 连线被拒

服务端 ``server.py`` 的 ``node_info()`` 里有这么一段：

    if issubclass(obj_class, _ComfyNodeInternal):
        return obj_class.GET_NODE_INFO_V1()      # v3：带复合类型元信息
    info['input'] = obj_class.INPUT_TYPES()      # 旧式：原样输出，前端不认

于是旧式节点里那个 `"VIDEO"` 只是字符串，前端拿不到复合类型标记，
「Load Video → 视频1」这类连接直接被前端拒绝。

本模块用**组合**（不是继承）把旧节点包成 v3 节点：
* 旧节点的 INPUT_TYPES / 执行逻辑 / 返回类型**一个字都不改**；
* 只把媒体输入换成 v3 的复合类型声明；
* 其余输入按旧式写法转换过去。

用法::

    from .xhcy_v3 import as_v3_node

    NODE_CLASS_MAPPINGS = {
        "my_node": as_v3_node(MyOldNode, "my_node", "我的节点"),
    }
"""

from __future__ import annotations

from typing import Any

try:
    from comfy_api.latest import io
    _V3_AVAILABLE = True
except Exception:  # pragma: no cover - 极老的 ComfyUI 没有 v3 API
    io = None
    _V3_AVAILABLE = False


# 旧式类型名 → v3 复合类型类名
_COMPOSITE_TYPES = {
    "VIDEO": "Video",
    "AUDIO": "Audio",
    "IMAGE": "Image",
}


def _composite_input(type_name: str, name: str, options: dict):
    """把一个媒体类型输入转成 v3 的复合类型 Input。"""
    kind = _COMPOSITE_TYPES.get(type_name)
    if kind is None:
        return None
    cls = getattr(io, kind, None)
    if cls is None:
        return None
    tooltip = (options or {}).get("tooltip")
    optional = bool((options or {}).get("optional", True))
    try:
        return cls.Input(name, tooltip=tooltip, optional=optional)
    except TypeError:
        return cls.Input(name, tooltip=tooltip)


def _plain_input(name: str, spec: Any):
    """把一个普通输入（字符串/下拉/数字/布尔）转成 v3 Input。

    ⚠️ 下拉必须用 ``io.Combo``：旧式写法把候选列表放在「类型」位置
    （``(["A", "B"], {...})``），而 v3 的 ``get_finalized_class_inputs`` 会拿
    这个 list 去 ``io_type in DYNAMIC_INPUT_LOOKUP`` 里查 → ``unhashable
    type: 'list'``。所以这里必须先识别出「类型是 list」的情况。
    """
    options: dict = {}
    kind = spec
    if isinstance(spec, (list, tuple)):
        kind = spec[0]
        if len(spec) > 1 and isinstance(spec[1], dict):
            options = dict(spec[1])

    # 旧式下拉：类型位置直接是候选列表
    if isinstance(kind, (list, tuple)):
        choices = [str(c) for c in kind]
        default = options.get("default", choices[0] if choices else "")
        if default not in choices and choices:
            default = choices[0]
        return io.Combo.Input(
            name,
            options=choices,
            default=default,
            tooltip=options.get("tooltip"),
        )

    kind = str(kind)

    if kind == "STRING":
        return io.String.Input(
            name,
            multiline=bool(options.get("multiline", False)),
            default=options.get("default", ""),
            tooltip=options.get("tooltip"),
        )
    if kind == "INT":
        return io.Int.Input(
            name,
            default=int(options.get("default", 0)),
            min=int(options.get("min", 0)),
            max=int(options.get("max", 2 ** 31 - 1)),
            step=int(options.get("step", 1)),
            tooltip=options.get("tooltip"),
        )
    if kind == "FLOAT":
        return io.Float.Input(
            name,
            default=float(options.get("default", 0.0)),
            min=float(options.get("min", 0.0)),
            max=float(options.get("max", 1e9)),
            step=float(options.get("step", 0.01)),
            tooltip=options.get("tooltip"),
        )
    if kind == "BOOLEAN":
        return io.Boolean.Input(
            name,
            default=bool(options.get("default", False)),
            tooltip=options.get("tooltip"),
        )
    if isinstance(spec, (list, tuple)) and isinstance(spec[0], (list, tuple)):
        choices = list(spec[0])
        default = options.get("default", choices[0] if choices else "")
        return io.Combo.Input(
            name,
            options=choices,
            default=default,
            tooltip=options.get("tooltip"),
        )
    return io.String.Input(
        name, default=str(options.get("default", "")), tooltip=options.get("tooltip")
    )


def _build_v3_inputs(old_inputs: dict) -> list:
    """把旧式 {required:..., optional:...} 转成 v3 的 inputs 列表。"""
    result = []
    for section in ("required", "optional"):
        block = old_inputs.get(section) or {}
        for name, spec in block.items():
            options: dict = {}
            kind = spec
            if isinstance(spec, (list, tuple)):
                kind = spec[0]
                if len(spec) > 1 and isinstance(spec[1], dict):
                    options = dict(spec[1])
            if section == "optional":
                options.setdefault("optional", True)

            # 媒体类型（VIDEO / AUDIO / IMAGE）走复合类型
            composite = None
            if isinstance(kind, str):
                composite = _composite_input(kind, name, options)
            if composite is not None:
                result.append(composite)
            else:
                result.append(_plain_input(name, spec))
    return result


def _plain_output(type_name: str, name: str):
    """输出端：VIDEO / IMAGE 走复合类型，其余按字符串。"""
    if type_name == "VIDEO":
        return io.Video.Output(display_name=name)
    if type_name == "IMAGE":
        return io.Image.Output(display_name=name)
    return io.String.Output(display_name=name)


def as_v3_node(cls, node_id: str | None = None, display_name: str | None = None):
    """把一个旧式节点类包装成 v3 节点。

    旧节点的 INPUT_TYPES / 执行逻辑 / 返回类型全部保持不变，只把媒体输入
    换成前端认的复合类型声明。

    ``node_id`` / ``display_name`` 可显式传入；不传则依次尝试节点类上的
    ``NODE_ID`` / ``DISPLAY_NAME`` 属性，最后退化为类名。
    """
    if not _V3_AVAILABLE:
        return cls

    old_inputs = cls.INPUT_TYPES()
    return_types = list(getattr(cls, "RETURN_TYPES", ("STRING",)))
    return_names = list(getattr(cls, "RETURN_NAMES", return_types))
    category = getattr(cls, "CATEGORY", "sd")
    description = getattr(cls, "DESCRIPTION", "") or ""
    is_output_node = bool(getattr(cls, "OUTPUT_NODE", False))

    resolved_id = node_id or getattr(cls, "NODE_ID", None) or cls.__name__.lower()
    resolved_name = display_name or getattr(cls, "DISPLAY_NAME", None) or cls.__name__
    # 旧节点的执行方法名（generate / enhance / analyze / chat …）
    func_name = getattr(cls, "FUNCTION", "generate")

    class _XHCYV3Adapter(io.ComfyNode):
        @classmethod
        def define_schema(cls2):
            return io.Schema(
                node_id=resolved_id,
                display_name=resolved_name,
                category=category,
                description=description,
                inputs=_build_v3_inputs(old_inputs),
                outputs=[
                    _plain_output(t, n) for t, n in zip(return_types, return_names)
                ],
                is_output_node=is_output_node,
            )

        @classmethod
        def execute(cls2, **kwargs):
            # v3 的 execute 是类方法，转回旧节点的实例方法调用方式
            instance = cls.__new__(cls)
            return getattr(instance, func_name)(**kwargs)

    _XHCYV3Adapter.__name__ = cls.__name__
    _XHCYV3Adapter.__qualname__ = cls.__qualname__
    _XHCYV3Adapter.NODE_ID = resolved_id
    _XHCYV3Adapter.DISPLAY_NAME = resolved_name
    # 保留旧类的常量，方便外部引用
    _XHCYV3Adapter.RETURN_TYPES = tuple(return_types)
    _XHCYV3Adapter.RETURN_NAMES = tuple(return_names)
    _XHCYV3Adapter.CATEGORY = category
    _XHCYV3Adapter.OUTPUT_NODE = is_output_node
    # 把原节点的规格常量也透传出去，方便外部（测试、审查脚本、其他插件）
    # 直接读「这个节点支持什么」。运行时并不依赖这些——execute 用的是原类
    # 实例，self 上的属性访问本来就正常。
    for _attr in (
        "VARIANT_MODELS",
        "RESOLUTION_LIMITS",
        "RATIO_LIMITS",
        "DURATION_LIMITS",
        "MEDIA_LIMITS",
        "PROMPT_MAX_CHARS",
        "DEFAULT_MODEL",
        "DEFAULT_RESOLUTION",
        "DEFAULT_DURATION",
        "DEFAULT_RATIO",
        "RESOLUTIONS",
        "RATIOS",
        "MODEL_SIZES",
        "SIZE_MAP",
        "QUALITIES",
        "MAX_REFERENCES",
    ):
        if hasattr(cls, _attr):
            setattr(_XHCYV3Adapter, _attr, getattr(cls, _attr))
    # 把旧节点的执行方法也挂到适配类上，外部代码（测试、其他插件）仍可
    # 像以前一样 ``node = cls(); node.generate(...)`` 这样调用。
    # ⚠️ 必须建一个**原类的实例**来执行：原类方法里的 self 语义（属性访问、
    #    方法调用）都指向原类，不能用适配类的实例。
    def _legacy_call(self, **kwargs):
        legacy_instance = cls.__new__(cls)
        return getattr(legacy_instance, func_name)(**kwargs)

    _legacy_call.__name__ = func_name
    _legacy_call.__doc__ = (
        f"旧式调用入口，转发到原节点的 {func_name}()。"
    )
    setattr(_XHCYV3Adapter, func_name, _legacy_call)
    # 故意**不覆盖** INPUT_TYPES：v3 的 INPUT_TYPES 由 schema 自动生成，
    # 里面下拉的类型是 "COMBO" 字符串。若这里塞回旧式 dict（候选列表放在
    # 类型位置），execution.py 走 v3 分支时会在
    # comfy_api/latest/_io.py 的 `io_type in DYNAMIC_INPUT_LOOKUP` 处抛
    # `unhashable type: 'list'`。
    return _XHCYV3Adapter
