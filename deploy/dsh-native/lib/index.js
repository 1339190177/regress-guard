/**
 * dsh-regress-guard — regress-guard 的 dsh 原生拦截适配层（批169，special/dsh-native）。
 *
 * 为什么原生（桥 README 自述"原生插件能做这一切，更强、带类型返回"）：
 *  - 无序列化边界：直接消费 exec.arguments / result.content（类型化）；
 *  - 无沙箱挂载缺口：插件跑在 harness 进程内，spawn 钩子=真实文件系统视图
 *    （CC 桥经 ctx.shell 把钩子关进会话沙箱——cwd 只读、外部文件不可见，
 *    guard 判"未接入项目"放行，2026-10-31 桌面 demo 铁证）；
 *  - 无参数形态方差：exec.arguments 为对象或 JSON 字符串都在此物化
 *    （GLM/zai 通道字符串形态曾穿门，v2.5.1 修复在桥侧，此处原生兜底）；
 *  - 失败判定原生：post-execute 的 result 直接可判成败，fail_watch 不靠
 *    文本启发式。
 *
 * 单一事实源不变：判定逻辑全部在 guardRoot 的 python 钩子链里，本层只做
 * 适配（构造 CC 形态 payload + 正确的 cwd/env + 类型化 Decision 映射）。
 */
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
import fs from "node:fs";
import z from "@deepseek-ai/schemastery";
import { createCommandRegistrar, userTextMessage } from "./commands.js";

export const name = "regress-guard";

// 批205：commands 服务走运行时注入（ctx.inject）而非硬 inject——老宿主无
// 该服务时硬 inject 会让整个插件拒载=拦截面陪葬（fail-closed 回归）。运行
// 时注入：服务在则命令面挂载，不在则钩子面独走（命令面是增强不是主体）。
export const inject = ["workingDirectory"];

export const Config = z.object({
	guardRoot: z.string().default(path.join(os.homedir(), ".zcode", "regress-guard-hooks")),
	timeoutMs: z.number().default(600000),
	// 命令 md 目录（默认 guardRoot 同级的 commands/——install.py 装入位）
	commandsDir: z.string().default("")
});

const BASH_TOOLS = new Set(["bash", "Bash", "pwsh"]);
const EDIT_TOOLS = new Set(["edit", "Edit", "write", "Write", "ApplyPatch"]);
const READ_TOOLS = new Set(["read", "Read"]);

/**
 * dsh 工具名 → CC 形态（批171：payload 补 tool_name）。
 * boundary/rbe 侧 host_env.canonicalize_tool_names 会自行规范化，但
 * execution_valve 严格等 "Bash"（:214）不规范化——故 canonicalize 必须在
 * 此完成；对已是 CC 形态的名幂等（首字母大写恒等）。
 */
function canonicalToolName(name) {
	if (BASH_TOOLS.has(name)) return "Bash";
	if (EDIT_TOOLS.has(name) || READ_TOOLS.has(name)) {
		return name.charAt(0).toUpperCase() + name.slice(1);
	}
	return name;
}

/** 模型通道参数形态方差兜底：GLM/zai 的 arguments 是 JSON 字符串。 */
function materializeArguments(v) {
	if (typeof v === "string" && v.trim()) {
		try {
			const obj = JSON.parse(v);
			if (obj && typeof obj === "object") return obj;
		} catch { /* 非法 JSON 保持原值——守卫侧自有语义 */ }
	}
	return v;
}

function blocksToText(content) {
	if (!Array.isArray(content)) return "";
	return content.filter((b) => b && b.type === "text").map((b) => b.text).join("\n");
}

/** 原生失败判定：result 的 error 面 + 文本兜底（dsh 归一化：[exit code: N>0]）。 */
function resultFailed(result) {
	if (!result) return false;
	if (result.status === "error" || result.error) return true;
	const text = blocksToText(result.content);
	return /\[exit code: [1-9]\d*\]/.test(text) || text.trimStart().startsWith("Error:");
}

/** Python 解释器候选（批191：Windows 无 python3——python.org 只装 python.exe/py.exe）。 */
const PY_CANDIDATES = ["python3", "python", "py"];

/** 进程内跑一个 guard 钩子：真实 fs 视图 + 正确 cwd/env，stdin=CC 形态 payload。
 *
 * 批191：解释器候选回退（python3→python→py）；-E 移除——env 本就是白名单式
 * 最小集（无 PYTHON* 透传，投毒面为空），改注入 PYTHONUTF8=1 根治中文 Windows
 * cp936 编码崩溃；SYSTEMROOT 补入（Windows 上 python.exe 缺它起不来）。 */
function runGuardHook(scriptPath, hookArgs, payload, cwd, sessionId, timeoutMs, pyIdx = 0) {
	return new Promise((resolve) => {
		let settled = false;
		const done = (code, stderr, stdout) => {
			if (!settled) {
				settled = true;
				resolve({ code: code ?? 0, stderr: stderr ?? "", stdout: stdout ?? "" });
			}
		};
		if (pyIdx >= PY_CANDIDATES.length) {
			done(0, `regress-guard(native): 找不到 Python 3（试过 ${PY_CANDIDATES.join("/")}，fail-open 适配层）`);
			return;
		}
		try {
			const child = spawn(PY_CANDIDATES[pyIdx], [scriptPath, ...hookArgs], {
				cwd,
				env: {
					PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
					HOME: process.env.HOME ?? os.homedir(),
					LANG: process.env.LANG ?? "C.UTF-8",
					TZ: process.env.TZ,
					SYSTEMROOT: process.env.SYSTEMROOT,
					PYTHONUTF8: "1",
					CLAUDE_PROJECT_DIR: cwd,
					CLAUDE_SESSION_ID: sessionId
				},
				stdio: ["pipe", "pipe", "pipe"],
				timeout: timeoutMs
			});
			let stderr = "";
			let stdout = "";
			child.stderr.setEncoding("utf-8");
			child.stderr.on("data", (c) => { stderr = (stderr + c).slice(-4000); });
			child.stdout.setEncoding("utf-8");
			child.stdout.on("data", (c) => { stdout = (stdout + c).slice(-8192); });
			child.on("error", (err) => {
				if (err && err.code === "ENOENT" && pyIdx + 1 < PY_CANDIDATES.length) {
					runGuardHook(scriptPath, hookArgs, payload, cwd, sessionId, timeoutMs, pyIdx + 1)
						.then(resolve);
				} else {
					done(0, `regress-guard(native): spawn ${PY_CANDIDATES[pyIdx]} 失败（fail-open 适配层）`);
				}
			});
			child.on("close", (code) => done(code, stderr, stdout));
			child.stdin.write(JSON.stringify(payload));
			child.stdin.end();
		} catch {
			done(0, "regress-guard(native): 钩子调度异常（fail-open 适配层）");
		}
	});
}

export function apply(ctx, config) {
	const G = config.guardRoot.replace(/^~/, os.homedir());
	const hook = (rel) => path.join(G, rel);
	const T = config.timeoutMs;

	// 批205（公网 issue#3）：命令面——16 个 /regress-* 经 ctx.commands.register
	// 入 dsh 斜杠菜单，执行=md 正文展开为 UserMessage 经 agent.followup 注入
	// （ZCode slash command 语义平移，单一事实源 commands/*.md）。commands
	// 服务运行时注入：老宿主无此服务→警告一次，钩子面不受牵连。
	const commandsDir = (config.commandsDir && config.commandsDir.replace(/^~/, os.homedir()))
		|| path.join(path.dirname(G), "commands");
	let registrar = null;
	ctx.inject(["commands"], (cmdCtx) => {
		// fail-soft：命令面装载失败（服务时序/竞态）不牵连钩子面
		try {
			registrar = createCommandRegistrar(cmdCtx, commandsDir, ctx.logger);
			const added = registrar.reconcile();
			ctx.logger?.info?.("regress-guard(native/commands): armed "
				+ `${registrar.registered.size} command(s) from ${commandsDir}`
				+ (added.length ? "" : " (no new this pass)"));
		} catch (err) {
			ctx.logger?.warn?.(`regress-guard(native/commands): 注册失败（钩子面不受影响）——${err}`);
		}
	});

	const sessionCwd = async (agent) => {
		try { return await ctx.workingDirectory.ensure(agent); }
		catch { return agent?.session?.header?.cwd; }
	};
	const sessionId = (agent) => agent?.session?.header?.id ?? "";

	/** 顺序跑一组钩子，exit 2 → {kind:'deny'}，其余放行。 */
	const chain = async (steps, payloadBase, agent) => {
		const cwd = await sessionCwd(agent);
		if (!cwd) return undefined;
		const sid = sessionId(agent);
		for (const [script, args] of steps) {
			const r = await runGuardHook(script, args, { ...payloadBase, session_id: sid }, cwd, sid, T);
			if (r.code === 2) {
				return { kind: "deny", reason: r.stderr || "regress-guard: 阻断（详见钩子输出）" };
			}
		}
		return undefined;
	};

	ctx.on("tools/pre-execute", async (exec, next) => {
		const args = materializeArguments(exec.arguments);
		// 批171：三守卫（boundary/valve/rbe）以 tool_name 为门控——缺它=整链 no-op
		const base = { tool_name: canonicalToolName(exec.name), tool_input: args ?? {} };
		let steps = null;
		if (BASH_TOOLS.has(exec.name)) {
			// 原生层直跑门禁本体（launcher.js 是 ZCode 侧的 python 探测+env
			// 白名单垫片——原生适配层自控解释器与 env，垫片无需过境）
			steps = [
				[hook("pre_commit_guard.py"), []],
				[hook("boundary_guard.py"), []],
				[hook("execution_valve.py"), []]
			];
		} else if (EDIT_TOOLS.has(exec.name)) {
			steps = [
				[hook("read_before_edit_guard.py"), ["pre"]],
				[hook("boundary_guard.py"), []]
			];
		}
		if (steps) {
			const deny = await chain(steps, base, exec.agent);
			if (deny) return deny;
		}
		return next();
	}, { global: true });

	ctx.on("tools/post-execute", async (exec, result, next) => {
		const args = materializeArguments(exec.arguments);
		const cwd = await sessionCwd(exec.agent);
		if (!cwd) return next();
		const sid = sessionId(exec.agent);
		// 批171：rbe post 按 tool_name 分支——payload 同样补 canonicalized 名
		const name = canonicalToolName(exec.name);
		const response = blocksToText(result?.content);
		const run = (script, argv, payload) =>
			runGuardHook(script, argv, { ...payload, session_id: sid }, cwd, sid, T);
		if (READ_TOOLS.has(exec.name)) {
			await run(hook("read_before_edit_guard.py"), ["post"],
				{ tool_name: name, tool_input: args ?? {} });
		} else if (BASH_TOOLS.has(exec.name) || EDIT_TOOLS.has(exec.name)) {
			await run(hook("risk_watch.py"), [],
				{ tool_name: name, tool_input: args ?? {}, tool_response: response });
			if (resultFailed(result)) {
				await run(hook("fail_watch.py"), [],
					{ tool_name: name, tool_input: args ?? {}, tool_response: response });
			}
		}
		return next();
	}, { global: true });

	ctx.on("agent/session-start", async ({ agent, source }) => {
		// 批205：会话启动对账注册——运行中安装/升级的命令免重启 dsh 即入菜单
		// （fail-soft：对账失败不阻塞 self_heal/compact_notice 主链）
		let added = [];
		try {
			added = registrar?.reconcile() ?? [];
		} catch (err) {
			ctx.logger?.warn?.(`regress-guard(native/commands): 对账失败——${err}`);
		}
		if (added.length) {
			ctx.logger?.info?.("regress-guard(native/commands): +" + added.length
				+ " on session-start (" + added.join(", ") + ")");
		}
		const cwd = await sessionCwd(agent);
		if (!cwd) return;
		const sid = sessionId(agent);
		if (source === "startup" || source === "resume") {
			await runGuardHook(hook("lib/self_heal.py"), [], { source }, cwd, sid, Math.min(T, 30000));
		} else if (source === "compact") {
			await runGuardHook(hook("compact_notice.py"), [], { source }, cwd, sid, Math.min(T, 30000));
		}
	}, { global: true });

	ctx.on("agent/pre-step", async (data, next) => {
		const agent = data?.agent;
		const cwd = await sessionCwd(agent);
		if (!cwd) return next();
		const sid = sessionId(agent);
		const prompt = (data?.messages ?? [])
			.filter((m) => m?.role === "user")
			.map((m) => Array.isArray(m.content)
				? blocksToText(m.content)
				: String(m.content ?? ""))
			.filter(Boolean).pop() ?? "";
		if (!prompt) return next();
		// 批170（计划模式平替接线）：prompt_intercept 的 stdout 是
		// {"additionalContext": "..."}（ZCode 宿主读它注入）——原生层此前把它
		// 丢弃=提醒永远到不了 dsh agent。现捕获并前置注入下游决策的
		// additionalContexts（含 3.5 计划性需求档：先立清单等批准）。
		const r = await runGuardHook(hook("prompt_intercept.py"), [],
			{ prompt }, cwd, sid, Math.min(T, 30000));
		const down = await next();
		let extra;
		try {
			const out = JSON.parse(r.stdout || "{}");
			if (typeof out.additionalContext === "string" && out.additionalContext.trim()) {
				extra = {
					role: "user",
					content: [{ type: "text", text: out.additionalContext }]
				};
			}
		} catch { /* 非 JSON 输出不注入 */ }
		if (!extra) return down;
		return { ...down, additionalContexts: [extra, ...(down.additionalContexts ?? [])] };
	}, { global: true });

	ctx.on("agent/turn-stopping", async ({ agent, signal }) => {
		const cwd = await sessionCwd(agent);
		if (!cwd) return;
		const sid = sessionId(agent);
		const r = await runGuardHook(hook("reflection_check.py"), [],
			{ stop_hook_active: false }, cwd, sid, Math.min(T, 120000));
		if (r.code === 2 && r.stderr && agent?.steer) {
			// 批205：消息形状收口——裸 {role,content} 缺 source，agent-loop 的
			// step 读 message.source.kind 会 TypeError 炸 turn 静默丢消息
			agent.steer(userTextMessage(r.stderr));
		} else {
			await runGuardHook(hook("stop_notify.py"), [], {}, cwd, sid, Math.min(T, 30000));
		}
	}, { global: true });

	// 批 N（诊断增强）：文件 boot 标记——apply() 跑过必落盘（诊断 boot-past
	// 静默跳过；ctx.logger 去向不一定可见，文件标记是硬证据）
	try {
		fs.appendFileSync(path.join(os.homedir(), ".dsh", "regress-guard-armed.log"),
			`${new Date().toISOString()} pid=${process.pid} guardRoot=${G}\n`);
	} catch { /* 标记失败不阻断钩子面 */ }

	ctx.logger?.info?.("regress-guard(native): interception armed "
		+ `(guardRoot=${G})`);
}
