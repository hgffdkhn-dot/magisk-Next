#!/usr/bin/env python3
"""仓库一致性静态校验（magisk-Next）。

不依赖 Android SDK，可在 CI 中直接运行。检查 10 项：
  1. 所有 Python 源码语法
  2. 资源 XML 合法性 + Next 文案中英文齐全
  3. Kotlin 里 CoreR.string.next_* 引用均有定义
  4. Kotlin 引用的上游符号（Info/Config/BuildConfig/组件）真实存在
  5. build.py 的 next.* 映射与 config.prop.sample 一致
  6. next.* 配置闭环：flags.prop → Plugin.kt → BuildConfig → App
  7. 每个 next/*.py 工具都带 --self-test
  8. 新增 shell 脚本语法
  9. .gitmodules 与工具箱 SUBMODULES 常量一致
 10. native 核心增强静态守卫（12 条规则，防止 rebase 回滚修复）

用法：python3 next/verify_repo.py [--json] [--self-test]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    FAIL, PASS, SUBMODULES, WARN, exit_code, project_root, render_checks,
)
import api_audit  # noqa: E402
import native_audit  # noqa: E402

NEXT_STRINGS = (
    "next_section_title", "next_snapshot_title", "next_snapshot_summary",
    "next_channel_verify_title", "next_channel_verify_summary",
    "next_health_check_title", "next_health_check_summary",
    "next_export_button", "next_health_disabled",
)
NEXT_SHELL = (
    "scripts/bootstrap-submodules.sh",
    "scripts/next-build.sh",
    "scripts/verify-next.sh",
)
# build.py 注入 flags.prop 的键，必须在 Gradle 侧被消费
NEXT_FLAGS = ("nextBrand", "nextChannel", "nextModuleSnapshot", "nextChannelVerify")


def _result(name, ok, detail_ok, detail_bad, hint="", level=FAIL):
    return {"name": name, "status": PASS if ok else level,
            "detail": detail_ok if ok else detail_bad, "hint": hint}


def check_python(root: Path) -> dict:
    files = sorted((root / "next").glob("*.py")) + \
        sorted((root / "tests").glob("*.py")) + [root / "build.py"]
    bad = []
    for f in files:
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")
        except SyntaxError as e:
            bad.append(f"{f.name}:{e.lineno}")
    return _result("python syntax", not bad, f"{len(files)} 个文件",
                   "语法错误: " + ", ".join(bad))


def check_resources(root: Path) -> dict:
    res = root / "app/core/src/main/res"
    problems = []
    parsed = {}
    for f in sorted(res.glob("values*/strings.xml")):
        try:
            tree = ET.parse(f)
            parsed[f.parent.name] = {
                e.get("name") for e in tree.getroot().findall("string")}
        except ET.ParseError as e:
            problems.append(f"{f.relative_to(root)}: {e}")
    if problems:
        return _result("resource xml", False, "", "; ".join(problems))

    base = parsed.get("values", set())
    zh = parsed.get("values-zh-rCN", set())
    missing_en = [s for s in NEXT_STRINGS if s not in base]
    missing_zh = [s for s in NEXT_STRINGS if s not in zh]
    ok = not missing_en and not missing_zh
    return _result(
        "resource xml", ok,
        f"{len(parsed)} 个 strings.xml 可解析，{len(NEXT_STRINGS)} 条 Next 文案中英齐全",
        f"缺少英文 {missing_en} / 中文 {missing_zh}",
        "在 values/strings.xml 与 values-zh-rCN/strings.xml 补齐")


def check_kotlin_refs(root: Path) -> dict:
    base = root / "app/core/src/main/res/values/strings.xml"
    defined = {e.get("name") for e in ET.parse(base).getroot().findall("string")}
    refs = set()
    for f in (root / "app/apk/src/main/java").rglob("*.kt"):
        refs.update(re.findall(r"CoreR\.string\.(next_\w+)",
                               f.read_text(encoding="utf-8", errors="replace")))
    missing = sorted(refs - defined)
    return _result("kotlin resources", not missing,
                   f"{len(refs)} 个 next_* 引用均已定义",
                   "未定义: " + ", ".join(missing),
                   "补齐 string 资源或修正引用")


def check_kotlin_api(root: Path) -> dict:
    problems = api_audit.audit(root)
    s = api_audit.summary(root)
    return _result("kotlin api", not problems,
                   f"{s['referenced']} 个上游引用均有定义",
                   "; ".join(p["message"] for p in problems),
                   "运行 python3 next/api_audit.py 查看详情")


def check_build_props(root: Path) -> dict:
    bp = (root / "build.py").read_text(encoding="utf-8")
    sample = (root / "config.prop.sample").read_text(encoding="utf-8")
    mapped = set(re.findall(r'"next\.(\w+)":\s*\(', bp))
    documented = set(re.findall(r"^next\.(\w+)=", sample, re.M))
    missing_doc = sorted(mapped - documented)
    extra_doc = sorted(documented - mapped)
    ok = not missing_doc and not extra_doc
    return _result("next.* config", ok,
                   f"build.py 映射 {len(mapped)} 项，样例文档齐全",
                   f"缺文档 {missing_doc} / 样例多出 {extra_doc}",
                   "同步 build.py 的 next_props 与 config.prop.sample")


def _snake(flag: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", flag).upper()


def check_next_buildconfig(root: Path) -> dict:
    """next.* 不能只写进 flags.prop 就结束，必须有 Gradle 侧消费链路。"""
    bp = (root / "build.py").read_text(encoding="utf-8")
    plugin = (root / "app/build-logic/src/main/java/Plugin.kt").read_text(encoding="utf-8")
    gradle = (root / "app/core/build.gradle.kts").read_text(encoding="utf-8")
    missing = []
    for flag in NEXT_FLAGS:
        if f"{flag}=" not in bp:
            missing.append(f"build.py 未注入 {flag}")
        if not re.search(rf"\bval\s+{flag}\b", plugin):
            missing.append(f"Plugin.kt 缺 val {flag}")
        if f'"{_snake(flag)}"' not in gradle:
            missing.append(f"build.gradle.kts 缺 buildConfigField {_snake(flag)}")
    return _result("next.* buildconfig", not missing,
                   f"{len(NEXT_FLAGS)} 项配置已贯通 flags.prop → BuildConfig",
                   "; ".join(missing),
                   "补齐 Plugin.kt getter 与 core/build.gradle.kts 的 buildConfigField")


def check_tool_selftests(root: Path) -> dict:
    skip = {"__init__.py", "next_common.py"}
    bad = []
    tools = sorted(f for f in (root / "next").glob("*.py") if f.name not in skip)
    for f in tools:
        text = f.read_text(encoding="utf-8")
        if "def self_test" not in text or '"--self-test"' not in text:
            bad.append(f.name)
    return _result("tool self-tests", not bad, f"{len(tools)} 个工具均带 --self-test",
                   "缺少自测: " + ", ".join(bad),
                   "为新工具补 self_test() 与 --self-test 参数")


def check_shell(root: Path) -> dict:
    bad = []
    for rel in NEXT_SHELL:
        f = root / rel
        if not f.is_file():
            bad.append(f"{rel}: 缺失")
            continue
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if r.returncode:
            bad.append(f"{rel}: {r.stderr.strip()[:80]}")
    return _result("shell syntax", not bad, f"{len(NEXT_SHELL)} 个脚本",
                   "; ".join(bad))


def check_submodules(root: Path) -> dict:
    text = (root / ".gitmodules").read_text(encoding="utf-8")
    paths = set(re.findall(r"^\s*path\s*=\s*(\S+)", text, re.M))
    ok = paths == set(SUBMODULES)
    return _result("submodule list", ok,
                   f"{len(SUBMODULES)} 项一致",
                   f"仅 .gitmodules: {sorted(paths - set(SUBMODULES))} / "
                   f"仅工具箱: {sorted(set(SUBMODULES) - paths)}",
                   "同步 .gitmodules 与 next/next_common.py")


def check_native_audit(root: Path) -> dict:
    """native 修复不能被 rebase / 合并上游悄悄回滚。"""
    problems = native_audit.audit(root)
    s = native_audit.summary(root)
    return _result("native guards", not problems,
                   f"{s['rules']} 条规则 / {s['assertions']} 项断言通过",
                   "; ".join(f"{p['code']}: {p['message']}" for p in problems[:6]),
                   "运行 python3 next/native_audit.py 查看详情")


def run_all(root: Path) -> list:
    return [check_python(root), check_resources(root),
            check_kotlin_refs(root), check_kotlin_api(root),
            check_build_props(root), check_next_buildconfig(root),
            check_tool_selftests(root), check_shell(root),
            check_submodules(root), check_native_audit(root)]


def self_test() -> int:
    checks = run_all(project_root())
    bad = [c for c in checks if c["status"] != PASS]
    assert not bad, bad
    print(f"verify_repo self-test: OK ({len(checks)} 项)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="magisk-Next 仓库一致性校验")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", type=Path, default=project_root())
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    checks = run_all(args.root)
    rc = exit_code(checks, strict=True)
    if args.json:
        print(json.dumps({"checks": checks, "exit_code": rc},
                         ensure_ascii=False, indent=2))
    else:
        print("magisk-Next · 仓库一致性校验")
        print("=" * 72)
        print(render_checks(checks))
        print("=" * 72)
        print(f"{sum(1 for c in checks if c['status'] == PASS)}/{len(checks)} 通过 → exit {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
