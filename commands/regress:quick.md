---
description: 快速模式——合并 plan+track 一步到位（适合个人项目/小改动）
argument-hint: <需求描述>
allowed-tools: Read, Write, Edit, Bash, Grep
---

# /regress:quick — 快速模式

合并 `/regress:plan` 和 `/regress:track` 为一步：**基于 git diff 直接生成完整清单**（不分 planned/actual，全部算实际改动）。适合小改动或个人项目。

## 与 full 模式的区别

| | full 模式 | quick 模式 |
|---|---------|----------|
| 流程 | plan→开发→track→verify | 开发→quick→commit |
| 步骤 | 4 步 | 2 步 |
| F3 追踪 | ✅ 区分计划内/外 | ❌ 不区分（全是 actual） |
| 适用 | 团队/大需求 | 个人/小改动 |

## 流程

参数 `$ARGUMENTS` 是需求描述。

### 步骤 1：用户先改好代码

quick 模式假设代码**已经改完了**。如果还没改，提示用户先改代码。

### 步骤 2：基于 git diff 生成清单

```bash
# 获取所有改动文件
git diff --name-only HEAD
git ls-files --others --exclude-standard
```

对每个改动文件（过滤 `.regress/`、`AGENTS.md`、锁文件、`.md`），分析改动类型：
```bash
git diff <file>  # 看具体改了什么，判断 method-logic/signature/new-file/model
```

### 步骤 3：生成清单（全部记为 actual_changes）

```yaml
---
id: REGRESS-<序号>
requirement: "<需求>"
status: in-progress
planned_changes: []
actual_changes:
  - id: F1
    file: "<文件>"
    type: <类型>
    reason: "quick 模式：基于 git diff 生成"
    tests_required: [unit]
mode: quick
---
```

### 步骤 4：提示用户

```
⚡ 快速清单已生成（mode: quick）
   F1: src/auth/login.js (method-logic)
   F2: src/utils/validator.js (new-file)

现在可以直接 git commit。
hook 会自动跑测试验证，通过后放行。
```

注意：quick 模式下 commit 时 hook **仍然会跑测试**，只是跳过了 plan/track 两步。
