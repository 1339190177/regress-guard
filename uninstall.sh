#!/usr/bin/env bash
# 薄委托（批191，v2.8.0）：实质逻辑已 Python 化到 uninstall.py——
# Windows 10+ 原生跑 `python uninstall.py`；本文件仅为 POSIX 习惯保留入口。
# 批202：解释器探测——滤掉 Microsoft Store 的 python3 假别名。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _py in python3 python py; do
    _bin="$(command -v "$_py" 2>/dev/null || true)"
    # 批202：Microsoft Store 假别名唯一藏身处是 WindowsApps 目录——在 PATH
    # 里存在但带参运行只打安装建议（rc 还可能是 0，-c 探针滤不掉），点名排除
    [ -z "$_bin" ] && continue
    case "$_bin" in
        *WindowsApps*) continue ;;
    esac
    exec "$_py" "${SCRIPT_DIR}/uninstall.py" "$@"
done
echo "REGRESS-GUARD: 找不到可用的 Python 3（试过 python3/python/py——Windows 请从 python.org 安装并勾选 Add to PATH）" >&2
exit 1
