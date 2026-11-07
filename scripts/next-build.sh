#!/usr/bin/env bash
# magisk-Next 一键构建：环境自检 → 上游 build.py → 产物完整性清单
#
# 用法：
#   ./scripts/next-build.sh                      # 等价于 ./build.py all
#   ./scripts/next-build.sh --skip-preflight
#   ./scripts/next-build.sh --config config.prop --release
#   ./scripts/next-build.sh native              # action 及其它参数透传给 build.py
#
# 注意：build.py 的 -r/-v/-c 是全局参数，必须位于 action 之前。
# 本脚本会把 --release/--verbose 自动归到全局参数，并补上默认 action "all"，
# 避免 "./build.py --release" 这种只打印帮助就退出 1 的调用。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_PREFLIGHT=0
CONFIG="config.prop"
GLOBAL_ARGS=()
ACTION_ARGS=()

usage() {
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

while (($#)); do
    case "$1" in
        --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
        --config) CONFIG="${2:?--config 需要参数}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        # build.py 的全局 flag 必须排在 action 前面
        -r|--release|-v|--verbose|-vv) GLOBAL_ARGS+=("$1"); shift ;;
        *) ACTION_ARGS+=("$1"); shift ;;
    esac
done

if (( SKIP_PREFLIGHT == 0 )); then
    echo ">>> 构建前环境自检"
    python3 next/preflight.py
fi

if (( ${#ACTION_ARGS[@]} == 0 )); then
    ACTION_ARGS=(all)
fi

echo
echo ">>> 调用上游构建：./build.py ${GLOBAL_ARGS[*]:-} -c $CONFIG ${ACTION_ARGS[*]}"
./build.py "${GLOBAL_ARGS[@]}" -c "$CONFIG" "${ACTION_ARGS[@]}"

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
