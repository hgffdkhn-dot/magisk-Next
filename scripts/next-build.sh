#!/usr/bin/env bash
# magisk-Next 一键构建：环境自检 → 上游 build.py → 产物完整性清单
#
# 用法：
#   ./scripts/next-build.sh                      # 等价于 ./build.py all
#   ./scripts/next-build.sh --skip-preflight
#   ./scripts/next-build.sh --config config.prop --release
#   ./scripts/next-build.sh native              # 其余参数原样透传给 build.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_PREFLIGHT=0
CONFIG="config.prop"
BUILD_ARGS=()

usage() {
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

while (($#)); do
    case "$1" in
        --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
        --config) CONFIG="${2:?--config 需要参数}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) BUILD_ARGS+=("$1"); shift ;;
    esac
done

if (( SKIP_PREFLIGHT == 0 )); then
    echo ">>> 构建前环境自检"
    python3 next/preflight.py
fi

if (( ${#BUILD_ARGS[@]} == 0 )); then
    BUILD_ARGS=(all)
fi

echo
echo ">>> 调用上游构建：./build.py -c $CONFIG ${BUILD_ARGS[*]}"
./build.py -c "$CONFIG" "${BUILD_ARGS[@]}"

OUT="$(python3 - "$CONFIG" <<'PY'
import sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("nc", Path("next/next_common.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
p = Path(sys.argv[1])
cfg = m.parse_props(p) if p.is_file() else {}
print(cfg.get("outdir", "out"))
PY
)"

echo
echo ">>> 生成产物完整性清单（$OUT）"
python3 next/integrity.py generate --dir "$OUT"

echo
echo "构建完成。产物与 SHA256SUMS 位于 $OUT"
