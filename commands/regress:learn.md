---
description: 分析历史+检测框架规则，输出项目洞察，写入 AGENTS.md
allowed-tools: Read, Write, Edit, Bash
---

# /regress:learn — 学习项目规律

分析历史 + 框架 co-change 规则，输出洞察，**写入 AGENTS.md**。

## 执行

```bash
# 历史分析
python3 "<插件路径>/hooks/scripts/lib/history.py" .regress summary

# 框架 co-change 规则
python3 "<插件路径>/hooks/scripts/lib/cochange_rules.py" .

# 考古地层挖掘（公理三：跨会话重复失败 = 稳定经验）
python3 "<插件路径>/hooks/scripts/lib/journal.py" . digest
```

## 考古地层（.regress/journal/events.jsonl）

工具失败、风险动作、用户纠正三类化石自动埋入地层（随 git 入库，重启不丢）。
`journal.py digest` 输出**跨会话出现 ≥2 次**的重复失败签名（单会话高频是重试噪声，
跨会话重复才是稳定经验）。

digest 不为空时，对每条重复签名：
1. `journal.py . raw` 找到该签名的历次现场（时间/会话/上下文）
2. 判断根因模式（环境缺依赖？路径假设错？API 误用？）
3. 写入下方项目规律块，格式：`- 「<签名>」反复失败 ×N（N 个会话）：根因 <模式>，先 <对策> 再动手`

## 如果 total_commits == 0
告诉用户："暂无历史数据。用了几次后再来。"

## 如果 tech_debt > 0
```
💳 技术债务：{debt} 笔 bypass 未补回归
```

## 如果 outside_gate_commits > 0
```
📤 {n} 次提交未走门禁（IDE/终端直提或历史回填）——门禁采用率的诚实镜子
```

## 如果 avg_coverage_pct 非 null
```
📊 平均测试覆盖率 {n}%（jest 项目自动采集）
```

## 如果 top_f3_files 不为空 → 写入 AGENTS.md
```markdown
<!-- regress-guard learn start -->
## 项目规律（/regress:learn 自动发现）
- 改 src/auth/ 时，src/utils/validator.js 通常需要同步改（出现 5 次）
<!-- regress-guard learn end -->
```

## 报错自救合流（v1.15）

清单里预先写的 rescue（报错→自救命令）与地层学出的失败根因是同一回路的两端：

- digest 里的签名，若在活跃/历史清单的 `rescue:` 或「报错自救」表里已有对策 →
  把「报错关键词 → 自救命令」写进上面的项目规律块（跨任务的 FAQ）
- 只有失败没有对策 → 标注"待补自救"，下次踩同坑时先回填清单再修

## 自主决策
- 发现规律 → 直接写入项目 AGENTS.md（不问用户）
- 数据太少（<3 次提交）→ 告诉用户多用几次再来
