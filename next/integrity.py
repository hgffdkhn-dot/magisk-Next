#!/usr/bin/env python3
"""构建产物完整性清单（magisk-Next integrity）。

生成与上游产物同目录的 SHA256SUMS（GNU coreutils 兼容）与 SHA256SUMS.json，
用于分发前生成、下载后校验。符号链接不会被跟随或写入清单，校验时以 WARN 提示。

用法：
    python3 next/integrity.py generate [--dir out]
    python3 next/integrity.py verify   [--dir out]
    python3 next/integrity.py --self-test
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    BRAND, FAIL, NEXT_VERSION, PASS, WARN, issue, project_root, sha256_file,
)

MANIFEST = "SHA256SUMS"
META = "SHA256SUMS.json"
SKIP_NAMES = {MANIFEST, META}


def _git_head(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short=8", "HEAD"],
                              cwd=root, capture_output=True, text=True,
                              timeout=5, check=True).stdout.strip()
    except Exception:
        return "unknown"


def symlinks(directory: Path) -> list[str]:
    """列出目录内的符号链接（不跟随），校验时提示未被清单覆盖。"""
    out = []
    for p in sorted(directory.rglob("*")):
        if p.is_symlink() and ".git" not in p.parts:
            out.append(str(p.relative_to(directory)))
    return out


def collect(directory: Path) -> dict:
    """收集目录下所有普通文件的相对路径 -> sha256。符号链接跳过。"""
    files = {}
    for p in sorted(directory.rglob("*")):
        if p.is_symlink() or not p.is_file() or p.name in SKIP_NAMES or ".git" in p.parts:
            continue
        files[str(p.relative_to(directory))] = sha256_file(p)
    return files


def generate(directory: Path) -> dict:
    files = collect(directory)
    lines = [f"{h}  {name}" for name, h in sorted(files.items())]
    (directory / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = {
        "brand": BRAND,
        "version": NEXT_VERSION,
        "git_head": _git_head(project_root()),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "manifest": MANIFEST,
        "algorithm": "sha256",
        "skipped_symlinks": symlinks(directory),
    }
    (directory / META).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def verify(directory: Path) -> list:
    manifest = directory / MANIFEST
    if not manifest.is_file():
        return [issue(FAIL, "NO_MANIFEST", f"缺少 {MANIFEST}",
                      "先运行 integrity.py generate")]
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, name = line.split(None, 1)
        except ValueError:
            return [issue(FAIL, "BAD_MANIFEST", f"清单格式错误: {line!r}")]
        expected[name.strip()] = digest.strip()

    actual = collect(directory)
    problems = []
    for name, digest in sorted(expected.items()):
        if name not in actual:
            problems.append(issue(FAIL, "MISSING", f"清单中的文件不存在: {name}"))
        elif actual[name] != digest:
            problems.append(issue(FAIL, "HASH_MISMATCH", f"校验和不匹配: {name}",
                                  "文件可能被篡改或传输损坏，请勿刷入"))
    for name in sorted(set(actual) - set(expected)):
        problems.append(issue(WARN, "EXTRA", f"清单外的文件: {name}"))
    for name in symlinks(directory):
        problems.append(issue(WARN, "SYMLINK_SKIPPED",
                              f"符号链接未纳入清单: {name}",
                              "产物目录应只包含普通文件"))
    return problems


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "app-debug.apk").write_bytes(b"apk-bytes")
        (d / "magisk-init.zip").write_bytes(b"zip-bytes")
        (d / "sub").mkdir()
        (d / "sub" / "boot.img").write_bytes(b"boot")
        meta = generate(d)
        assert meta["file_count"] == 3, meta
        assert not verify(d), verify(d)
        manifest = (d / MANIFEST).read_text(encoding="utf-8")
        assert "app-debug.apk" in manifest and "sub/boot.img" in manifest

        (d / "app-debug.apk").write_bytes(b"TAMPERED")
        codes = {i["code"] for i in verify(d)}
        assert "HASH_MISMATCH" in codes, codes
        (d / "app-debug.apk").unlink()
        codes = {i["code"] for i in verify(d)}
        assert "MISSING" in codes, codes
        (d / "extra.txt").write_text("x", encoding="utf-8")
        assert "EXTRA" in {i["code"] for i in verify(d)}

        # 符号链接不应被跟随，且应给出提示
        (d / "link.apk").symlink_to("extra.txt")
        assert "link.apk" not in collect(d), "符号链接不得写入清单"
        assert "SYMLINK_SKIPPED" in {i["code"] for i in verify(d)}
    print("integrity self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 产物完整性清单")
    ap.add_argument("action", nargs="?", choices=("generate", "verify"))
    ap.add_argument("--dir", type=Path, default=None, help="产物目录（默认 <root>/out）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.action:
        ap.error("请指定 generate / verify，或使用 --self-test")

    directory = args.dir or (project_root() / "out")
    directory.mkdir(parents=True, exist_ok=True)
    if args.action == "generate":
        meta = generate(directory)
        if args.json:
            print(json.dumps(meta, ensure_ascii=False, indent=2))
        else:
            print(f"{BRAND} · 已生成 {directory / MANIFEST}")
            print(f"  {meta['file_count']} 个文件 · git {meta['git_head']} · {meta['generated_at']}")
        return 0

    problems = verify(directory)
    if args.json:
        print(json.dumps({"problems": problems,
                          "ok": not any(p["level"] == FAIL for p in problems)},
                         ensure_ascii=False, indent=2))
    else:
        if not problems:
            print(f"[ OK ] {directory} 全部文件校验通过（{MANIFEST}）")
        for p in problems:
            print(f"[{p['level']:4s}] {p['code']}: {p['message']}")
            if p["hint"]:
                print(f"        -> {p['hint']}")
    return 1 if any(p["level"] == FAIL for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
