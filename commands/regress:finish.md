---
description: 收尾流水线：track 回写 → verify 全证据 → 代谢沉淀 → 状态推进 → 汇总报告（一条命令走完收尾，人只出现在决策点）
argument-hint: [manifest-id]
allowed-tools: Read, Write, Edit, Bash, Grep
---

# /regress:finish — 收尾流水线

实施完成后的一条命令收尾：**track → verify → 代谢沉淀 → 提交就绪**。
流程段之间没有人肉粘合剂——中间不需要人，人只出现在两个决策点
（残留 open/flagged 的处置、提交本身）。

找最新 `status != done` 的清单（或用 `$ARGUMENTS` 指定 id），依次执行：

## 步骤 1：track（F3 回写 = 扩界留痕）

按 /regress:track 的完整规则执行：`git diff` + 未跟踪文件对比清单，
F3 直接回写 `actual_changes`（这是开发边界的扩界出口，留痕）。

## 步骤 2：verify（全证据）

按 /regress:verify 的完整规则执行：

- 跑项目测试——失败自己修再跑；**修复 3 次仍败或需要输入 → 先分流再受阻**：
  知识型阻塞（用法/取舍/报错不懂）先带四问去 consult，顾问能解则继续（标注采纳情况）；
  环境/权限型或顾问不能解 → `plan_approve.py <清单> --block --reason --need`
  （tried 里写明顾问意见），把 need 转达人类，流程到此暂停
  （受阻是合法停止，不是 finish 失败）
- 逐条脆弱点：带 `rescue:` 的失败**先自救再重试**；通过 → `locked`；
  sensory 类 → 问人一个布尔问题，`human_check` 化石落档后转 locked（verify 写
  `human_check:<vid>`，门禁验化石存在性不复跑感官）；
  实测证伪假设 → 「假设失效记录」+ 地层化石；显式不处理 → `flagged`（写明知悉原因）
- env.lock.json 漂移检测（漂移了要在报告里标红）

## 步骤 3：状态推进（机器判据，不由感觉）

- **全部脆弱点 locked/flagged + 测试绿** → 无需手动改 status：直接提交。
  commit 门禁自跑测试复验，通过时自动写 `status: done` + `test_verified_by: hook`
  ——done 是门禁发的，不是自称的
- **有残留 open** → 这是人的决策点，两条路摆给用户：
  ① 列出每条 open，说明锁死还差什么证据；② 显式 flagged（写明知悉原因）
  用户不表态不继续

## 步骤 4：代谢沉淀位（v1.24：任务结束必过，有料沉淀无料跳过）

任务收尾即代谢入口——规律不靠人想起来才沉淀（病例：v1.23 排障纪律靠人类推动才固化）：

```bash
python3 "<插件路径>/hooks/scripts/lib/journal.py" . digest
```

- **digest 非空 / 本次有 rescue 回填 / top_f3 有新共变** → 执行 /regress:learn 的沉淀
  流程（规律入 AGENTS.md 标记块 + `rules_ledger.py . record` 记账），汇报新增规律条数
- 全空 → 报告一行「无可沉淀，代谢跳过」——不硬凑
- 顺带跑 `rules_ledger.py . health`：命中 ≥3 的稳定规律输出「建议固化 skill」卡片
  （🦴 经人批准后用 skill-creator 固化——**自动固化的错误经验会以技能的形式高速复发**）

## 步骤 5：汇总报告

```
🏁 收尾完成 · REGRESS-<id>
  改动：F1/F2（计划内）+ F3 × <n>（已回写留痕）
  脆弱点：<n_locked> locked / <n_flagged> flagged / 0 open
  测试：<passed>/<total> 通过<+覆盖率>
  债务：<tech_debt> 笔 bypass 未补回归（>0 要提示还债）
  环境：<与 env.lock 一致 或 ⚠️已漂移：项>

可以提交（门禁复验后自动标 done）。
```

## 自主决策

- 清单已是 done/completed → 报告"已收尾"，只输出债务/漂移检查
- 测试全绿但用户不在场 → 报告就绪状态并停，不代答 open 的处置
- 小改动收不了尾（无清单）→ 提示下次走 /regress:quick 或先 /regress:plan
