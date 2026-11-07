#!/usr/bin/env python3
"""magisk-Next 工具箱：共享常量与辅助函数。

不依赖任何第三方库，Python 3.8+ 可直接运行。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict

BRAND = "magisk-Next"
UPSTREAM_REPO = "topjohnwu/Magisk"
UPSTREAM_BASELINE = "33bfff7ce7"
NEXT_VERSION = "31.1-next.1"

SUBMODULES = (
    "native/src/external/selinux",
    "native/src/external/lz4",
    "native/src/external/libcxx",
    "native/src/external/cxx-rs",
    "native/src/external/lsplt",
    "native/src/external/system_properties",
    "native/src/external/crt0",
    "native/src/external/xz-embedded",
)

SIGNING_KEYS = ("keyStore", "keyStorePass", "keyAlias", "keyPass")
PROP_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
MODULE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{2,63}$")
MIN_MAGISK_RE = re.compile(r"^(?:v?\d{2,3}(?:\.\d+)?|\d{4,5})$")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
ICON = {PASS: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}


def project_root() -> Path:
    """返回仓库根目录（本文件位于 <root>/next/）。"""
    return Path(__file__).resolve().parent.parent


def parse_props(path: Path) -> Dict[str, str]:
    """解析 Java properties 风格文件，语义与上游 build.py 保持一致。"""
    result: Dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return result
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key and PROP_KEY_RE.match(key):
            result[key] = value
    return result


def next_config(root: Path | None = None) -> Dict[str, str]:
    """从 config.prop 读取 next.* 配置项（去掉前缀）。"""
    root = root or project_root()
    props = parse_props(root / "config.prop")
    return {k[5:]: v for k, v in props.items() if k.startswith("next.")}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def issue(level: str, code: str, message: str, hint: str = "") -> Dict[str, str]:
    return {"level": level, "code": code, "message": message, "hint": hint}


def render_checks(checks: Any) -> str:
    """把检查结果渲染成对齐的文本表。"""
    lines = []
    width = max((len(c["name"]) for c in checks), default=10)
    for c in checks:
        lines.append(
            f"{ICON[c['status']]:7s} {c['name']:<{width}}  {c['detail']}"
        )
        if c["status"] != PASS and c.get("hint"):
            lines.append(f"         {'':<{width}}  -> {c['hint']}")
    return "\n".join(lines)


def exit_code(checks: Any, strict: bool = False) -> int:
    levels = [c["status"] for c in checks]
    if FAIL in levels:
        return 1
    if strict and WARN in levels:
        return 2
    return 0
