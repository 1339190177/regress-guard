---
id: REGRESS-{{YEAR}}-{{SEQ}}
requirement: "{{RAW_REQUIREMENT}}"
understood_intent: "{{AI_PARSED_FULL_DESCRIPTION}}"
assumptions:
  - "{{ASSUMPTION_1}}"
  - "{{ASSUMPTION_2}}"
confirmed: []
ambiguities_resolved:
  - point: "{{AMBIGUITY_POINT}}"
    ai_choice: "{{AI_DECISION}}"
    basis: "{{CODE_OR_CONVENTION_BASIS}}"
status: planning         # planning=待批准（拦编辑）→批准后 in-progress；blocked=受阻（拦编辑，四问见 blocked 块）；cancelled=取消归档；done=收尾
base_head: "{{GIT_HEAD_SHORT}}"   # 创建时 git HEAD 短sha（非 git 项目留空）——批准时校验计划是否漂移
approved:                # 批准落产物（v1.13）：批准词由 AI 转写（plan_approve.py），或人类直接填 at（产物直通）
  at: ""                 # 批准时间（空=未批准；非空=边界守卫视同已批准）
  note: ""               # 批准附言/修改要求
blocked:                 # 受阻记录（v1.14）：卡住别硬磨别绕过——plan_approve.py --block 写入四问
  reason: ""             # 阻塞在哪（具体命令/代码位置/环境）
  tried: ""              # 已尝试的方法
  unsafe_why: ""         # 为什么不能安全继续
  need: ""               # 需要人类提供什么（信息/权限/决策）
  at: ""
provisional:            # 临行（v1.18 伪全自动）：预授权任务经顾问预审无方向性异议后临行；否决=--cancel
  at: ""                 # 临行时间（空=非临行）；哨兵显示 🚀 否决窗内
  advisor: ""            # 预审一句话结论——顾问有一票否决权，没有一票批准权
planned_changes:
  - id: F1
    file: "{{FILE_PATH}}"
    type: method-logic
    reason: "{{REASON}}"
    tests_required: [unit, smoke]
    characterization_needed: false
actual_changes: []
boundary:              # 开发边界（hook 事前拦截越界 Edit/Write；track 回写即扩界）
  include:
    - "src/**"         # 改动所在目录
    - "tests/**"       # 配套测试
fragile_points:        # 公理一：穷举致使失败的关键脆弱点，逐个挂牌
  - id: V1
    kind: env          # env | dependency | resource | data | concurrency | api | oracle | sensory
    description: "{{FRAGILE_DESCRIPTION}}"
    verify: "{{VERIFY_COMMAND}}"   # 可执行命令，/regress:verify 跑它拿证据
    rescue: "{{RESCUE_COMMAND}}"   # 可选：verify 失败/见典型报错时先敲这个（自救）
    status: open       # open=未挂牌(禁提交) / locked=verify已通过 / flagged=带病挂牌
test_results: {}
created_at: "{{DATE}}"
---

# 回归清单：{{REQUIREMENT}}

## 需求理解

**原始需求**：{{RAW_REQUIREMENT}}

**AI 理解**：{{UNDERSTOOD_INTENT}}

**设计取舍**（v1.25）：{{被否备选方案}}——否决因：{{一句理由}}（没有备选的设计不是设计）

**用户所见**（v1.26 草图先行，用户可见功能必备）：{{界面示意 / 三步交互流 / API 示例——否决发生在草图，不在实现后}}

**假设**（如有不符请指出）：
1. {{ASSUMPTION_1}}
2. {{ASSUMPTION_2}}

## 验收标准（做到什么算完 · v1.25：需求的证据律）

> 每条必须可检验：布尔判据或可观察行为。"根治/优化/更好"这类词必须挂在下面
> 某条判据上，指不回去的词不许出现在汇报里。非功能底线（延迟/安全/兼容）在
> 这里定型——它们在需求阶段缺席，设计就会朝反方向跑
> （病例：REGRESS-005 jitter buffer，产品价值观在两轮过度设计后才抵达）。
> 与脆弱点互补分层：验收=需求侧 done 定义（功能对不对），脆弱点=风险侧（周边会不会坏）。

| # | 判据（可检验） | 证据（verify 命令 / human_check） | 状态 |
|---|--------------|-----------------------------------|------|
| A1 | {{例：发起对讲后 3s 内建流，全程无断续}} | {{真机听感 human_check:V8}} | open |

## 环境准备（必读 · 写给失忆的读者）

> 写给失忆的读者：只凭这段把环境跑起来，不求助、不迷路。（写作指导 /regress:plan 4.7）

- **运行时**：{{JDK/Node/Python 版本及原因；有 --add-opens 之类的特殊参数直接给全命令}}
- **外部依赖**：{{Redis/TDengine/…：本地装还是隧道连？给出 ssh -L 等现成命令}}
- **启动入口**：{{唯一正确的启动脚本；若"别点 IDE 的 Run"必须写明}}

## 实施顺序（一步一响）

> planned_changes 是集合，这里是序列：每步挂**可观察里程碑**，做完一步见到一步的响。

| 步 | 做什么 | 里程碑（做到什么算过） |
|---|--------|----------------------|
| 1 | {{基石：无网络依赖的纯逻辑 + 单测}} | {{对应单测绿}} |
| 2 | {{骨架：服务/端口能起}} | {{控制台打印出约定日志}} |
| 3 | {{协议/联动}} | {{可观察的输出}} |

## 预期改动点

### F1: {{FILE_PATH}} — {{TYPE}}
- **改动原因**：{{REASON}}
- **测试要求**：unit + smoke
- **影响范围**：{{AFFECTED}}

## 脆弱点拓扑（公理一）

成功不是代码跑通，而是所有已知脆弱点被锁死或显式挂牌。
**未列出的脆弱点才是真正的未知风险**——动手前穷举：谁帮我设了环境变量？
依赖库会不会报错？资源会不会被抢（PID/端口/GPU）？数据会丢吗？

| ID | 类型 | 脆弱点 | 验证命令 | 状态 |
|----|------|--------|----------|------|
| V1 | env | {{FRAGILE_DESCRIPTION}} | `{{VERIFY_COMMAND}}` | open |

> status 流转：open →（verify 命令实测通过）→ locked；
> 或 open →（明知风险但暂不处理，写明原因）→ flagged。open 状态禁止提交。
>
> sensory 类（人的感官是唯一判据，如对讲声音清晰）：问人只收**通过/不通过**，
> verify 写 `human_check:<vid>`，结果落化石（`journal.py . add human_check`）——
> 门禁验"人确认过"这个事实的存在，不复跑感官。

## 报错自救（What if broken）

> verify 失败先查这张表再动手：左列报错关键词、右列自救命令（与 rescue 字段同源；
> 踩坑修复后回填，经 /regress:learn 沉淀为项目规律）。

| 报错关键词 | 自救 |
|-----------|------|
| {{UnsatisfiedLinkError taos}} | {{用 run-local.sh 启动，别用 IDE Run}} |

## 假设账本（排障任务必填 · v1.23：先检验后动手）

> 病例 REGRESS-005：三轮"根治"全上，真凶是自己上一轮写的参数（全文 docs/PHILOSOPHY.md §4）。

每个假设先过检验关，裁决通过才写修复代码——**写不出当场能跑的检验命令的，
不是假设，是猜测。**

| # | 假设 | 检验命令（当场可跑） | 结果 | 裁决 |
|---|------|---------------------|------|------|
| H1 | {{例：前端超发导致丢帧}} | {{grep 日志统计实际到达帧率}} | {{实测 50fps}} | 证伪 |

裁决规则：
- **第一嫌疑人 = 自己最近的 diff**——症状出现在某次修复之后，先 `git log` 审那次
  修复，再向外搜（前端/固件/网络）
- 检验通过 → 才允许写修复代码；修复后 oracle 仍报问题 = **假设被证伪**，
  不是"防御不够"——回本表新增一行重新取证，禁止直接叠防御层（叠层须出示新证据）
- **旧解释不复用**——上个根因对这个症状无效，上次为真 ≠ 这次为真，复用必须重测

## 假设失效记录（v1.14：失效过程比结论值钱）

假设被实测证伪时**不要悄悄改写**——追加一行，把 was→reality→evidence 留在产物里：

| 脆弱点 | 原假设（was） | 实际（reality） | 证据（evidence） |
|--------|--------------|----------------|-----------------|
| V? | （推测：按 1601/1603 格式） | （实测：Cmd=7203 但 Ack=1） | `node mock-device.js --self-test` 输出 |

同时埋一条地层化石（机器可读）：

```bash
python3 "<插件路径>/hooks/scripts/lib/journal.py" . add assumption_broken \
  '{"manifest_id":"<ID>","vid":"V5","was":"<原假设>","reality":"<实际>","evidence":"<命令>"}'
```
