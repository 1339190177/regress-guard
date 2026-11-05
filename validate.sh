#!/usr/bin/env bash
# regress-guard 一键健康检查——改完代码跑这个，全绿再打包。
#
# 用法：bash validate.sh
#
# 检查项：
#   1. 单元测试（pytest）
#   2. 文档一致性（check_docs）
#   3. 静态检查（ruff+mypy，批163；本机未装则提示跳过——CI 是硬执法点）
#   4. hook 语法（所有 py/js 可解析）
#   5. guard 冒烟（非 commit 命令放行 + fail-safe 阻断）
#   6. 架构守卫（frontmatter 块解析只许住 lib/manifest_fields.py）

set -uo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
fail=0

echo "═══ regress-guard 健康检查 ═══"

echo "/─ 1/6 单元测试"
if python3 -m pytest tests/ -q --tb=short 2>&1 | tail -2; then :; fi
python3 -m pytest tests/ -q --tb=no >/dev/null 2>&1 || { echo -e "${RED}❌ 测试失败${NC}"; fail=1; }

echo "/─ 2/6 文档一致性"
python3 scripts/check_docs.py >/dev/null 2>&1 && echo "✅" || { echo -e "${RED}❌ 文档引用不一致${NC}"; fail=1; }

echo "/─ 3/6 静态检查（ruff+mypy）"
if command -v ruff >/dev/null 2>&1; then
  ruff check . || { echo -e "${RED}❌ ruff 未过${NC}"; fail=1; }
else
  echo "⏭ ruff 未装，跳过（CI 是硬执法点）"
fi
if command -v mypy >/dev/null 2>&1; then
  mypy hooks/scripts scripts || { echo -e "${RED}❌ mypy 未过${NC}"; fail=1; }
else
  echo "⏭ mypy 未装，跳过（CI 是硬执法点）"
fi

echo "/─ 4/6 hook 脚本语法"
for f in hooks/scripts/*.py hooks/scripts/lib/*.py; do
  python3 -m py_compile "$f" 2>/dev/null || { echo -e "${RED}❌ 语法错误: $f${NC}"; fail=1; }
done
node --check hooks/scripts/launcher.js 2>/dev/null || { echo -e "${RED}❌ launcher.js 语法错误${NC}"; fail=1; }
# 批205：dsh 原生适配层（index.js 命令面接线 + commands.js 零依赖模块）
for f in deploy/dsh-native/lib/*.js; do
  if node --check "$f" 2>/dev/null; then continue; fi
  # ESM 兜底：老 node 对 package.json type 感知不稳时按 .mjs 复检
  cp "$f" "${f%.js}.mjs"
  node --check "${f%.js}.mjs" 2>/dev/null; rc=$?
  rm -f "${f%.js}.mjs"
  [ $rc -eq 0 ] || { echo -e "${RED}❌ 语法错误: $f${NC}"; fail=1; }
done
echo "✅"

echo "/─ 5/6 guard 冒烟"
TMP=$(mktemp -d)
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | \
  env -u ZCODE_PROJECT_DIR -u ZCODE_SESSION_ID CLAUDE_PROJECT_DIR="$TMP" \
    python3 hooks/scripts/pre_commit_guard.py 2>/dev/null
[ $? -eq 0 ] || { echo -e "${RED}❌ 非 commit 命令未放行${NC}"; fail=1; }
mkdir -p "$TMP/.regress/manifests" && echo "broken" > "$TMP/.regress/config.json"
echo '{"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}' | \
  env -u ZCODE_PROJECT_DIR -u ZCODE_SESSION_ID CLAUDE_PROJECT_DIR="$TMP" \
    python3 hooks/scripts/pre_commit_guard.py 2>/dev/null
[ $? -eq 2 ] || { echo -e "${RED}❌ fail-safe 未阻断${NC}"; fail=1; }
rm -rf "$TMP"
echo "✅"

echo "─ 6/6 架构守卫（v1.20：块解析单一来源）"
BAD=$(grep -l -E '\^(approved|blocked|provisional):' hooks/scripts/*.py 2>/dev/null || true)
if [ -n "$BAD" ]; then
  echo -e "${RED}❌ 块解析正则出现在 lib 之外: $BAD${NC}"; fail=1
else
  echo "✅"
fi

echo "═══"
[ $fail -eq 0 ] && echo -e "${GREEN}全部通过${NC}" || { echo -e "${RED}存在失败项${NC}"; exit 1; }
