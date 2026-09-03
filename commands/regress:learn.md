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
4. **同步记账（v1.24 代谢链）**：
   ```bash
   python3 "<插件路径>/hooks/scripts/lib/rules_ledger.py" . record --sig "<签名>" --occurrences <N>
   ```
   首次沉淀 hits=1；同签名再检出（下次 learn 又见到它）= 命中一次——
   命中是固化的证据，没记过账的规律块只会膨胀（实测：真实项目 3 周 18 节）

**产品否决同样可挖（v1.26）**：digest 之外查 `design_rejected` 类化石——
跨任务重复的产品否决（行业惯例/用户习惯/该简化）升格为产品规律，写入
`.regress/product-context.md` 的「设计否决记录」段，稳定后晋级「行业惯例」段。

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

## 规律健康（v1.24：记账的另一半是衰变）

```bash
python3 "<插件路径>/hooks/scripts/lib/rules_ledger.py" . health
```

- 🦴 **固化候选**（hits ≥3）：稳定规律建议固化为宿主 skill——输出卡片**等人批准**，
  批准后用 skill-creator 造（地层是脂肪，规律是肌肉，skill 是骨骼）
- 🍂 **降级候选**（>180 天零命中）：提示人工修剪——**本工具永不自动删 AGENTS.md**
  （人类文件红线）；只进不出的"知识库"是熵增库
- 空 digest + 空账本 → 告诉用户"暂无可沉淀规律"，不硬凑

## 自主决策
- 发现规律 → 直接写入项目 AGENTS.md（不问用户）
- 数据太少（<3 次提交）→ 告诉用户多用几次再来
