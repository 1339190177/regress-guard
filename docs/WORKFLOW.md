# 工作流

> 自动触发为主，人类只在决策点。命令无需手动召唤——说需求即可（v1.12 起计划
> 待人类批准，v1.17 起收尾有流水线）。

## Full 模式（团队/大需求）

```
说需求（自然语言，无需敲命令）
      ↓ UserPromptSubmit 钩子提示 AI 走 plan 流程（含 /regress:init 自动兜底）
/regress:plan 逻辑       → 清单（F1/F2 + 脆弱点拓扑 + 边界 + 实施顺序），status: planning
      ↓ （可选顾问预审：有方向性异议必等人）
📋 计划卡片 → 人类 30 秒：批准 / 修改 / 取消      ← 人类决策点 ①
      ↓ plan_approve.py：status→in-progress + approved.at 落产物
      ↓ （预授权任务无异议可 --provisional 临行，进否决窗）
[AI 开发]                ← 边界守卫事前拦截越界编辑；受阻则四问落产物
      ↓                    （人类决策点 ②：给 need 所需的输入/权限）
/regress:finish          → track 回写 F3 → verify 全证据（rescue 自救/感官问人收布尔）
      ↓                    （人类决策点 ③：感官终验 human_check）
git commit               ← 门禁自跑测试 + locked 复验，通过自动写 done
```

## Fast 模式（个人/小改动）

```
[先改好代码]
      ↓
/regress:quick <需求>    → 基于 diff 生成清单（全 actual）
      ↓
git commit               ← 门禁跑测试，通过放行
```

## Bypass 模式（紧急 hotfix）

```
/regress:bypass 10       → 10 分钟赦免窗口（边界/门禁统一放行，赦后记债）
      ↓
git commit               ← 放行（审计日志 + 技术债记账，测试通过的提交才还债）
      ↓
（到期自动恢复严格模式；逾期未还会被哨兵点名）
```

## 信任链

hook 在 commit 时**自己跑测试**（自动探测 jest/pytest/maven/go test）：
- **测试通过** → 写入 `test_verified_by: hook` + `status: done` → 放行
- **测试失败** → 阻断，列出失败用例
- **无测试运行器** → 回退到检查清单 status（降级信任）
- **locked 脆弱点** → 门禁复验 verify 命令（证据律：locked = 此刻能过）；
  sensory 类验 human_check 化石存在性，不复跑感官

## 状态机（v1.20）

```
planning ──批准/临行──→ in-progress ──→ verifying ──门禁测试过──→ done
   │                      │    ↑
   │取消                  受阻 └─解阻
   ↓                      ↓
 cancelled ←──────────────（临行任务否决窗内可取消；正式批准的任务走受阻/完成）
```

`done` 由门禁写入（测试通过时），不由 AI 手动标记。blocked 期间边界守卫拦编辑。

## 无感层（自动，零操作）

- 会话启动：自愈/自动升级/老项目迁移/活跃清单哨兵（指路 /regress:resume）
- 编辑时：先读后改 + 文件指纹 + 边界拦截（AI 是第一现场，人看到的只是行为变好）
- 失败/风险/纠正：自动入考古地层，跨会话可考古
- 断点续作：`/regress:resume` 一句话重建现场

## 降级

- `.regress/config.json` → `"strict": false`：门禁降级为仅警告
- `"boundary_enforced": false`：关闭边界守卫
- `/regress:bypass <分钟>`：限时赦免 + 审计（不可赦名单：执行阀=物理不可逆、先读后改=防盲改）
