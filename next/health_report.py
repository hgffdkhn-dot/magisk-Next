#!/usr/bin/env python3
"""设备侧体检报告渲染器（magisk-Next health report）。

App 端 NextFeatures.exportHealth() 导出 JSON，本工具在主机侧渲染成 Markdown
报告，便于提交 issue 或归档。

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
    return {
        "brand": BRAND, "version": NEXT_VERSION,
        "device": "Pixel 8 Pro / husky", "android": "16 (API 36)",
        "generated_at": "2026-11-07T08:30:00Z",
        "checks": [
            {"id": "magisk.active", "status": "ok", "detail": "Magisk 已激活，版本 31.1-next.1", "hint": ""},
            {"id": "su.available", "status": "ok", "detail": "su 可执行，UID 0", "hint": ""},
            {"id": "zygisk.enabled", "status": "ok", "detail": "Zygisk 已启用", "hint": ""},
            {"id": "denylist.configured", "status": "warn", "detail": "DenyList 未强制执行", "hint": "在设置中开启 Enforce DenyList"},
            {"id": "modules.count", "status": "ok", "detail": "已安装 3 个模块", "hint": ""},
            {"id": "module.snapshot", "status": "warn", "detail": "模块快照功能未开启", "hint": "开启后可在变更模块前自动快照"},
            {"id": "boot.slot", "status": "ok", "detail": "当前槽位 _a，备份存在", "hint": ""},
            {"id": "app.cloak", "status": "na", "detail": "可选 App Cloak 未安装", "hint": "按需安装，见 docs/DESIGN.md"},
        ],
    }


def self_test() -> int:
    d = demo_data()
    assert not validate(d), validate(d)
    md = render_report(d)
    assert md.startswith("# ") and "| 检查项 |" in md, md
    assert "module.snapshot" in md and "Pixel 8 Pro" in md
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
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {args.output}")
    else:
        print(text)
    return 0 if not validate(data) else 1


if __name__ == "__main__":
    sys.exit(main())
