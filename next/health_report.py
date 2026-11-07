#!/usr/bin/env python3
"""设备侧体检报告渲染器（magisk-Next health report）。

App 端 NextFeatures.exportHealthJson() 导出 JSON，本工具在主机侧渲染成 Markdown
报告，便于提交 issue 或归档。demo 数据与 App 的 collectChecks() 8 个检查项
保持一致，避免文档与实际导出结果不符。

用法：
    python3 next/health_report.py --input next-health.json
    python3 next/health_report.py --demo
    python3 next/health_report.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import BRAND, NEXT_VERSION, project_root  # noqa: E402

STATUS_LABEL = {
    "ok": "正常", "warn": "需关注", "fail": "异常", "na": "不适用",
}
STATUS_ICON = {"ok": "OK", "warn": "WARN", "fail": "FAIL", "na": "N/A"}


def validate(data: dict) -> list:
    errors = []
    if not isinstance(data, dict):
        return ["根节点必须是 JSON 对象"]
    for key in ("brand", "version", "checks"):
        if key not in data:
            errors.append(f"缺少字段 {key}")
    checks = data.get("checks", [])
    if not isinstance(checks, list):
        errors.append("checks 必须是数组")
    else:
        for i, c in enumerate(checks):
            if not isinstance(c, dict) or "id" not in c or "status" not in c:
                errors.append(f"checks[{i}] 缺少 id/status")
            elif c["status"] not in STATUS_LABEL:
                errors.append(f"checks[{i}].status 非法: {c['status']}")
    return errors


def render_report(data: dict) -> str:
    errors = validate(data)
    if errors:
        return "\n".join(["# 体检报告解析失败", ""] +
                         [f"- {e}" for e in errors])
    checks = data["checks"]
    counts = {k: sum(1 for c in checks if c["status"] == k)
              for k in STATUS_LABEL}
    lines = [
        f"# {data.get('brand', BRAND)} 设备体检报告",
        "",
        f"- 版本：`{data.get('version', NEXT_VERSION)}`",
        f"- 设备：`{data.get('device', 'unknown')}`",
        f"- Android：`{data.get('android', 'unknown')}`",
        f"- 生成时间：`{data.get('generated_at', 'unknown')}`",
        f"- 更新通道：`{data.get('channel') or '未配置（沿用上游通道）'}`",
        f"- 运行体检：**{'开启' if data.get('health_enabled') is True else '关闭/未知'}**",
        f"- 结论：**{counts['ok']} 正常 / {counts['warn']} 需关注 / "
        f"{counts['fail']} 异常 / {counts['na']} 不适用**",
        "",
        "| 检查项 | 结果 | 说明 | 建议 |",
        "| --- | --- | --- | --- |",
    ]
    for c in checks:
        lines.append(
            f"| `{c['id']}` | {STATUS_ICON[c['status']]} "
            f"({STATUS_LABEL[c['status']]}) | "
            f"{str(c.get('detail', '')).replace('|', '/')} | "
            f"{str(c.get('hint', '')).replace('|', '/')} |")
    lines += ["", "---", "",
              "> 本报告由 magisk-Next 工具生成，仅做状态汇总，不包含设备唯一标识。"]
    return "\n".join(lines)


def demo_data() -> dict:
    """与 NextFeatures.collectChecks() 的 8 个 id 一一对齐。"""
    return {
        "brand": BRAND, "version": NEXT_VERSION,
        "channel": "https://example.com/magisk-next.json",
        "health_enabled": True,
        "device": "Pixel 8 Pro / husky", "android": "API 36 (16)",
        "generated_at": "2026-11-07T08:30:00Z",
        "checks": [
            {"id": "magisk.active", "status": "ok",
             "detail": "Magisk 已激活，核心版本 31.1-next.1", "hint": ""},
            {"id": "app.version", "status": "ok",
             "detail": "31.1-next.1 (1000000)", "hint": ""},
            {"id": "zygisk.enabled", "status": "ok",
             "detail": "Zygisk 已启用", "hint": ""},
            {"id": "zygisk.loaded", "status": "ok",
             "detail": "Zygisk 已加载", "hint": ""},
            {"id": "denylist.configured", "status": "warn",
             "detail": "DenyList 未强制启用", "hint": "在设置中开启 Enforce DenyList"},
            {"id": "next.module.snapshot", "status": "ok",
             "detail": "模块变更前自动快照已开启", "hint": ""},
            {"id": "next.channel.verify", "status": "ok",
             "detail": "更新通道清单校验已开启", "hint": ""},
            {"id": "app.cloak", "status": "na",
             "detail": "可选 App Cloak 插件未安装", "hint": "按需安装，见 docs/DESIGN.md"},
        ],
    }


def self_test() -> int:
    d = demo_data()
    assert not validate(d), validate(d)
    assert len(d["checks"]) == 8, "demo 数据必须与 App 的 8 项检查对齐"
    md = render_report(d)
    assert md.startswith("# ") and "| 检查项 |" in md, md
    assert "next.module.snapshot" in md and "Pixel 8 Pro" in md
    assert validate({}) and validate({"brand": "x", "version": "1",
                                     "checks": [{"id": "a", "status": "bad"}]})
    assert "解析失败" in render_report({"checks": []})
    print("health_report self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 体检报告渲染器")
    ap.add_argument("--input", type=Path, help="App 导出的 next-health.json")
    ap.add_argument("--output", type=Path, help="Markdown 输出路径（默认标准输出）")
    ap.add_argument("--demo", action="store_true", help="使用示例数据")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.input and not args.demo:
        ap.error("请提供 --input <json> 或使用 --demo")

    if args.demo:
        data = demo_data()
    else:
        try:
            data = json.loads(args.input.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"读取失败: {e}", file=sys.stderr)
            return 1
    text = render_report(data)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            print(f"写入失败: {e}", file=sys.stderr)
            return 1
        print(f"已写入 {args.output}")
    else:
        print(text)
    return 0 if not validate(data) else 1


if __name__ == "__main__":
    sys.exit(main())
