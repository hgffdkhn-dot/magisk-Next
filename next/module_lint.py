#!/usr/bin/env python3
"""Magisk 模块静态校验器（magisk-Next module lint）。

在模块安装/发布前检查 module.prop 与目录结构，避免常见的坏模块。
除原有字段检查外，还覆盖：目录名/id 一致性、脚本可执行位（归档 zip 常丢失）、
符号链接逃逸、name 字段合法性。

用法：
    python3 next/module_lint.py <模块目录> [<模块目录2> ...]
    python3 next/module_lint.py --json <模块目录>
    python3 next/module_lint.py --strict <模块目录>   # WARN 也返回非零
    python3 next/module_lint.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    BRAND, FAIL, MIN_MAGISK_RE, MODULE_ID_RE, PASS, WARN,
    issue, parse_props, project_root,
)

REQUIRED_FIELDS = ("id", "name", "version", "versionCode", "author", "description")
OPTIONAL_SCRIPTS = ("customize.sh", "uninstall.sh", "post-fs-data.sh", "service.sh")
UPDATE_BINARY = Path("META-INF/com/google/android/update-binary")


def lint_module(path: Path) -> list:
    """返回该模块的问题列表；空列表表示通过。"""
    root = Path(path)
    problems = []
    if not root.is_dir():
        return [issue(FAIL, "NOT_DIR", f"不是目录: {root}")]

    prop = root / "module.prop"
    if not prop.is_file():
        return [issue(FAIL, "NO_MODULE_PROP", "缺少 module.prop",
                      "模块根目录必须包含 module.prop")]
    text = prop.read_text(encoding="utf-8", errors="replace")
    fields = parse_props(prop)

    for key in REQUIRED_FIELDS:
        if not fields.get(key):
            problems.append(issue(FAIL, "MISSING_FIELD", f"module.prop 缺少字段 {key}",
                                  f"添加 {key}=<值>"))

    mid = fields.get("id", "")
    bad_id = bool(mid and not MODULE_ID_RE.match(mid))
    if bad_id:
        problems.append(issue(FAIL, "BAD_ID", f"id 不合法: {mid!r}",
                              "以字母开头，仅含字母/数字/./_/-，长度 3-64"))
    # 仅在 id 本身合法时才单独报路径穿越，避免与 BAD_ID 重复刷屏
    if mid and not bad_id and ".." in mid:
        problems.append(issue(FAIL, "PATH_TRAVERSAL",
                              f"id 含路径穿越片段: {mid!r}",
                              "模块 id 不允许出现 .."))
    if mid and root.name != mid and not root.name.startswith("."):
        problems.append(issue(WARN, "ID_DIR_MISMATCH",
                              f"目录名 {root.name!r} 与 id {mid!r} 不一致",
                              "Magisk 以目录名定位模块，建议保持一致"))

    name = fields.get("name", "")
    if name and (any(ord(ch) < 32 for ch in name) or len(name) > 80):
        problems.append(issue(WARN, "BAD_NAME",
                              "name 含控制字符或超过 80 字符"))

    vc = fields.get("versionCode", "")
    if vc:
        try:
            if int(vc) < 0:
                raise ValueError
        except ValueError:
            problems.append(issue(FAIL, "BAD_VERSION_CODE",
                                  f"versionCode 必须是非负整数: {vc!r}"))

    mm = fields.get("minMagisk", "")
    if mm and not MIN_MAGISK_RE.match(mm):
        problems.append(issue(FAIL, "BAD_MIN_MAGISK",
                              f"minMagisk 格式不合法: {mm!r}",
                              "形如 31100 或 v31.1"))

    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        problems.append(issue(WARN, "CONTROL_CHAR", "module.prop 含控制字符"))
    if len(fields.get("description", "")) > 200:
        problems.append(issue(WARN, "LONG_DESC", "description 超过 200 字符，建议精简"))

    if not (root / UPDATE_BINARY).is_file():
        problems.append(issue(WARN, "NO_UPDATE_BINARY",
                              "缺少 META-INF/com/google/android/update-binary",
                              "标准模块模板应提供 update-binary；纯 sku 模块可忽略"))

    system = root / "system"
    has_payload = system.is_dir() and any(system.rglob("*"))
    has_script = any((root / s).is_file() for s in OPTIONAL_SCRIPTS)
    if not has_payload and not has_script:
        problems.append(issue(WARN, "EMPTY_MODULE",
                              "既无 system/ 内容也无任何脚本，模块不会有任何效果"))

    for script in OPTIONAL_SCRIPTS:
        s = root / script
        if s.is_file():
            head = s.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
            if head and not head[0].lstrip().startswith("#!"):
                problems.append(issue(WARN, "NO_SHEBANG",
                                      f"{script} 缺少 shebang",
                                      "首行建议 #!/system/bin/sh"))

    # 可执行位：release 归档 zip 不保留 Unix 权限，是最常见的隐蔽故障
    for s in [root / UPDATE_BINARY, *(root / n for n in OPTIONAL_SCRIPTS)]:
        if s.is_file() and not (s.stat().st_mode & 0o111):
            problems.append(issue(WARN, "NOT_EXECUTABLE",
                                  f"{s.name} 缺少可执行位",
                                  "chmod +x；从 zip 解包的模块常丢失执行位"))

    # 符号链接逃逸：不能指向模块目录之外（防读取/覆盖宿主文件）
    base = str(root.resolve())
    for p in root.rglob("*"):
        if not p.is_symlink():
            continue
        try:
            target = str((p.parent / os.readlink(p)).resolve())
            if os.path.commonpath([base, target]) != base:
                problems.append(issue(FAIL, "SYMLINK_ESCAPE",
                                      f"符号链接指向模块目录之外: {p.relative_to(root)}",
                                      "模块内符号链接只能指向模块自身文件"))
        except (OSError, ValueError):
            problems.append(issue(WARN, "SYMLINK_BROKEN",
                                  f"无法解析符号链接: {p.relative_to(root)}"))
    return problems


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "good"
        (good / "META-INF/com/google/android").mkdir(parents=True)
        (good / "module.prop").write_text(
            "id=com.example.demo\nname=Demo\nversion=v1.0\nversionCode=1\n"
            "author=next\ndescription=A demo module\nminMagisk=31100\n",
            encoding="utf-8")
        (good / UPDATE_BINARY).write_text("#!/system/bin/sh\n", encoding="utf-8")
        (good / UPDATE_BINARY).chmod(0o755)
        (good / "system" / "etc").mkdir(parents=True)
        (good / "system" / "etc" / "demo").write_text("x", encoding="utf-8")
        p = lint_module(good)
        assert not [i for i in p if i["level"] == FAIL], p

        bad = Path(td) / "bad"
        bad.mkdir()
        (bad / "module.prop").write_text(
            "id=../evil\nname=Bad\nversion=v1\nversionCode=abc\n", encoding="utf-8")
        p = lint_module(bad)
        codes = {i["code"] for i in p}
        assert {"MISSING_FIELD", "BAD_ID", "BAD_VERSION_CODE"} <= codes, codes
        assert lint_module(Path(td) / "missing")[0]["code"] == "NOT_DIR"
        empty = Path(td) / "empty"
        empty.mkdir()
        assert lint_module(empty)[0]["code"] == "NO_MODULE_PROP"

        # 新增检查：不可执行的 update-binary 与逃逸符号链接
        noexec = Path(td) / "noexec"
        (noexec / "META-INF/com/google/android").mkdir(parents=True)
        (noexec / "module.prop").write_text(
            "id=noexec\nname=N\nversion=v1\nversionCode=1\nauthor=a\ndescription=d\n",
            encoding="utf-8")
        (noexec / UPDATE_BINARY).write_text("#!/system/bin/sh\n", encoding="utf-8")
        (noexec / UPDATE_BINARY).chmod(0o644)
        assert "NOT_EXECUTABLE" in {i["code"] for i in lint_module(noexec)}

        esc = Path(td) / "escape"
        esc.mkdir()
        (esc / "module.prop").write_text(
            "id=escape\nname=E\nversion=v1\nversionCode=1\nauthor=a\ndescription=d\n",
            encoding="utf-8")
        (esc / "leak").symlink_to(Path(td) / "outside.txt")
        assert "SYMLINK_ESCAPE" in {i["code"] for i in lint_module(esc)}
    print("module_lint self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 模块静态校验器")
    ap.add_argument("paths", nargs="*", type=Path, help="模块目录（可多个）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="存在 WARN 也返回非零")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.paths:
        ap.error("请指定至少一个模块目录，或使用 --self-test")

    report = []
    for p in args.paths:
        problems = lint_module(p)
        report.append({"path": str(p), "ok": not any(
            i["level"] == FAIL for i in problems), "problems": problems})

    if args.json:
        print(json.dumps({"brand": BRAND, "modules": report},
                         ensure_ascii=False, indent=2))
    else:
        for m in report:
            print(f"\n=== {m['path']} ===")
            if not m["problems"]:
                print("  [ OK ] 未发现问题")
            for i in m["problems"]:
                print(f"  [{i['level']:4s}] {i['code']}: {i['message']}")
                if i["hint"]:
                    print(f"          -> {i['hint']}")

    fail = any(i["level"] == FAIL for m in report for i in m["problems"])
    warn = any(i["level"] == WARN for m in report for i in m["problems"])
    return 1 if fail else (2 if (warn and args.strict) else 0)


if __name__ == "__main__":
    sys.exit(main())
