#!/usr/bin/env bash
# magisk-Next 仓库一键校验：静态检查 + 单元测试 + 工具自测 + 新能力 CLI 冒烟
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo ">>> 静态一致性校验（9 项）"
python3 next/verify_repo.py

echo
echo ">>> 单元测试"
python3 -m unittest discover -s tests -v

echo
echo ">>> 工具自测"
for tool in preflight module_lint integrity health_report snapshot channel api_audit verify_repo; do
    python3 "next/${tool}.py" --self-test
done

echo
echo ">>> 新能力 CLI 冒烟"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/modules/demo"
printf 'id=demo\nname=Demo\n' > "$TMP/modules/demo/module.prop"
printf 'payload\n' > "$TMP/modules/demo/data.txt"
python3 next/snapshot.py capture --root "$TMP/repo" --modules-dir "$TMP/modules" --name ci
SID="$(python3 next/snapshot.py list --root "$TMP/repo" --json | \
    python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')"
python3 next/snapshot.py verify --root "$TMP/repo" "$SID"
python3 next/snapshot.py diff --root "$TMP/repo" "$SID" --modules-dir "$TMP/modules"
python3 next/snapshot.py restore --root "$TMP/repo" "$SID" --modules-dir "$TMP/modules"
python3 next/channel.py template > "$TMP/next.json"
python3 next/channel.py verify --manifest "$TMP/next.json"

echo
echo ">>> 环境自检（信息项，不阻断 CI）"
python3 next/preflight.py || true

echo
echo "ALL CHECKS PASSED"
