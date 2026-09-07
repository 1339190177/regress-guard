#!/bin/sh
# regress-guard commit observer
# 记录所有来源的提交（IDE/终端/ZCode）到 .regress/history.jsonl，补全证据链。
# 特性：静默 / 自禁用（.regress 删除后失效）/ 永不阻断 / monorepo 向上查找 / 来源区分。
D="$(git rev-parse --show-toplevel 2>/dev/null)"
RG=""
while [ -n "$D" ] && [ "$D" != "/" ]; do
  [ -d "$D/.regress" ] && RG="$D/.regress" && break
  D="$(dirname "$D")"
done
[ -n "$RG" ] || exit 0

# 消费 expect-commit 标记（新鲜<5min 才认）：区分门禁放行/绕过 vs 外部直提
SRC="git-hook"
EXP="$RG/.expect-commit"
if [ -f "$EXP" ]; then
  if [ -n "$(find "$EXP" -mmin -5 2>/dev/null)" ]; then
    SRC="zcode-$(sed -n 's/^kind=//p' "$EXP" | head -1)"
  fi
  rm -f "$EXP" 2>/dev/null
fi

SHA="$(git rev-parse --short HEAD 2>/dev/null)"
SUBJ="$(git log -1 --format=%s 2>/dev/null | head -c 80 | sed 's/\\/\\\\/g; s/"/\\"/g')"
printf '{"timestamp":"%s","event":"commit_observed","manifest_id":"","commit_sha":"%s","subject":"%s","source":"%s"}\n' \
  "$(date -Iseconds)" "$SHA" "$SUBJ" "$SRC" >> "$RG/history.jsonl" 2>/dev/null
exit 0
