"""XHCY 接口自测脚本（独立于 ComfyUI，只依赖 requests）。

用途：拿到 API Key 后，先在这里把接口跑通、把真实响应结构打出来，
再回填到 ComfyUI 节点里，避免节点写完却和真实返回对不上。

用法：
  python test_api.py --api-key sk-xxxx
  python test_api.py --api-key sk-xxxx --models-only        # 只列模型，不生成
  python test_api.py --api-key sk-xxxx --model gpt-image-2.5 --size 1024x1024
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from xhcy_client import (  # noqa: E402
    DEFAULT_BASE_URL,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    XHCYClient,
    XHCYError,
    extract_failure_reason,
    extract_image_urls,
    extract_status,
    extract_task_id,
)

SEP = "-" * 74


def show(title: str, payload) -> None:
    print(f"\n{SEP}\n[{title}]\n{SEP}")
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
    except (TypeError, ValueError):
        print(repr(payload)[:4000])


def run(args) -> int:
    client = XHCYClient(args.api_key, args.base_url)
    print(f"服务地址：{client.base_url}")

    # 1) 列出模型
    try:
        raw = client.get_json("/v1/models", "获取模型列表")
        show("GET /v1/models 原始返回", raw)
        models = client.list_models()
        print(f"\n可用模型 {len(models)} 个：")
        for name in models:
            mark = "  <= 目标" if name in args.models.split(",") else ""
            print(f"   - {name}{mark}")
        for wanted in args.models.split(","):
            wanted = wanted.strip()
            if wanted and wanted not in models:
                print(f"   !! 目标模型 {wanted} 不在可用列表里")
    except XHCYError as exc:
        print(f"\n[模型列表失败] {exc}")

    if args.models_only:
        return 0

    # 2) 逐个模型实际生成
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n产物目录：{out_dir}")

    failures = 0
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"\n{SEP}\n>>> 测试模型 {model}\n{SEP}")
        payload = {
            "model": model,
            "prompt": args.prompt,
            "size": args.size,
            "n": 1,
            "response_format": "url",
        }
        if args.async_mode:
            payload["async"] = True
        show(f"{model} 提交用的请求体", payload)

        started = time.time()
        try:
            first = client.submit_image(payload)
        except XHCYError as exc:
            print(f"[提交失败] {exc}")
            failures += 1
            continue

        show(f"{model} 提交后的原始返回", first)
        status = extract_status(first)
        task_id = extract_task_id(first)
        print(f"解析结果 -> status={status!r} task_id={task_id!r} "
              f"直出图片={len(extract_image_urls(first))} 张")

        result = first
        if not extract_image_urls(first) and status not in STATUS_FAILURE and task_id:
            for attempt in range(1, args.max_attempts + 1):
                time.sleep(args.interval)
                try:
                    current = client.poll_image(task_id)
                except XHCYError as exc:
                    print(f"  第 {attempt} 次查询出错：{exc}")
                    continue
                status = extract_status(current)
                print(f"  第 {attempt} 次查询 -> status={status!r}")
                if attempt == 1:
                    show(f"{model} 轮询返回结构（首个样本）", current)
                if status in STATUS_SUCCESS or (
                    status not in STATUS_FAILURE and extract_image_urls(current)
                ):
                    result = current
                    break
                if status in STATUS_FAILURE:
                    print(f"  生成失败：{extract_failure_reason(current)}")
                    break
            else:
                print("  轮询次数用尽，未拿到终态")

        urls = extract_image_urls(result)
        if not urls:
            print("[没有拿到图片]")
            failures += 1
            continue

        for index, url in enumerate(urls, start=1):
            try:
                raw = client.download(url)
            except XHCYError as exc:
                print(f"  下载失败：{exc}")
                failures += 1
                continue
            ext = os.path.splitext(url.split("?")[0])[1] or ".png"
            target = os.path.join(out_dir, f"{model}_{index}{ext}")
            with open(target, "wb") as handle:
                handle.write(raw)
            print(f"  已保存 {len(raw)} 字节 -> {target}")
        print(f"  耗时 {time.time() - started:.1f} 秒")

    print(f"\n{SEP}\n完成：{len(args.models.split(','))} 个模型，失败 {failures} 个\n{SEP}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="XHCY AI 接口自测")
    parser.add_argument("--api-key", required=True, help="XHCY 访问密钥")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--models",
        default="gpt-image-2.5,gpt-image-2.5-flare,gpt-image-2.5-sunburst",
        help="逗号分隔的模型名",
    )
    parser.add_argument("--models-only", action="store_true", help="只列模型，不实际生成")
    parser.add_argument("--model", help="只测这一个模型（覆盖 --models）")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--prompt", default="a red panda sleeping on a mossy branch, soft morning light")
    parser.add_argument("--out", default="probe_out")
    parser.add_argument("--interval", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=40)
    parser.add_argument("--async", dest="async_mode", action="store_true",
                        help="发送 async 字段走异步（站点当前禁用，默认同步提交）")
    args = parser.parse_args()
    if args.model:
        args.models = args.model
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
