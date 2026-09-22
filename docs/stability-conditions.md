# 稳定性条件自审表（self-improvement stability conditions）

> v1.88.2（批 101）。来源：better-harness learning-loop-research-basis 深研借抄
> （2026-09-21，工作区 .regress/better-harness-deep-study-2026-09-21.md 思想三）。
> 他们把九篇 2026 自进化 Agent 论文压成七条稳定性条件并逐条自审；本文把同一张
> 表套在 regress-guard 自己身上——因为本插件本身就是一个 self-improving 系统
> （它开发自己、治理自己的开发）。

**核心句（借抄）：无受控准入的自主修改是失败模式，不是默认。**

## 七条件 × 本仓自审

| # | 条件（来源） | 本仓自审 | 补法草图 |
|---|---|---|---|
| 1 | 只在 held-out 分数严格改善时接受编辑（SkillOpt） | **Absent**——只有 rollback 触发器，无 held-out 验收门 | 公开基准集（benchmarks/ 82 例）作 held-out 面：走批前后跑一遍，退化即拦（候选机制，未建） |
| 2 | 只保留验证 Pareto 前沿上的资产（EvoSkill） | **Absent**——命令/规则只进不出（代谢靠人肉） | 已有 /regress:stats 零火摘除惯例，缺前沿判定 |
| 3 | 验证器与测试内容隔离但仍给可行动反馈（CoEvoSkills） | **Partial**——门禁跑项目自己的测试（验证器=被验物同源）；基准集独立于项目测试是隔离面的一半 |
| 4 | 同策略配对对比基线/注入运行，差值为更新信号（D2Skill） | **Absent**——版本对比是叙事不是实验 | 同批工作负载下新旧版各跑 N 次取差值（成本高，先立差距面） |
| 5 | 每次编辑有界，被拒编辑进缓冲区，不再重提（SkillOpt） | **Partial**——decisions.md 记否决但无机器缓冲，砍掉的方案可换皮重提（白嫖/自驳分类学是手工补丁） | 走批前顾问预审附"近 90 天已否决方案"检索（候选） |
| 6 | 归因到 episode 粒度以下再怪某步骤（GiGPO） | **Absent**——归因在清单/staged 文件级 | 暂不补（单维护者批粒度已够用，防过度工程） |
| 7 | 生成 held-out 任务而非假设固定套件（AgentEvolver） | **Absent**——基准集冻结不生成 | 暂不补（生成器自身需要稳定性条件，递归风险） |

## 宣称约束（本表的用途）

- 在条件 1/4 补齐之前：**任何特性的"有效"宣称上限=已证活（Exercised）**，
  不许说已证效——与 claim-discipline.md 七态表联动。
- 遥测计数（命中率/拦截数）按计数≠行为规则只当线索；
  est_saved_seconds 类估算保持 est 前缀诚实。
- 特性零火探测（`history.py features`）的 unmeasurable 态=宣称上限为零；
  量测位补齐后（如本批的 rule_recall_fired）从零升 Exercised 观察位。

## 配套词汇（借 better-harness 蒸馏七阶段，本仓映射）

capture（journal/标本）→ generalize（规律账本 bigram 聚合）→ codify（规则/命令）
→ route（skill/命令路由）→ **exercise（点火=Exercised）**→ evaluate（本表条件）
→ maintain（零火摘除/代谢）。其中 exercise 态两个反模式名直接可用：
`routed-but-not-applied`（路由了没应用）、`asset-updated-not-reexercised`
（资产更新了没重训）。

## 解释边界

- 本表借的是形状；better-harness 的自审结论（他们哪些 Absent）不迁移到本仓。
- 本表自身是 Exercised 以下产物：表建立=已配置，被走批引用=已接线，
  真正拦下一次越线效果宣称=已证活（观察位）。
- 条件 6/7 的"暂不补"是裁决不是遗忘——重评触发器=出现批粒度归因冤案/
  基准集被记忆污染的实际病例。
