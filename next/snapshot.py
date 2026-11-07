#!/usr/bin/env python3
"""模块快照与回滚（magisk-Next module snapshot）。

在模块变更前记录模块目录（设备上是 /data/adb/modules，主机上可为任意目录）
的完整状态；变更失败后可一键回滚。纯标准库，主机侧可独立运行与测试。

用法：
    python3 next/snapshot.py capture [--modules-dir D] [--name NAME] [--no-payload]
    python3 next/snapshot.py list
    python3 next/snapshot.py show <id>
    python3 next/snapshot.py diff <id> [--modules-dir D]
    python3 next/snapshot.py verify <id>
    python3 next/snapshot.py restore <id> [--modules-dir D] [--force] [--no-backup]
    python3 next/snapshot.py prune --keep N
    python3 next/snapshot.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    BRAND, FAIL, PASS, WARN, issue, project_root, sha256_file,
)

SNAP_DIR = "next-snapshots"
MANIFEST = "snapshot.json"
PAYLOAD = "files"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snap_root(root: Path | None = None) -> Path:
    return (root or project_root()) / SNAP_DIR


def _valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid)) and ".." not in sid


def _rel_is_safe(rel: str) -> bool:
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts and rel not in ("", ".")


def scan(base: Path) -> tuple[dict, list, list]:
    """扫描模块目录，返回 (文件表, 目录表, 问题表)。符号链接不跟随。"""
    files: dict[str, dict] = {}
    dirs: list[str] = []
    problems: list = []
    if not base.is_dir():
        return files, dirs, [issue(FAIL, "NOT_DIR", f"模块目录不存在: {base}")]
    for p in sorted(base.rglob("*")):
        rel = str(p.relative_to(base))
        if not _rel_is_safe(rel):
            problems.append(issue(FAIL, "UNSAFE_PATH", f"跳过不安全路径: {rel}"))
            continue
        if p.is_symlink():
            files[rel] = {"type": "link", "target": os.readlink(p)}
        elif p.is_dir():
            dirs.append(rel)
        elif p.is_file():
            st = p.stat()
            files[rel] = {
                "type": "file",
                "sha256": sha256_file(p),
                "size": st.st_size,
                "mode": oct(st.st_mode & 0o777)[2:],
            }
        else:
            problems.append(issue(WARN, "SPECIAL_FILE", f"跳过特殊文件: {rel}"))
    return files, sorted(dirs), problems


def _manifest_path(root: Path, sid: str) -> Path:
    return snap_root(root) / sid / MANIFEST


def load_manifest(root: Path, sid: str) -> dict:
    if not _valid_id(sid):
        raise ValueError(f"非法快照 id: {sid!r}")
    p = _manifest_path(root, sid)
    if not p.is_file():
        raise FileNotFoundError(f"快照不存在: {sid}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data.get("files"), dict):
        raise ValueError(f"快照清单损坏: {sid}")
    return data


def capture(root: Path, modules_dir: Path, name: str = "",
            with_payload: bool = True) -> dict:
    files, dirs, problems = scan(modules_dir)
    hard = [i for i in problems if i["level"] == FAIL]
    if hard:
        raise ValueError("; ".join(i["message"] for i in hard))
    sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    if name:
        clean = "".join(c if c.isalnum() or c in "._-" else "-" for c in name)
        sid += "-" + clean[:24]
    dest = snap_root(root) / sid
    (dest / PAYLOAD).mkdir(parents=True, exist_ok=False)
    for rel, info in files.items():
        if with_payload and info["type"] == "file":
            src = modules_dir / rel
            out = dest / PAYLOAD / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
    data = {
        "id": sid,
        "brand": BRAND,
        "created_at": _now(),
        "modules_dir": str(modules_dir),
        "has_payload": with_payload,
        "file_count": len(files),
        "dir_count": len(dirs),
        "files": files,
        "dirs": dirs,
        "warnings": problems,
    }
    (dest / MANIFEST).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def list_snapshots(root: Path) -> list[dict]:
    base = snap_root(root)
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not _valid_id(d.name):
            continue
        try:
            m = load_manifest(root, d.name)
        except (OSError, ValueError, json.JSONDecodeError):
            out.append({"id": d.name, "created_at": "?", "file_count": -1,
                        "has_payload": False, "broken": True})
            continue
        m["broken"] = False
        out.append(m)
    return out


def verify(root: Path, sid: str) -> list:
    problems: list = []
    try:
        m = load_manifest(root, sid)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
        return [issue(FAIL, "BAD_MANIFEST", str(e))]
    if m.get("brand") != BRAND:
        problems.append(issue(WARN, "FOREIGN", "快照并非 magisk-Next 生成"))
    payload = snap_root(root) / sid / PAYLOAD
    for rel, info in m["files"].items():
        if not _rel_is_safe(rel):
            problems.append(issue(FAIL, "UNSAFE_PATH", f"清单含不安全路径: {rel}"))
            continue
        if info["type"] != "file":
            continue
        if not m.get("has_payload"):
            continue
        f = payload / rel
        if not f.is_file():
            problems.append(issue(FAIL, "PAYLOAD_MISSING", f"快照缺少文件: {rel}"))
        elif sha256_file(f) != info["sha256"]:
            problems.append(issue(FAIL, "PAYLOAD_TAMPERED", f"快照文件校验失败: {rel}",
                                  "快照可能已损坏，请勿用于回滚"))
    return problems


def diff(root: Path, sid: str, modules_dir: Path) -> dict:
    m = load_manifest(root, sid)
    current, _, _ = scan(modules_dir)
    old = m["files"]
    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))
    changed = sorted(k for k in set(old) & set(current)
                     if old[k]["type"] != current[k]["type"]
                     or old[k].get("sha256") != current[k].get("sha256")
                     or old[k].get("target") != current[k].get("target"))
    return {"id": sid, "added": added, "removed": removed,
            "changed": changed, "unchanged": len(set(old) & set(current)) - len(changed)}


def restore(root: Path, sid: str, modules_dir: Path,
            force: bool = False, backup: bool = True) -> dict:
    m = load_manifest(root, sid)
    if not m.get("has_payload"):
        raise ValueError("该快照不含文件负载（--no-payload），无法回滚")
    v = verify(root, sid)
    if any(i["level"] == FAIL for i in v):
        raise ValueError("快照自身校验失败: " + "; ".join(i["message"] for i in v))
    src_payload = snap_root(root) / sid / PAYLOAD
    plan = {
        "id": sid,
        "modules_dir": str(modules_dir),
        "restore_files": len(m["files"]),
        "restore_dirs": len(m.get("dirs", [])),
        "backup": None,
        "applied": False,
    }
    if not force:
        return plan  # dry-run
    if backup:
        b = capture(root, modules_dir, name="before-restore")
        plan["backup"] = b["id"]
    # 清空目标目录内容（保留目录本身），随后按快照重建
    for child in list(modules_dir.iterdir()):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    for rel in m.get("dirs", []):
        if _rel_is_safe(rel):
            (modules_dir / rel).mkdir(parents=True, exist_ok=True)
    for rel, info in m["files"].items():
        if not _rel_is_safe(rel):
            continue
        out = modules_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if info["type"] == "link":
            out.symlink_to(info["target"])
        else:
            shutil.copy2(src_payload / rel, out)
            try:
                out.chmod(int(info.get("mode", "644"), 8))
            except (ValueError, OSError):
                pass
    plan["applied"] = True
    return plan


def prune(root: Path, keep: int) -> list[str]:
    snaps = [s for s in list_snapshots(root) if not s.get("broken")]
    victims = snaps[:-keep] if keep > 0 else snaps
    removed = []
    for s in victims:
        shutil.rmtree(snap_root(root) / s["id"], ignore_errors=True)
        removed.append(s["id"])
    return removed


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"
        mods = Path(td) / "modules"
        (mods / "demo_module" / "system" / "etc").mkdir(parents=True)
        (mods / "demo_module" / "module.prop").write_text("id=demo_module\n", encoding="utf-8")
        (mods / "demo_module" / "system" / "etc" / "hosts").write_text("127.0.0.1 localhost\n", encoding="utf-8")
        (mods / "another" / "empty").mkdir(parents=True)
        (mods / "link").symlink_to("demo_module/module.prop")

        m = capture(root, mods, name="selftest")
        assert m["file_count"] == 3, m
        assert not verify(root, m["id"]), verify(root, m["id"])
        assert len(list_snapshots(root)) == 1
        d = diff(root, m["id"], mods)
        assert not (d["added"] or d["removed"] or d["changed"]), d

        # 篡改后 diff 应检出，restore --force 应恢复
        (mods / "demo_module" / "system" / "etc" / "hosts").write_text("HACKED\n", encoding="utf-8")
        (mods / "extra.txt").write_text("new", encoding="utf-8")
        d = diff(root, m["id"], mods)
        assert "demo_module/system/etc/hosts" in d["changed"], d
        assert "extra.txt" in d["added"], d
        assert restore(root, m["id"], mods)["applied"] is False  # dry-run
        assert (mods / "extra.txt").exists()
        plan = restore(root, m["id"], mods, force=True)
        assert plan["applied"] and plan["backup"]
        assert (mods / "demo_module" / "system" / "etc" / "hosts").read_text(encoding="utf-8") == "127.0.0.1 localhost\n"
        assert not (mods / "extra.txt").exists()
        assert (mods / "link").is_symlink()
        assert (mods / "another" / "empty").is_dir()

        # 快照负载被篡改 -> verify 必须报错 -> restore 必须拒绝
        bad = capture(root, mods, name="tamper")
        (snap_root(root) / bad["id"] / PAYLOAD / "demo_module" / "module.prop").write_text("BAD", encoding="utf-8")
        assert "PAYLOAD_TAMPERED" in {i["code"] for i in verify(root, bad["id"])}
        try:
            restore(root, bad["id"], mods, force=True)
            raise AssertionError("损坏的快照不应允许回滚")
        except ValueError:
            pass

        # 路径穿越防护
        assert not _valid_id("../evil") and not _valid_id("a/b")
        assert not _rel_is_safe("../x") and not _rel_is_safe("/etc/passwd")

        # prune 保留最近 N 个
        for i in range(3):
            capture(root, mods, name=f"p{i}")
        removed = prune(root, keep=2)
        assert len(removed) >= 2, removed
        assert len(list_snapshots(root)) == 2
    print("snapshot self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 模块快照与回滚")
    ap.add_argument("action", nargs="?", choices=("capture", "list", "show", "diff",
                                                  "verify", "restore", "prune"))
    ap.add_argument("sid", nargs="?", help="快照 id")
    ap.add_argument("--root", type=Path, default=project_root(), help="仓库根目录")
    ap.add_argument("--modules-dir", type=Path, default=None,
                    help="模块目录（默认快照清单里记录的路径）")
    ap.add_argument("--name", default="", help="快照名后缀")
    ap.add_argument("--no-payload", action="store_true", help="只记录哈希，不保存文件内容")
    ap.add_argument("--force", action="store_true", help="真正执行回滚（默认仅预览）")
    ap.add_argument("--no-backup", action="store_true", help="回滚前不自动备份当前状态")
    ap.add_argument("--keep", type=int, default=0, help="prune 保留的快照数")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    # action 与 sid 是两个连续的 nargs="?" 位置参数。用 parse_intermixed_args
    # 才能让 "verify --root X <sid>" 这种选项夹在中间的写法正确解析
    # （普通 parse_args 会把 <sid> 报成 unrecognized arguments）。
    args = ap.parse_intermixed_args()
    if args.self_test:
        return self_test()
    if not args.action:
        ap.error("请指定动作，或使用 --self-test")

    root = args.root
    try:
        if args.action == "capture":
            mods = args.modules_dir or (root / "modules")
            data = capture(root, mods, args.name, not args.no_payload)
            print(f"[ OK ] 快照 {data['id']} · {data['file_count']} 个文件 · "
                  f"{data['dir_count']} 个目录 · payload={data['has_payload']}")
            if args.json:
                print(json.dumps({"id": data["id"], "file_count": data["file_count"]},
                                 ensure_ascii=False))
            return 0
        if args.action == "list":
            snaps = list_snapshots(root)
            if args.json:
                print(json.dumps([{k: s.get(k) for k in
                                   ("id", "created_at", "file_count", "has_payload", "broken")}
                                  for s in snaps], ensure_ascii=False, indent=2))
            else:
                if not snaps:
                    print("暂无快照")
                for s in snaps:
                    flag = " [损坏]" if s.get("broken") else ""
                    print(f"  {s['id']:38s} {str(s.get('created_at')):20s} "
                          f"{str(s.get('file_count')):>5s} 文件  "
                          f"payload={s.get('has_payload')}{flag}")
            return 0
        if not args.sid:
            ap.error(f"{args.action} 需要快照 id")
        if args.action == "show":
            print(json.dumps(load_manifest(root, args.sid), ensure_ascii=False, indent=2))
            return 0
        if args.action == "verify":
            problems = verify(root, args.sid)
            if not problems:
                print(f"[ OK ] 快照 {args.sid} 校验通过")
            for i in problems:
                print(f"[{i['level']:4s}] {i['code']}: {i['message']}")
            return 1 if any(i["level"] == FAIL for i in problems) else 0
        mods = args.modules_dir or Path(load_manifest(root, args.sid)["modules_dir"])
        if args.action == "diff":
            d = diff(root, args.sid, mods)
            if args.json:
                print(json.dumps(d, ensure_ascii=False, indent=2))
            else:
                print(f"快照 {d['id']} · 未变 {d['unchanged']} / "
                      f"新增 {len(d['added'])} / 删除 {len(d['removed'])} / 修改 {len(d['changed'])}")
                for label, key in (("+ 新增", "added"), ("- 删除", "removed"), ("~ 修改", "changed")):
                    for rel in d[key]:
                        print(f"  {label} {rel}")
            return 0
        if args.action == "restore":
            plan = restore(root, args.sid, mods, args.force, not args.no_backup)
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(f"{'已回滚' if plan['applied'] else '预览（加 --force 执行）'}: "
                      f"{plan['restore_files']} 文件 / {plan['restore_dirs']} 目录 "
                      f"→ {plan['modules_dir']}")
                if plan["backup"]:
                    print(f"  回滚前状态已另存为快照 {plan['backup']}")
            return 0
        if args.action == "prune":
            removed = prune(root, args.keep)
            print(f"已删除 {len(removed)} 个旧快照: {', '.join(removed) or '无'}")
            return 0
    except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
