#!/usr/bin/env python3
"""构建前环境自检（magisk-Next preflight）。

用法：
    python3 next/preflight.py                 # 人读报告
    python3 next/preflight.py --json         # 机器可读
    python3 next/preflight.py --strict       # 有 WARN 也返回非零
    python3 next/preflight.py --self-test    # 内部逻辑自测
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    BRAND, FAIL, NEXT_VERSION, PASS, SIGNING_KEYS, SUBMODULES, WARN,
    exit_code, parse_props, project_root, render_checks,
)

GIB = 1 << 30
MIN_FREE_BYTES = 10 * GIB


def _check(name: str, ok: bool, detail_ok: str, detail_bad: str,
           hint: str = "", level_on_fail: str = FAIL) -> dict:
    return {
        "name": name,
        "status": PASS if ok else level_on_fail,
        "detail": detail_ok if ok else detail_bad,
        "hint": hint,
    }


def run_checks(root: Path) -> list:
    checks = []

    py = sys.version_info
    checks.append(_check(
        "python>=3.8", py >= (3, 8),
        f"{py.major}.{py.minor}.{py.micro}", "Python 版本过低，需要 3.8+",
        "安装 Python 3.8 或更高版本"))

    git = shutil.which("git")
    checks.append(_check(
        "git", git is not None, git or "", "未找到 git",
        "安装 git 并确保在 PATH 中；构建脚本用 git rev-parse 生成版本号"))

    java = shutil.which("java")
    studio = os.environ.get("ANDROID_STUDIO")
    java_ok = bool(java or studio)
    checks.append(_check(
        "jdk / android studio", java_ok,
        java or f"ANDROID_STUDIO={studio}", "未找到 java，也未设置 ANDROID_STUDIO",
        "上游要求 JDK 25；可设置 ANDROID_STUDIO 让 build.py 自动定位自带 JDK",
        level_on_fail=WARN))

    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    sdk_path = Path(sdk) if sdk else None
    sdk_ok = bool(sdk_path and sdk_path.is_dir())
    checks.append(_check(
        "ANDROID_HOME", sdk_ok, str(sdk_path) if sdk_path else "",
        "未设置 ANDROID_HOME / ANDROID_SDK_ROOT，或路径不存在",
        "export ANDROID_HOME=/path/to/Android/sdk"))

    ondk_ok = bool(sdk_path and (sdk_path / "ndk" / "magisk").is_dir())
    checks.append(_check(
        "ONDK (ndk/magisk)", ondk_ok,
        str(sdk_path / "ndk" / "magisk") if sdk_path else "",
        "未安装 Magisk ONDK 工具链",
        "运行 ./build.py ndk 自动下载安装（scripts/env.py 中 ondk_version 指定版本）"))

    missing = [s for s in SUBMODULES
               if not (root / s).is_dir() or not any((root / s).iterdir())]
    checks.append(_check(
        "git submodules", not missing,
        f"{len(SUBMODULES)}/{len(SUBMODULES)} 已初始化",
        f"缺少 {len(missing)} 个: {', '.join(missing[:3])}"
        + (" ..." if len(missing) > 3 else ""),
        "运行 ./scripts/bootstrap-submodules.sh（离线归档快照不含 submodule 内容）"))

    free = shutil.disk_usage(root).free
    checks.append(_check(
        "disk>=10GiB", free >= MIN_FREE_BYTES,
        f"可用 {free / GIB:.1f} GiB", f"可用仅 {free / GIB:.1f} GiB",
        "ONDK + NDK + Rust 全量构建需要约 10 GiB 空间",
        level_on_fail=WARN))

    props = parse_props(root / "config.prop")
    present = [k for k in SIGNING_KEYS if props.get(k)]
    sign_ok = len(present) == 0 or len(present) == len(SIGNING_KEYS)
    checks.append(_check(
        "signing config", sign_ok,
        "未配置签名（使用 debug 签名）" if not present else "4 项签名配置齐全",
        f"签名配置不完整（{len(present)}/4: {', '.join(present)}）",
        "keyStore / keyStorePass / keyAlias / keyPass 必须同时设置或同时留空"))

    cfg_ok = (root / "build.py").is_file() and (root / "app" / "settings.gradle.kts").is_file()
    checks.append(_check(
        "repo layout", cfg_ok, "build.py 与 app/settings.gradle.kts 就位",
        "仓库结构不完整，可能不在仓库根目录运行",
        "在 magisk-Next 仓库根目录执行本脚本"))

    return checks


def self_test() -> int:
    """不依赖真实环境的逻辑自测。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.prop"
        p.write_text("# comment\nversion=31.1-next.3\nkeyStore=a\nbad key=x\n",
                     encoding="utf-8")
        props = parse_props(p)
        assert props["version"] == "31.1-next.3", props
        assert "bad key" not in props, props
        assert parse_props(Path(td) / "nope") == {}

        c = _check("x", True, "ok", "bad")
        assert c["status"] == PASS
        assert _check("y", False, "ok", "bad", level_on_fail=WARN)["status"] == WARN
        assert exit_code([c]) == 0
        assert exit_code([{"status": FAIL}]) == 1
        assert exit_code([{"status": WARN}], strict=True) == 2
        assert SUBMODULES and len(SUBMODULES) == 8
    print("preflight self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 构建前环境自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="存在 WARN 也返回非零")
    ap.add_argument("--root", type=Path, default=project_root(), help="仓库根目录")
    ap.add_argument("--self-test", action="store_true", help="运行内部自测")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    checks = run_checks(args.root)
    rc = exit_code(checks, args.strict)
    if args.json:
        print(json.dumps({"brand": BRAND, "version": NEXT_VERSION,
                          "checks": checks, "exit_code": rc},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{BRAND} {NEXT_VERSION} · 构建前环境自检")
        print("=" * 72)
        print(render_checks(checks))
        print("=" * 72)
        n = {s: sum(1 for c in checks if c["status"] == s)
             for s in (PASS, WARN, FAIL)}
        print(f"合计 {len(checks)} 项：{n[PASS]} 通过 / {n[WARN]} 警告 / {n[FAIL]} 失败"
              f"  → exit {rc}")
        if rc:
            print("请先处理上述 FAIL 项，再运行 ./scripts/next-build.sh")
    return rc


if __name__ == "__main__":
    sys.exit(main())
