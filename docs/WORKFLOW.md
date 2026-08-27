# 工作流

## Full 模式（团队/大需求）

```
/regress:init           一次性初始化
      ↓
/regress:plan <需求>    → 清单(F1,F2)
      ↓
[补 characterization test]  ← 无测试的老代码（skill 自动提示）
      ↓
[AI 开发]               ← 可能产生 F3
      ↓
/regress:track          → 发现 F3，回写清单
      ↓
git commit              ← hook 自己跑测试，通过才放行
```

## Fast 模式（个人/小改动）

```
[先改好代码]
      ↓
/regress:quick <需求>   → 基于 diff 生成清单（全 actual）
      ↓
git commit              ← hook 跑测试，通过放行
```

## Bypass 模式（紧急 hotfix）

```
/regress:bypass 10     → 开启 10 分钟绕过窗口
      ↓
git commit             ← 放行（记入 .regress/bypass.log）
      ↓
（到期自动恢复严格模式）
```

## 信任链

hook 在 commit 时**自己跑测试**（自动探测 jest/pytest/maven/go test）：
- **测试通过** → 写入 `test_verified_by: hook` + `status: done` → 放行
- **测试失败** → 阻断，列出失败用例
- **无测试运行器** → 回退到检查清单 status（降级信任）

## 状态流转

`planning → in-progress → done`

`done` 由 hook 写入（测试通过时），不由 AI 手动标记。

## 降级

- `.regress/config.json` → `"strict": false`：hook 降级为仅警告
- `/regress:bypass <分钟>`：限时绕过 + 审计日志
