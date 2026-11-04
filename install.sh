#!/usr/bin/env bash
# 薄委托（批191，v2.8.0）：实质逻辑已 Python 化到 install.py——
# Windows 10+ 原生跑 `python install.py`；本文件仅为 POSIX 习惯保留入口
# （install_dogfood 哨兵与既有文档引用 bash install.sh）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/install.py" "$@"
