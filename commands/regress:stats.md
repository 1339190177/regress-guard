---
description: 健康报表：门禁拦截/债务/规律命中/僵尸清单/钩子活性一屏读（观测期仪表盘，只读不改）
allowed-tools: Read, Bash
---

# /regress:stats — 健康报表

一屏读完治理实况。**只读**——本命令不改任何状态，全部数据来自既有产物。
观测期仪表盘（病例：v1.26.1 审计时手工统计部署差异，本命令是那次需求现场的工具化）。

## 执行（五个既有 CLI，零新采集）

```bash
# 1. 提交观测：通过/绕门禁/覆盖率/技术债
python3 "<插件路径>/hooks/scripts/lib/history.py" .regress summary

# 2. 考古地层：跨会话重复失败（稳定经验候选）
python3 "<插件路径>/hooks/scripts/lib/journal.py" . digest

# 3. 规律账本：固化候选 🦴 / 降级候选 🍂
python3 "<插件路径>/hooks/scripts/lib/rules_ledger.py" . health

# 4. 钩子活性（链外看门狗）
python3 "<插件路径>/scripts/check_docs.py" 2>&1 | grep -E "config.file.invalid|空 matcher" || echo "钩子链健康"

# 5. 僵尸清单：planning/verifying 搁置 >30 天（哨兵口径）
grep -l "status: planning\|status: verifying" .regress/manifests/*.md 2>/dev/null | while read f; do
  age=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 86400 ))
  [ $age -gt 30 ] && echo "⏰ $(basename $f) 已搁置 ${age} 天"
done; true
```

## 输出格式

```
📊 regress-guard 健康报表 · <项目名>
  门禁：<n_pass> 过 / <n_outside> 绕行（IDE 直提）/ 债 <debt> 笔
  地层：<n_events> 事件 / 跨会话重复失败 <n_sig> 个签名
  规律：<n_rules> 条（🦴 固化候选 <a> / 🍂 降级候选 <b>）
  钩子：健康 | ⚠️ <看门狗告警>
  僵尸：<无 | ⏰ 清单×n>
```

## 解读要点

- **绕行率持续高** → 门禁采用率问题（IDE/终端直提），不是测试问题——先解决提交习惯
- **债不还** → 赦免权闭环失效的前兆（PHILOSOPHY §11）
- **规律只涨不落** → 该跑 learn 并修剪降级候选（熵增警戒）
- 全部为零 → 项目刚开始或钩子长期静默——用第 4 项确认链活性
