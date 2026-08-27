#!/usr/bin/env bash
# regress-guard 卸载器
#
# 用法：bash uninstall.sh
#
# 清理：
#   1. 删除 ~/.zcode/skills/ 下的 3 个 skill
#   2. 删除 ~/.zcode/commands/ 下的 7 个命令
#   3. 删除 ~/.zcode/regress-guard-hooks/
#   4. 从 config.json 移除 hook 注册
#   5. 从 AGENTS.md 移除回归契约块
#
# 安全：不会删除用户的其他 skill/命令/config 字段。

set -euo pipefail

ZCODE_HOME="${HOME}/.zcode"
HOOK_HOME="${ZCODE_HOME}/regress-guard-hooks"
CONFIG_FILE="${ZCODE_HOME}/cli/config.json"
AGENTS_FILE="${ZCODE_HOME}/AGENTS.md"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠️${NC} $1"; }

echo "════════════════════════════════════════════"
echo "  regress-guard 卸载"
echo "════════════════════════════════════════════"
echo ""

# ─── 1. 删除旧版 skills（兼容清理）──────────────────
for skill in regression-planning characterization-testing change-impact-analysis requirement-parsing adaptive-thinking adaptive-learning; do
    if [ -d "${ZCODE_HOME}/skills/${skill}" ]; then
        rm -rf "${ZCODE_HOME}/skills/${skill}"
        info "清理旧 skill: ${skill}"
    fi
done

# ─── 2. 删除 commands ─────────────────────────────────
for cmd in regress:init regress:plan regress:track regress:verify regress:quick regress:bypass regress:learn regress:evolve regress:trace regress:install regress:uninstall regress:update; do
    f="${ZCODE_HOME}/commands/${cmd}.md"
    if [ -f "$f" ]; then
        rm "$f"
        info "删除命令: ${cmd}"
    fi
done

# ─── 3. 删除 hook 脚本 ────────────────────────────────
if [ -d "${HOOK_HOME}" ]; then
    rm -rf "${HOOK_HOME}"
    info "删除 hook 脚本: ${HOOK_HOME}"
fi

# ─── 4. 从 config.json 移除 hook ──────────────────────
if [ -f "${CONFIG_FILE}" ]; then
    python3 << 'PYEOF'
import json, os, re

config_path = os.path.expanduser("~/.zcode/cli/config.json")
try:
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
except Exception:
    exit(0)

hooks = config.get("hooks", {})
events = hooks.get("events", {})

# 从 PreToolUse 移除 regress-guard 的 hook（commit guard + 先读后改）
pretool = events.get("PreToolUse", [])
cleaned = []
for entry in pretool:
    hooks_list = entry.get("hooks", [])
    filtered = [h for h in hooks_list
                 if not any("regress-guard" in str(a) or "launcher.js" in str(a)
                            for a in h.get("args", []))
                 and "read_before_edit" not in str(h.get("command", ""))]
    if filtered:
        cleaned.append({**entry, "hooks": filtered})
if cleaned:
    events["PreToolUse"] = cleaned
else:
    events.pop("PreToolUse", None)

# 从 PostToolUse 移除 先读后改
posttool = events.get("PostToolUse", [])
post_cleaned = []
for entry in posttool:
    hooks_list = entry.get("hooks", [])
    filtered = [h for h in hooks_list
                 if "read_before_edit" not in str(h.get("command", ""))]
    if filtered:
        post_cleaned.append({**entry, "hooks": filtered})
if post_cleaned:
    events["PostToolUse"] = post_cleaned
else:
    events.pop("PostToolUse", None)

# 从 UserPromptSubmit 移除 需求入口检查
submit = events.get("UserPromptSubmit", [])
submit_cleaned = []
for entry in submit:
    hooks_list = entry.get("hooks", [])
    filtered = [h for h in hooks_list
                 if "prompt_intercept" not in str(h.get("command", ""))]
    if filtered:
        submit_cleaned.append({**entry, "hooks": filtered})
if submit_cleaned:
    events["UserPromptSubmit"] = submit_cleaned
else:
    events.pop("UserPromptSubmit", None)

# 从 Stop 移除 反思检查
stop = events.get("Stop", [])
stop_cleaned = []
for entry in stop:
    hooks_list = entry.get("hooks", [])
    filtered = [h for h in hooks_list
                 if "reflection_check" not in str(h.get("command", ""))]
    if filtered:
        stop_cleaned.append({**entry, "hooks": filtered})
if stop_cleaned:
    events["Stop"] = stop_cleaned
else:
    events.pop("Stop", None)

# 从 SessionStart 移除 regress-guard 的自愈 hook
session = events.get("SessionStart", [])
session_cleaned = []
for entry in session:
    hooks_list = entry.get("hooks", [])
    filtered = [h for h in hooks_list
                 if "self_heal" not in str(h.get("command", ""))]
    if filtered:
        session_cleaned.append({**entry, "hooks": filtered})
if session_cleaned:
    events["SessionStart"] = session_cleaned
else:
    events.pop("SessionStart", None)

if not events:
    hooks.pop("events", None)
    # 如果 hooks 空了，保留 enabled（不影响其他东西）
config["hooks"] = hooks

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("已从 config.json 移除 hook 注册")
PYEOF
    info "hook 注册已移除"
fi

# ─── 5. 从 AGENTS.md 移除回归契约 ────────────────────
if [ -f "${AGENTS_FILE}" ]; then
    python3 << 'PYEOF'
import re, os
path = os.path.expanduser("~/.zcode/AGENTS.md")
content = open(path, encoding="utf-8").read()
pattern = r'<!-- regress-guard start -->.*?<!-- regress-guard end -->\n*'
new = re.sub(pattern, '', content, flags=re.DOTALL).rstrip() + '\n'
open(path, "w", encoding="utf-8").write(new)
print("已从 AGENTS.md 移除回归契约")
PYEOF
    info "AGENTS.md 回归契约已移除"
fi

# ─── 6. 清理文档（可选）──────────────────────────────
if [ -d "${ZCODE_HOME}/regress-guard-docs" ]; then
    rm -rf "${ZCODE_HOME}/regress-guard-docs"
    info "删除文档"
fi

echo ""
echo "════════════════════════════════════════════"
echo -e "${GREEN}  ✅ regress-guard 已卸载${NC}"
echo "════════════════════════════════════════════"
echo ""
echo "项目的 .regress/ 目录未删除（保留历史数据）。"
echo "如需彻底清理项目，手动删除项目中的 .regress/ 文件夹。"
