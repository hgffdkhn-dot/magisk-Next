#!/usr/bin/env python3
"""native 核心增强静态守卫（magisk-Next）。

用途：把 native/src 里的 12 组修复固化成可回归的文本断言，防止后续
rebase / 合并上游 / 手工改动时把它们悄悄回滚。纯标准库，不依赖 Android
SDK、NDK 或 rustc，可直接进 CI。

覆盖的修复（对应 docs/NATIVE-AUDIT.md）：
  N01  线程池 FIFO 队列 + 线程数上限（避免高占用 / 请求串行阻塞）
  N02  pthread_create 返回值与 pthread_attr_t 生命周期
  N03  magiskd accept 错误分类（不再一律 exit(1) 掉 root）
  N04  connect_daemon 5 秒 deadline（避免 su 永久挂起）
  N05  su fork 失败显式回 Deny（避免"部分授权"挂起 / 误判）
  N06  waitpid 处理 EINTR（避免 root 子进程变僵尸）
  N07  zygiskd dlclose + poll 健壮性（避免 handle/fd 泄露、忙等）
  N08  connect_zygiskd 正确判定 poll 返回值（避免误杀 zygiskd）
  N09  Zygisk 模块缺 entry 时释放 handle 并标记失败
  N10  DenyList end() 解引用守卫（避免 magiskd 崩溃）
  N11  logcat 命名空间等待上限（避免忙等 + helper 进程残留）
  N12  revert_unmount 精确扩展隐藏清理目标

用法：
  python3 next/native_audit.py                 # 打印每项规则的通过情况
  python3 next/native_audit.py --json         # 机器可读
  python3 next/native_audit.py --root PATH    # 指定仓库根
  python3 next/native_audit.py --self-test    # 逐条扰动验证守卫有效
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    FAIL, PASS, exit_code, project_root, render_checks,
)

# 每条规则：
#   required     必须出现的字面片段
#   required_re  必须匹配的正则（re.S，可跨行，用于确认代码结构）
#   forbidden    必须不出现的字面片段（已修复的反模式）
RULES = (
    {
        "id": "N01", "file": "native/src/core/thread.rs",
        "title": "线程池 FIFO 队列与线程上限",
        "required": (
            "use std::collections::VecDeque;",
            "const MAX_POOL_SIZE: i32 = 16;",
            "task_ready: Condvar",
            "tasks: VecDeque<Box<dyn FnOnce() + Send>>",
            "info.tasks.push_back(Box::new(f))",
            "info.total_threads < MAX_POOL_SIZE",
            "self.task_ready.notify_one()",
        ),
        "forbidden": ("task_is_some", "task_is_none", "while info.task.is_some()"),
    },
    {
        "id": "N02", "file": "native/src/core/utils.cpp",
        "title": "pthread_create 返回值与 attr 生命周期",
        "required": (
            "int rc = pthread_create(&thread, &attr, entry, arg);",
            "pthread_attr_destroy(&attr);",
            "return rc;",
        ),
        "forbidden": ("errno = pthread_create",),
    },
    {
        "id": "N03", "file": "native/src/core/daemon.rs",
        "title": "magiskd accept 错误分类",
        "required": (
            "e.raw_os_error()",
            "Some(libc::EMFILE)",
            "Some(libc::ENFILE)",
            "Some(libc::EBADF)",
            "Some(libc::EINVAL)",
            "Some(libc::EINTR)",
            "Some(libc::ECONNABORTED)",
            "Some(libc::EAGAIN)",
            "accept fd pressure",
            "Duration::from_millis(50)",
        ),
    },
    {
        "id": "N04", "file": "native/src/core/daemon.rs",
        "title": "connect_daemon 启动超时上限",
        "required": (
            "use std::time::{Duration, Instant}",
            "let deadline = Instant::now() + Duration::from_secs(5);",
            "Instant::now() >= deadline",
            "Cannot connect to daemon: startup timed out",
        ),
    },
    {
        "id": "N05", "file": "native/src/core/su/daemon.rs",
        "title": "su fork 失败显式拒绝",
        "required": ("client.write_pod(&SuPolicy::Deny.repr).ok();",),
        "required_re": (
            r"if child < 0 \{[\s\S]{0,600}?SuPolicy::Deny\.repr",
        ),
    },
    {
        "id": "N06", "file": "native/src/core/su/daemon.rs",
        "title": "waitpid 处理 EINTR",
        "required": (
            "break libc::WEXITSTATUS(status)",
            "std::io::Error::last_os_error().raw_os_error() != Some(libc::EINTR)",
        ),
    },
    {
        "id": "N07", "file": "native/src/core/zygisk/entry.cpp",
        "title": "zygiskd dlclose 与 poll 健壮性",
        "required": (
            "#include <cerrno>",
            "dlclose(h);",
            "static_cast<size_t>(module_id)",
            "rc = poll(&pfd, 1, -1);",
            "errno == EINTR",
            "if (rc < 0) {",
            "POLLERR | POLLHUP | POLLNVAL",
            "if (!(pfd.revents & POLLIN)) {",
            "close(client);",
        ),
        "forbidden": ("if (pfd.revents && !(pfd.revents & POLLIN))",),
    },
    {
        "id": "N08", "file": "native/src/core/zygisk/daemon.rs",
        "title": "connect_zygiskd 正确判定 poll 返回值",
        "required": (
            "let rc = unsafe { libc::poll(&mut pfd, 1, 0) };",
            "if rc > 0 && pfd.revents != 0 {",
        ),
        "forbidden": (
            "if unsafe { libc::poll(&mut pfd, 1, 0) } != 0 || pfd.revents != 0 {",
        ),
    },
    {
        "id": "N09", "file": "native/src/core/zygisk/module.cpp",
        "title": "Zygisk 模块缺 entry 时释放 handle",
        "required": ("dlclose(h);", "fds[i] = -1;"),
        "required_re": (
            r'dlsym\(h, "zygisk_module_entry"\)[\s\S]{0,600}?dlclose\(h\)'
            r'[\s\S]{0,200}?fds\[i\] = -1',
        ),
    },
    {
        "id": "N10", "file": "native/src/core/deny/utils.cpp",
        "title": "DenyList end() 解引用守卫",
        "required": (
            "auto hit = pkg_to_procs.find(pkg);",
            "hit != pkg_to_procs.end() && hit->second.count(process)",
        ),
        "forbidden": ("pkg_to_procs.find(pkg)->second",),
    },
    {
        "id": "N11", "file": "native/src/core/deny/logcat.cpp",
        "title": "logcat 命名空间等待上限",
        "required": (
            "constexpr int MAX_NS_POLLS = 300;",
            "++ns_polls > MAX_NS_POLLS",
            "logcat: denylist namespace wait timeout",
        ),
    },
    {
        "id": "N12", "file": "native/src/core/mount.rs",
        "title": "revert_unmount 精确扩展隐藏清理",
        "required": (
            "INTERNAL_DIR",
            'let private_prefix = format!("{}/", private_dir);',
            "info.target == private_dir",
            "info.target.starts_with(private_prefix.as_str())",
            "info.source.starts_with(private_prefix.as_str())",
        ),
        "forbidden": ("info.source.contains(INTERNAL_DIR)",),
    },
)


def _assertion_count(rule: dict) -> int:
    return sum(len(rule.get(k, ())) for k in
               ("required", "required_re", "forbidden"))


def _issue(rule: dict, message: str) -> dict:
    return {
        "level": FAIL,
        "code": rule["id"],
        "rule": rule["title"],
        "file": rule["file"],
        "message": message,
    }


def audit(root: Path) -> list:
    """返回所有违规项；空列表表示全部守卫通过。"""
    issues = []
    for rule in RULES:
        path = root / rule["file"]
        if not path.is_file():
            issues.append(_issue(rule, f"文件缺失: {rule['file']}"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for snippet in rule.get("required", ()):
            if snippet not in text:
                issues.append(_issue(rule, f"缺少必需片段: {snippet[:64]}"))
        for pattern in rule.get("required_re", ()):
            if not re.search(pattern, text, re.S):
                issues.append(_issue(rule, f"缺少必需结构: {pattern[:64]}"))
        for snippet in rule.get("forbidden", ()):
            if snippet in text:
                issues.append(_issue(rule, f"出现已修复的反模式: {snippet[:64]}"))
    return issues


def checks(root: Path) -> list:
    """把规则渲染成 verify_repo 风格的检查表。"""
    issues = audit(root)
    grouped = {}
    for i in issues:
        grouped.setdefault(i["code"], []).append(i["message"])
    out = []
    for rule in RULES:
        bad = grouped.get(rule["id"], [])
        n = _assertion_count(rule)
        out.append({
            "name": f"{rule['id']} {rule['title']}",
            "status": FAIL if bad else PASS,
            "detail": "; ".join(bad) if bad else f"{n} 项断言通过",
            "hint": f"核对 {rule['file']}" if bad else "",
        })
    return out


def summary(root: Path) -> dict:
    issues = audit(root)
    files = sorted({r["file"] for r in RULES})
    return {
        "rules": len(RULES),
        "assertions": sum(_assertion_count(r) for r in RULES),
        "files": len(files),
        "failed_rules": len({i["code"] for i in issues}),
        "issues": len(issues),
    }


def self_test() -> int:
    """真仓库必须通过；再逐条扰动，验证每条规则确实能抓到回滚。"""
    root = project_root()
    assert not audit(root), f"真实仓库未通过守卫: {audit(root)}"

    files = sorted({r["file"] for r in RULES})
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for rel in files:
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((root / rel).read_text(encoding="utf-8"),
                           encoding="utf-8")
        assert not audit(tmp), "临时基线应等价于真实仓库"

        for rule in RULES:
            path = tmp / rule["file"]
            original = path.read_text(encoding="utf-8")
            probes = []
            if rule.get("required"):
                snippet = rule["required"][0]
                assert snippet in original, (rule["id"], snippet)
                # 替换全部出现：同一个片段可能在文件里多处存在（例如
                # SuPolicy::Deny.repr），只删一处不足以触发失败。
                probes.append(original.replace(snippet, "__REMOVED__"))
            if rule.get("forbidden"):
                probes.append(original + "\n" + rule["forbidden"][0] + "\n")
            if rule.get("required_re"):
                m = re.search(rule["required_re"][0], original, re.S)
                assert m, (rule["id"], "required_re 无法匹配真实源码")
                probes.append(original[:m.start()] + "__REMOVED__" + original[m.end():])
            assert probes, f"{rule['id']} 没有任何可扰动断言"
            for probe in probes:
                path.write_text(probe, encoding="utf-8")
                ids = {i["code"] for i in audit(tmp)}
                assert rule["id"] in ids, f"{rule['id']} 未被扰动检出: {sorted(ids)}"
            path.write_text(original, encoding="utf-8")

    s = summary(root)
    print(f"native_audit self-test: OK "
          f"({s['rules']} 条规则 / {s['assertions']} 项断言 / {s['files']} 个文件)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="magisk-Next native 静态守卫")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", type=Path, default=project_root())
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    cs = checks(args.root)
    rc = exit_code(cs, strict=True)
    if args.json:
        print(json.dumps({"checks": cs, "issues": audit(args.root),
                          "summary": summary(args.root), "exit_code": rc},
                         ensure_ascii=False, indent=2))
    else:
        print("magisk-Next · native 核心增强静态守卫")
        print("=" * 72)
        print(render_checks(cs))
        print("=" * 72)
        s = summary(args.root)
        print(f"{sum(1 for c in cs if c['status'] == PASS)}/{len(cs)} 条规则通过，"
              f"共 {s['assertions']} 项断言 → exit {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
