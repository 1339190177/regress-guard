# dsh 桌面版支持（批166，REGRESS-2026-164·特种分支 special/dsh-desktop）

把 regress-guard 全量钩子链挂上 DeepSeek dsh 桌面版（DeepSeek Harness）。
本文是架构决策记录（ADR 位）+安装/运维手册。

## 架构（为什么是桥而不是原生插件）

**选型：官方 CC 方言桥 @deepseek-ai/dsh-hooks-claude-code（0.0.1-rc.1）。**

- dsh 官方提供 dsh-hook-protocol（Claude Code/Codex 钩子线协议：matcher
  引擎+stdin/exit-code/stdout 编解码）与 dsh-hooks-claude-code 桥——后者
  直接装载用户的 CC 方言 hooks.json 于 dsh 规范拦截点。regress-guard 的
  hooks.json 本就是 CC 方言（ZCode 钩子体系同族形态）。
- 桥的映射（其 README 契约）：PreToolUse→tools/pre-execute（deny→
  PreToolDecision.deny）、PostToolUse→tools/post-execute、SessionStart→
  agent/session-start、Stop→agent/turn-stopping、UserPromptSubmit→
  agent/pre-step。exit 2 语义=deny，与我们门禁拦截同构。
- 备选不采：自写原生 cordis 插件（桥 README 自述"原生插件能做这一切"，
  但绑定 cordis 内部 API 面，维护成本高于一条 hooks.json 配置；桥路径
  零代码即得全链）。若未来需要 typed 增强点再评估原生化——观察位。

## 三处适配（侦察实证，2026-10-30）

1. **变量+布局**：源仓命令串（ZCODE 变量 + 源仓脚本子目录前缀）→已装
   根实体路径（变量=桥契约换 CLAUDE；前缀剥离=install.sh 把脚本摊平拷到
   已装根；特例 self_heal 搬进 lib/，install.sh:98）——install_dsh.py
   生成 hooks.cc.json 入已装根并做**全命令实体校验**（每条命令引用的
   文件必须在已装根存在——路径错位的失效形态=桥静默含错放行，e2e 活体）。
2. **工具名 matcher 展宽**：桥 matcher 匹配宿主工具名；dsh 注册名是小写
   `bash`/`read`/`write`/`edit` 另有 `pwsh`（CC 系是首字母大写）。载荷
   字段名两家一致（dsh-tool-fs README 明示 snake_case 对齐 Claude Code，
   `file_path`/`command` 均同）——故只需 matcher 双方言：Bash→Bash|bash|
   pwsh 等（MATCHER_WIDEN 表，install_dsh.py）。
3. **会话身份+工具名规范化**：dsh 桥不设 CLAUDE_SESSION_ID env——会话身份
   在 stdin payload 的 session_id 字段。lib/host_env.py absorb_session
   垫片：env 缺席时从 payload 吸收（只补缺不覆盖）。工具名规范化垫片：
   dsh 小写名→CC 形态（钩子内部分支按 CC 大小写匹配，不规范化=全线漏判
   假阴性）。接线：rbe/pre_commit/boundary/risk/fail 五钩子。

## 安装的三个坑（e2e 活体标本，install_dsh.py 已内置防护）

1. **桥版本必须与 dsh 运行时配对**：裸 `dsh plugin add` 解析到旧线
   0.0.1-rc，其 `agent.session.events` API 与运行时 0.2.1-rc 错配——所有
   bash 调用恒报 "agent.session.events is not iterable"。装版本配对
   `bridge@<dsh版本>`（0.2.1-rc.5 实证）。
2. **桥的 protocol 是 peerDependency**：宿主不显式装则桥 import 失败=
   **静默含错放行**（提交穿门）。ensure_bridge_pkg 双包同装。
3. **在位判定查 node_modules 实体**：lock 字符串会被 peerDependency
   声明行误中（假绿）。

## 攻克判据（e2e，2026-10-30 实证达成）

真实 DeepSeek agent 会话（dsh --profile headless，deepseek-official）在
fixture 仓（活跃清单 R1 边界=src/app.js，staged 越界文件）执行
`git commit`：**提交未发生**（fixture git log 空），agent 收到完整拦截消息
（"commit 被阻断。以下 staged 文件不在回归清单中…请先运行 /regress:track
回写"）并原样转达、零绕过。全链：dsh bash 工具→桥 PreToolUse→
hooks.cc.json（摊平路径）→launcher/门禁→deny→agent。复跑可再现。

## 100% 冲刺（批167，v2.5.0）——两个探针实证与三处补位

- **SessionStart 实证**：工作区探针捕获 payload `source:"startup"`——
  与 self_heal 的 matcher 完全吻合（compact_notice 同词对齐）。
  "待证"转"实证"。
- **沙箱纪律（重大发现）**：dsh 桥经 ctx.shell 跑钩子=**会话
  workspace-write 沙箱辖内**——写 /tmp 被拒且各写者 except 静默。推论：
  状态文件在 /tmp 的钩子在 dsh 全部静默失效。修=host_env.
  sandbox_aware_state_dir（/tmp 写探测→失败回退 CLAUDE_PROJECT_DIR/
  .regress/tmp 工作区内），接线 rbe/fail_watch/risk_watch/stop_notify/
  reflection 五写者。ZCode 无沙箱=探测恒成功零行为变化。
- **fail_watch 补位**：dsh 无 PostToolUseFailure 桥点——hooks.cc 生成时
  把 fail_watch 复挂到 PostToolUse，载荷带 tool_response 时自筛失败
  （dsh 归一化契约：`[exit code: N>0]` 或 `Error:` 前缀；无该键=宿主已
  筛的 ZCode 语义直通）。
- **能力矩阵终态**：ZCode 100%（原生全事件面）；dsh 100%*（*唯一 N/A=
  plan_bridge——dsh 无原生计划模式，宿主概念缺位非缺口；上游加计划
  模式后 hooks.cc 生成器已预留复挂模式可循 fail_watch 先例扩展）。

## 如实声明（能力子集，spec §13.2 精神）

**降级面**：
- PostToolUseFailure 无桥接点 → fail_watch（失败信号采集）在 dsh 缺位。
- read_image 不计入读计数（图像不授文本认知——MATCHER_WIDEN 注记）。
- ExitPlanMode matcher 在 dsh 无对应工具 → plan_bridge 两钩子不触发
  （dsh 无原生计划模式，本就无计划可转录）。
- SessionStart matcher 主题=dsh 会话来源；startup/compact 若命名不同则
  self_heal/compact_notice 不触发（缺位非误拦）。

**不受降级影响的主链**：提交门禁（PreToolUse launcher）、边界守卫、
执行阀、先读后改、风险采集（PostToolUse）、**失败信号采集（批167 起：
PostToolUse 自筛复挂）**、反思检查（Stop）、需求入口
（UserPromptSubmit）、自愈/压缩提醒（SessionStart，source=startup/
compact 实证契合）——全部在桥的映射点内。

**AGENTS.md 契约**：dsh-agent-instructions 原生装载（64KB 预算，dsh-base
默认启用）——回归契约注入免改自动生效。

## 安装 / 卸载

```bash
python3 scripts/install_dsh.py              # 安装（默认 profile=web=桌面版）
python3 scripts/install_dsh.py --check      # 诊断（桥包/patch 条目/hooks.cc.json）
python3 scripts/install_dsh.py --remove     # 精确移除本批接线（不动他人条目）
python3 scripts/install_dsh.py --profile headless   # 指定 profile
```

前提：已装 regress-guard（install.sh——已装根 = 桥的 pluginRoot）+本机
有 ~/.dsh。桥包装入走 `dsh plugin --profile <p> add @deepseek-ai/
dsh-hooks-claude-code`（版本配对 dsh 运行时）+protocol peer，实体在位
判定）。

## 风险与观察位

- 桥 0.0.1-rc.1 漂移：失效形态=fail-closed（桥拒载不崩 dsh）。上游出
  stable 时钉版本复核。
- 双宿主并发（ZCode+dsh 同项目）：两宿主各自独立门禁（不同进程不同
  钩子链，非同宿主双重拦截）；read_before_edit 状态按会话分文件天然
  隔离（P2#17）。

## 真实桌面 demo 战报（2026-10-31，浏览器全驱动 dsh web UI）

demo 抓出**三个真缺口**（全部契约级测试测不出——载荷/环境形态只有真跑才现形）：

1. **字符串 tool_input 穿门（已修，v2.5.1）**：GLM/zai 通道的 tool-call
   arguments 序列化为 JSON 字符串而非对象（deepseek 通道是对象）——钩子
   找不到 command 键判"非提交"放行=越界提交穿门。修=host_env.
   materialize_tool_input 六入口接线；复现 rc 0→2 钉回归测试。
2. **web 钩子沙箱挂载视图隔离（已定位，观察位→上游）**：web 实例的钩子
   进程文件系统视图与宿主隔离（cwd 只读层、预置脚本对钩子不可见
   "No such file"实证）——guard 在该视图内可能看不到项目 .regress →
   判"未接入"放行。headless 无此问题（钩子=进程 cwd）。修复方向=上游
   桥 PreToolUse 载荷带 cwd（现仅 SessionStart 带）或原生插件；guard 侧
   无文件系统外通道可自愈。
3. **桥无 shell 执行**（排障纪律）：钩子命令不经 shell 解释——管道/引号
   是死字（tee 报错与 python exit 1 双实证）。探针必须免引号纯 argv 形态。

**demo 期间实证在岗**：门禁拦截（探针4/终验轮 hook 层 exit 2、git log
零新提交）、PostToolUse 风险采集、Stop 反思、UserPromptSubmit 需求入口
（hook/invoked 全记录在会话事件流，可考古）。
