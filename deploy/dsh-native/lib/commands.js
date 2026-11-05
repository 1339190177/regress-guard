/**
 * dsh-regress-guard 命令面（批205，公网 issue#3 根治层）。
 *
 * 病根：install.py 把 16 个 /regress-* 命令装到 ~/.zcode/commands/——ZCode
 * 扫描该目录，dsh 不扫（dsh 指令面只有 skill 与 ctx.commands.register）。
 * 命令在 dsh 里是"死文件"：安装器报 ✅、斜杠菜单不出现、输入 /regress-*
 * 被当普通文本。批166/169 只适配了拦截面（钩子），入口面（命令）缺位。
 *
 * 本模块把命令面接到 dsh 原生命令注册表，语义与 ZCode 对齐：
 *  - 注册：ctx.commands.register（全局生效、描述不进系统提示=零 token、
 *    斜杠菜单确定性解析）——name/description 取自命令 md 的 frontmatter，
 *    单一事实源仍是 commands/*.md（本层零复制流程逻辑）；
 *  - 执行：handler 把 md 正文（$ARGUMENTS → rawInput）构造成宿主契约的
 *    UserMessage 经 agent.followup 注入为新回合——ZCode slash command 的
 *    dsh 平移（命令展开为用户回合交给模型，AI 类流程全量可用）。
 *
 * 为什么 followup 能用（issue 作者以为 handler 不能给模型发消息）：
 * commands.execute 的"不发给模型"说的是宿主不自动把命令行变成消息；
 * handler 自己拿 invocation.agent 走 inbox 是正门——dsh-acp 同款
 * （createUserMessage + agent.followup，宿主运行时实证）。
 *
 * 消息形状纪律：agent-loop 的 step 读 message.source.kind，裸
 * {role, content} 会 TypeError 炸 turn 静默丢消息——id/role/content/source
 * 四件套必齐（userTextMessage 单点铸造，steer 老调用点同修）。
 *
 * 本文件刻意零外部依赖（无 schemastery）：pytest 探针可直载行为测。
 */
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/** 命令名合法域（宿主契约：小写字母/数字/_/-，不带斜杠）。 */
const NAME_RE = /^[a-z0-9][a-z0-9_-]*$/;

/** 本插件管辖域：~/.zcode/commands/ 里同住的外来命令（handoff 等）不碰。 */
function isRegressCommandFile(fileName) {
	return fileName.startsWith("regress-") && fileName.endsWith(".md");
}

/** 解析 md frontmatter 的单行键值（description / argument-hint——仓契约）。 */
export function parseFrontmatter(text) {
	const out = {};
	const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
	if (!m) return out;
	for (const line of m[1].split(/\r?\n/)) {
		const kv = /^([A-Za-z-]+):\s*(.*)$/.exec(line);
		if (!kv) continue;
		const val = kv[2].trim().replace(/^["']|["']$/g, "");
		if (kv[1].toLowerCase() === "description") out.description = val;
		if (kv[1].toLowerCase() === "argument-hint") out.argumentHint = val;
	}
	return out;
}

/** 剥掉 frontmatter 块（元数据不进模型回合，正文才是命令体）。 */
export function stripFrontmatter(text) {
	const m = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/.exec(text);
	return m ? text.slice(m[0].length) : text;
}

/** $ARGUMENTS 展开（ZCode slash command 语义：全文替换，空参数=空串）。 */
export function expandCommand(body, rawInput) {
	return body.split("$ARGUMENTS").join(rawInput);
}

/** 铸宿主契约 UserMessage（id+source 必带——见文件头"消息形状纪律"）。 */
export function userTextMessage(text) {
	return Object.freeze({
		id: randomUUID(),
		role: "user",
		content: Object.freeze([{ type: "text", text }]),
		source: Object.freeze({ kind: "user" })
	});
}

/** description 兜底：首个一级标题去命令名前缀（"/regress-x — 描述"→"描述"）。 */
function headingFallback(body, name) {
	const m = /^#\s+(.+)$/m.exec(body);
	if (!m) return "";
	return m[1].replace(new RegExp("^/?" + name + "\\s*[—-]?\\s*"), "").trim();
}

/** 读命令文档并执行一次注入：fresh 读盘（注册后 install.py 更新即生效）。
 *
 * 失败语义：文档缺失→error+修复指引（重跑 install.py）；宿主 Agent 面
 * 无 followup/steer→error（老宿主明确报因，不静默）。 */
function invokeCommand(invocation, commandsDir, name) {
	const file = path.join(commandsDir, name + ".md");
	let md;
	try {
		md = fs.readFileSync(file, "utf8");
	} catch {
		return { kind: "error", text: `regress-guard: 命令文档缺失（${file}）——请重跑 python install.py 刷新命令面` };
	}
	const rawInput = typeof invocation?.rawInput === "string" ? invocation.rawInput : "";
	const body = expandCommand(stripFrontmatter(md), rawInput).trim();
	const agent = invocation?.agent;
	if (typeof agent?.followup === "function") {
		agent.followup(userTextMessage(body));
	} else if (typeof agent?.steer === "function") {
		agent.steer(userTextMessage(body)); // 老宿主兜底：idle steer 同样开 turn
	} else {
		return { kind: "error", text: "regress-guard: 宿主 Agent 面缺少 followup/steer——命令无法注入模型回合" };
	}
	const arg = rawInput.trim();
	return { kind: "success", text: `/${name} 已交给模型执行${arg ? `（参数：${arg}）` : ""}` };
}

/**
 * 建命令注册器（幂等可对账）。
 *
 * reconcile() 扫 commandsDir 补注新出现的 regress-*.md——已在册的跳过
 * （宿主对同名重复注册会 throw）。dsh 会话生命周期内 install.py 新装
 * 的命令在下一个 session-start 对账后无需重启 dsh 即入斜杠菜单。
 *
 * fail-soft：宿主无 commands 服务（老版本桌面）→ 警告一次并静默返回，
 * 钩子面不受牵连（拦截链是治理主体，命令面是入口增强）。
 */
export function createCommandRegistrar(ctx, commandsDir, logger) {
	const registered = new Map(); // name -> disposer
	let warned = false;
	const warn = (msg) => {
		if (warned) return;
		warned = true;
		(logger?.warn ?? console.warn)?.(`regress-guard(native/commands): ${msg}`);
	};
	function reconcile() {
		if (!ctx?.commands || typeof ctx.commands.register !== "function") {
			warn("宿主无 commands 服务（老 dsh？）——命令面不注册，钩子面不受影响");
			return [];
		}
		let files;
		try {
			files = fs.readdirSync(commandsDir);
		} catch {
			warn(`命令目录不可读（${commandsDir}）——先跑 python install.py`);
			return [];
		}
		const added = [];
		for (const f of files.sort()) {
			if (!isRegressCommandFile(f)) continue;
			const name = f.slice(0, -3);
			if (!NAME_RE.test(name)) {
				warn(`跳过非法命令名：${f}`);
				continue;
			}
			if (registered.has(name)) continue;
			let md = "";
			try {
				md = fs.readFileSync(path.join(commandsDir, f), "utf8");
			} catch { /* 读失败按空文档注册，调用时再给修复指引 */ }
			const fm = parseFrontmatter(md);
			const body = stripFrontmatter(md);
			const definition = {
				name,
				description: fm.description || headingFallback(body, name) || name,
				handler: (invocation) => invokeCommand(invocation, commandsDir, name)
			};
			if (fm.argumentHint) definition.input = { hint: fm.argumentHint };
			const dispose = ctx.commands.register(definition);
			registered.set(name, typeof dispose === "function" ? dispose : () => {});
			added.push(name);
		}
		return added;
	}
	return { reconcile, registered };
}
