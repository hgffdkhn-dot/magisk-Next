#!/usr/bin/env python3
"""Kotlin 上游 API 引用守卫（magisk-Next api audit）。

背景：Next 的 Kotlin 代码是"叠加在上游源码上的薄层"，引用了官方的
Info / Config / BuildConfig / CoreR / Compose 组件。此前只校验了资源名，
没有校验符号是否真实存在 —— 一旦上游重命名就会编译失败，而 CI 里的
静态校验发现不了。本工具从**官方源码本身**动态提取定义名并逐一比对。

检查对象（Next 自研 Kotlin 文件）：
    app/core/src/main/java/com/topjohnwu/magisk/core/next/*.kt
    app/apk/src/main/java/com/topjohnwu/magisk/ui/settings/NextSection.kt

用法：
    python3 next/api_audit.py [--json] [--root DIR]
    python3 next/api_audit.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import FAIL, PASS, issue, project_root  # noqa: E402

DEF_RE = re.compile(r"\b(?:const\s+val|val|var|fun)\s+(\w+)")
BUILD_CONFIG_RE = re.compile(
    r'buildConfigField\(\s*"[^"]+"\s*,\s*"(\w+)"')
COMPOSE_RE = re.compile(r"\bfun\s+(\w+)\s*\(")

NEXT_KT = (
    "app/core/src/main/java/com/topjohnwu/magisk/core/next/NextFeatures.kt",
    "app/apk/src/main/java/com/topjohnwu/magisk/ui/settings/NextSection.kt",
)
# Next 代码里允许引用的 Compose 组件（来自 ui/component/）
COMPONENT_PREFIXES = ("Settings", "SmallTitle", "SettingsSwitch")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def definitions(root: Path) -> dict[str, set[str]]:
    """从官方源码动态提取各类符号的定义名集合。"""
    info = set(DEF_RE.findall(_read(
        root / "app/core/src/main/java/com/topjohnwu/magisk/core/Info.kt")))
    config = set(DEF_RE.findall(_read(
        root / "app/core/src/main/java/com/topjohnwu/magisk/core/Config.kt")))
    build_config = set(BUILD_CONFIG_RE.findall(_read(
        root / "app/core/build.gradle.kts")))
    strings: set[str] = set()
    sp = root / "app/core/src/main/res/values/strings.xml"
    if sp.is_file():
        try:
            strings = {e.get("name") for e in ET.parse(sp).getroot().findall("string")}
        except ET.ParseError:
            pass
    components: set[str] = set()
    comp_dir = root / "app/apk/src/main/java/com/topjohnwu/magisk/ui/component"
    for f in comp_dir.glob("*.kt"):
        components.update(COMPOSE_RE.findall(_read(f)))
    return {"Info": info, "Config": config, "BuildConfig": build_config,
            "CoreR.string": strings, "components": components}


def extract_refs(text: str) -> dict[str, set[str]]:
    """提取 Next Kotlin 代码里对上游符号的引用。"""
    refs: dict[str, set[str]] = {
        "Info": set(), "Config": set(), "BuildConfig": set(),
        "CoreR.string": set(), "components": set(),
    }
    refs["Info"].update(re.findall(r"\bInfo\.(\w+)", text))
    refs["Info"].update(re.findall(r"\bInfo\.env\.(\w+)", text))
    refs["Config"].update(re.findall(r"\bConfig\.(\w+)", text))
    refs["BuildConfig"].update(re.findall(r"\bBuildConfig\.(\w+)", text))
    refs["CoreR.string"].update(re.findall(r"\bCoreR\.string\.(\w+)", text))
    for m in re.findall(r"import\s+com\.topjohnwu\.magisk\.ui\.component\.(\w+)", text):
        refs["components"].add(m)
    # NextFeatures 自身常量（BRAND/VERSION 等）不参与上游符号检查
    return refs


def audit(root: Path) -> list:
    """返回问题列表；空列表表示所有引用都能在上游源码中找到定义。"""
    defs = definitions(root)
    problems: list = []
    files = [root / rel for rel in NEXT_KT]
    for f in files:
        if not f.is_file():
            problems.append(issue(FAIL, "MISSING_FILE", f"缺少 Next 源文件: {f}"))
            continue
        text = _read(f)
        refs = extract_refs(text)
        for kind in ("Info", "Config", "BuildConfig", "CoreR.string", "components"):
            missing = sorted(refs[kind] - defs[kind])
            for sym in missing:
                problems.append(issue(
                    FAIL, "UNDEFINED_SYMBOL",
                    f"{f.name}: {kind}.{sym} 在上游源码中未找到定义",
                    "上游可能已重命名该符号；请核对官方源码并更新 Next 代码"))
    return problems


def summary(root: Path) -> dict:
    defs = definitions(root)
    total = 0
    for f in NEXT_KT:
        text = _read(root / f)
        if text:
            total += sum(len(v) for v in extract_refs(text).values())
    return {"definitions": {k: len(v) for k, v in defs.items()},
            "referenced": total}


def self_test() -> int:
    root = project_root()
    problems = audit(root)
    assert not problems, problems
    s = summary(root)
    assert s["referenced"] > 0 and all(v > 0 for v in s["definitions"].values()), s
    # 伪造一个不存在的符号，必须被检出
    refs = extract_refs("val x = Config.thisDoesNotExist\n"
                        "val y = Info.env.alsoMissing\n"
                        "val z = BuildConfig.NO_SUCH_FIELD\n")
    assert "thisDoesNotExist" in refs["Config"]
    assert "alsoMissing" in refs["Info"]
    assert "NO_SUCH_FIELD" in refs["BuildConfig"]
    fake_defs = definitions(root)
    assert "thisDoesNotExist" not in fake_defs["Config"]
    print("api_audit self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="magisk-Next Kotlin 上游 API 引用守卫")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", type=Path, default=project_root())
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    problems = audit(args.root)
    s = summary(args.root)
    if args.json:
        print(json.dumps({"problems": problems, "ok": not problems,
                          "summary": s}, ensure_ascii=False, indent=2))
    else:
        if not problems:
            print(f"[ OK ] Kotlin 上游 API 引用校验通过 · "
                  f"{s['referenced']} 个引用 · 定义集 "
                  f"Info={s['definitions']['Info']} "
                  f"Config={s['definitions']['Config']} "
                  f"BuildConfig={s['definitions']['BuildConfig']} "
                  f"strings={s['definitions']['CoreR.string']} "
                  f"components={s['definitions']['components']}")
        for i in problems:
            print(f"[{i['level']:4s}] {i['code']}: {i['message']}")
            if i["hint"]:
                print(f"        -> {i['hint']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
