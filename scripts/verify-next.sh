#!/usr/bin/env bash
# magisk-Next 仓库一键校验：静态检查 + 单元测试 + 工具自测
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo ">>> 静态一致性校验"
python3 next/verify_repo.py

echo
echo ">>> 单元测试"
python3 -m unittest discover -s tests -v

echo
echo ">>> 工具自测"
for tool in preflight module_lint integrity health_report; do
    python3 "next/${tool}.py" --self-test
done

echo
echo ">>> 环境自检（信息项，不阻断 CI）"
python3 next/preflight.py || true

echo
echo "ALL CHECKS PASSED"
