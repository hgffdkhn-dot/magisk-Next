#!/usr/bin/env bash
# 引导 magisk-Next 的 8 个 native 子模块。
#
# 两种来源都支持：
#   - 标准 git clone（index 里有 gitlink）→ 用 git submodule update，能锁定官方 commit
#   - 从 release 归档快照创建的仓库（无 gitlink）→ 按 .gitmodules 直接克隆
#
# 可选环境变量：
#   MAGISK_NEXT_MIRROR  自定义 GitHub 前缀镜像，如 https://ghfast.top/https://github.com/
# 可选参数：
#   --shallow           子模块使用 --depth 1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEPTH=()
if [[ "${1:-}" == "--shallow" ]]; then
    DEPTH=(--depth 1)
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "错误：请在 magisk-Next 的 git 仓库中运行本脚本" >&2
    exit 1
fi

MIRROR="${MAGISK_NEXT_MIRROR:-https://ghfast.top/https://github.com/}"

echo ">>> 同步 .gitmodules"
git submodule sync --recursive >/dev/null 2>&1 || true

# index 中存在 160000 条目才说明这是带 submodule 历史的完整 clone
GITLINKS="$(git ls-files --stage | awk '$1 == "160000" { print $4 }')"

if [[ -n "$GITLINKS" ]]; then
    echo ">>> 检测到 gitlink，使用 git submodule update（可锁定官方 commit）"
    if ! git submodule update --init --recursive "${DEPTH[@]}"; then
        echo "直连失败，改用镜像 $MIRROR"
        git -c url."$MIRROR".insteadOf="https://github.com/" \
            submodule update --init --recursive "${DEPTH[@]}"
    fi
else
    echo ">>> 未检测到 gitlink（归档快照），按 .gitmodules 逐个克隆"
    echo "    注意：归档快照无法锁定上游 submodule commit，正式构建建议改用"
    echo "    git clone --recurse-submodules https://github.com/topjohnwu/Magisk.git"
    python3 - <<'PY' > /tmp/magisk-next-submodules.tsv
import configparser, pathlib
c = configparser.ConfigParser()
c.read(".gitmodules")
for s in c.sections():
    if "path" in c[s] and "url" in c[s]:
        print(c[s]["path"] + "\t" + c[s]["url"])
PY
    while IFS=$'\t' read -r path url; do
        [[ -z "$path" ]] && continue
        if [[ -d "$path" ]] && [[ -n "$(find "$path" -maxdepth 1 -type f -print -quit)" ]]; then
            echo "  [skip] $path 已有内容"
            continue
        fi
        echo "  [clone] $path <- $url"
        mkdir -p "$path"
        if ! git clone --quiet "${DEPTH[@]}" "$url" "$path" 2>/dev/null; then
            mirrored="${MIRROR}${url#https://github.com/}"
            echo "    直连失败，改用镜像 $mirrored"
            rm -rf "$path" && mkdir -p "$path"
            git clone --quiet "${DEPTH[@]}" "$mirrored" "$path"
        fi
    done < /tmp/magisk-next-submodules.tsv
    rm -f /tmp/magisk-next-submodules.tsv
fi

echo
echo ">>> 校验"
missing=0
while IFS=$'\t' read -r path url; do
    [[ -z "$path" ]] && continue
    if [[ -d "$path" ]] && [[ -n "$(find "$path" -maxdepth 1 -type f -print -quit)" ]]; then
        echo "  [ OK ] $path"
    else
        echo "  [FAIL] $path 为空"
        missing=$((missing + 1))
    fi
done < <(python3 - <<'PY'
import configparser
c = configparser.ConfigParser()
c.read(".gitmodules")
for s in c.sections():
    if "path" in c[s]:
        print(c[s]["path"] + "\t" + c[s].get("url", ""))
PY
)

if (( missing > 0 )); then
    echo "有 $missing 个子模块未就绪，请先检查网络或设置 MAGISK_NEXT_MIRROR" >&2
    exit 1
fi
echo "全部子模块就绪"
