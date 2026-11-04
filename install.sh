#!/usr/bin/env bash
# 薄委托（批191，v2.8.0）：实质逻辑已 Python 化到 install.py——
# Windows 10+ 原生跑 `python install.py`；本文件仅为 POSIX 习惯保留入口
# （install_dogfood 哨兵与既有文档引用 bash install.sh）。
# 批202：解释器探测——Windows 的 python3 可能是 Microsoft Store 假别名
# （在 PATH 里存在但只打印安装建议、退出非 0），-c 探针滤掉它。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _py in python3 python py; do
    if command -v "$_py" >/dev/null 2>&1 && "$_py" -c 'import sys' >/dev/null 2>&1; then
        exec "$_py" "${SCRIPT_DIR}/install.py" "$@"
    fi
done
echo "REGRESS-GUARD: 找不到可用的 Python 3（试过 python3/python/py——Windows 请从 python.org 安装并勾选 Add to PATH）" >&2
exit 1
