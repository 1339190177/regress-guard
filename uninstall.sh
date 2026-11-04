#!/usr/bin/env bash
# 薄委托（批191，v2.8.0）：实质逻辑已 Python 化到 uninstall.py——
# Windows 10+ 原生跑 `python uninstall.py`；本文件仅为 POSIX 习惯保留入口。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/uninstall.py" "$@"
