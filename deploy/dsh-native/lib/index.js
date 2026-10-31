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
import z from "@deepseek-ai/schemastery";

export const name = "regress-guard";

export const inject = ["workingDirectory"];

export const Config = z.object({
	guardRoot: z.string().default(path.join(os.homedir(), ".zcode", "regress-guard-hooks")),
	timeoutMs: z.number().default(600000)
});

const BASH_TOOLS = new Set(["bash", "Bash", "pwsh"]);
const EDIT_TOOLS = new Set(["edit", "Edit", "write", "Write", "ApplyPatch"]);
const READ_TOOLS = new Set(["read", "Read"]);

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

/** 进程内跑一个 guard 钩子：真实 fs 视图 + 正确 cwd/env，stdin=CC 形态 payload。 */
function runGuardHook(scriptPath, hookArgs, payload, cwd, sessionId, timeoutMs) {
	return new Promise((resolve) => {
		let settled = false;
		const done = (code, stderr, stdout) => {
			if (!settled) {
				settled = true;
				resolve({ code: code ?? 0, stderr: stderr ?? "", stdout: stdout ?? "" });
			}
		};
		try {
			const child = spawn("python3", ["-E", scriptPath, ...hookArgs], {
				cwd,
				env: {
					PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
					HOME: process.env.HOME ?? os.homedir(),
					LANG: process.env.LANG ?? "C.UTF-8",
					TZ: process.env.TZ,
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
			child.on("error", () => done(0, "regress-guard(native): spawn python3 失败（fail-open 适配层）"));
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
		const base = { tool_input: args ?? {} };
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
	});

	ctx.on("tools/post-execute", async (exec, result, next) => {
		const args = materializeArguments(exec.arguments);
		const cwd = await sessionCwd(exec.agent);
		if (!cwd) return next();
		const sid = sessionId(exec.agent);
		const response = blocksToText(result?.content);
		const run = (script, argv, payload) =>
			runGuardHook(script, argv, { ...payload, session_id: sid }, cwd, sid, T);
		if (READ_TOOLS.has(exec.name)) {
			await run(hook("read_before_edit_guard.py"), ["post"], { tool_input: args ?? {} });
		} else if (BASH_TOOLS.has(exec.name) || EDIT_TOOLS.has(exec.name)) {
			await run(hook("risk_watch.py"), [], { tool_input: args ?? {}, tool_response: response });
			if (resultFailed(result)) {
				await run(hook("fail_watch.py"), [], { tool_input: args ?? {}, tool_response: response });
			}
		}
		return next();
	});

	ctx.on("agent/session-start", async ({ agent, source }) => {
		const cwd = await sessionCwd(agent);
		if (!cwd) return;
		const sid = sessionId(agent);
		if (source === "startup" || source === "resume") {
			await runGuardHook(hook("lib/self_heal.py"), [], { source }, cwd, sid, Math.min(T, 30000));
		} else if (source === "compact") {
			await runGuardHook(hook("compact_notice.py"), [], { source }, cwd, sid, Math.min(T, 30000));
		}
	});

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
	});

	ctx.on("agent/turn-stopping", async ({ agent, signal }) => {
		const cwd = await sessionCwd(agent);
		if (!cwd) return;
		const sid = sessionId(agent);
		const r = await runGuardHook(hook("reflection_check.py"), [],
			{ stop_hook_active: false }, cwd, sid, Math.min(T, 120000));
		if (r.code === 2 && r.stderr && agent?.steer) {
			agent.steer({ role: "user", content: [{ type: "text", text: r.stderr }] });
		} else {
			await runGuardHook(hook("stop_notify.py"), [], {}, cwd, sid, Math.min(T, 30000));
		}
	});

	ctx.logger?.info?.("regress-guard(native): interception armed "
		+ `(guardRoot=${G})`);
}
