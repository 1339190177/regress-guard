#!/usr/bin/env node
/**
 * launcher.js — 跨平台 hook 启动器（批191 泛化：全钩子统一入口）。
 *
 * ZCode 的 hook command 串在 Windows 宿主下走 cmd 语义，python3 不存在
 * （通常是 python 或 py），所以用 Node（ZCode 必有）作为入口，由它找到
 * 正确的 Python 解释器并转发。
 *
 * 用法（批191 起全部钩子走此形态）：
 *   node launcher.js <script.py> [args...]
 * 无参默认 pre_commit_guard.py（向后兼容既有已装配置与 dsh 桥）。
 *
 * hook.json 配置形态：
 *   { "type": "command",
 *     "command": "node \"${ZCODE_PLUGIN_ROOT}/hooks/scripts/launcher.js\" boundary_guard.py" }
 *
 * 布局自愈：目标脚本按三种部署布局解析——源码态（__dirname/<script>）、
 * 摊平态（install 轨把脚本拷到已装根）、self_heal 特例（lib/ 子目录）。
 * 依次尝试 __dirname/<script> → __dirname/lib/<script>，绝对路径直用。
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const DEFAULT_GUARD = "pre_commit_guard.py";
// 白名单策略只对提交门禁生效（历史契约，ENV_KEEP 注释见下）
const WHITELIST_TARGET = "pre_commit_guard.py";

// 候选 Python 解释器（按优先级）
const candidates = ["python3", "python", "py"];

// env 白名单（v1.69，run4 R1）：门禁入口构造洁净环境——RG_*/WECOM_*/GIT_* 等
// 覆盖类变量不透传给守卫子进程（env 缝隙族的入口层根治：宿主进程 env 里任何
// 对守卫行为/信任判定/git 读数的注入在此失效）。键按大写归一比较（Windows 不区分）。
const ENV_KEEP = new Set([
  // 系统基础：找解释器/git、编码、临时区、Windows python 依赖
  "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "TMPDIR", "SYSTEMROOT",
  // 代理（通知外发走系统代理语义）
  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
  // 宿主契约变量（ZCode 注入的会话/项目/插件根——守卫合法依赖）
  "ZCODE_SESSION_ID", "CLAUDE_SESSION_ID",
  "ZCODE_PROJECT_DIR", "CLAUDE_PROJECT_DIR",
  "ZCODE_HOME", "ZCODE_PLUGIN_ROOT",
]);

function cleanEnv(env) {
  const out = {};
  for (const k of Object.keys(env)) {
    if (ENV_KEEP.has(k) || ENV_KEEP.has(k.toUpperCase())) out[k] = env[k];
  }
  return out;
}

/**
 * 非门禁脚本的 env 策略：全量透传但清洗 PYTHON* 键——严格等价原
 * `python3 -E` 的防投毒语义（PYTHONPATH/PYTHONHOME 注入失效），另注入
 * PYTHONUTF8=1（批191：中文 Windows cp936 下 emoji/中文 IO 的根治）。
 */
function scrubbedEnv(env) {
  const out = {};
  for (const k of Object.keys(env)) {
    if (/^PYTHON/i.test(k)) continue;
    out[k] = env[k];
  }
  out.PYTHONUTF8 = "1";
  return out;
}

/**
 * 解析目标脚本路径（布局自愈）：绝对路径直用；相对名依次尝试
 * __dirname/<s>（源码态/摊平态）→ __dirname/lib/<s>（self_heal 特例）。
 * 都不存在时返回首个候选（由子进程报错，保持可诊断性）。
 */
function resolveTarget(script) {
  if (path.isAbsolute(script)) return script;
  const primary = path.join(__dirname, script);
  if (fs.existsSync(primary)) return primary;
  const inLib = path.join(__dirname, "lib", script);
  if (fs.existsSync(inLib)) return inLib;
  return primary;
}

function envFor(target) {
  return path.basename(target) === WHITELIST_TARGET
    ? cleanEnv(process.env)
    : scrubbedEnv(process.env);
}

module.exports = { cleanEnv, scrubbedEnv, resolveTarget, envFor, ENV_KEEP };

function failNoPython() {
  console.error("REGRESS-GUARD: ❌ 找不到 Python 3 解释器。");
  console.error("  尝试过: " + candidates.join(", "));
  console.error("");
  console.error("  解决方法：");
  console.error("    Windows: 从 https://python.org 安装，勾选 'Add to PATH'");
  console.error("    macOS:   brew install python3");
  console.error("    Linux:   sudo apt install python3 / sudo yum install python3");
  console.error("");
  console.error("  安装后重启 ZCode 再试。");
  console.error("  如需临时跳过：.regress/config.json 设 \"strict\": false");
  process.exit(2);
}

function tryPython(idx, target, extraArgs) {
  if (idx >= candidates.length) failNoPython();

  const py = candidates[idx];
  const child = spawn(py, [target, ...extraArgs], {
    stdio: ["inherit", "inherit", "inherit"],
    env: envFor(target),
  });

  child.on("error", (err) => {
    if (err.code === "ENOENT") {
      // 这个解释器不存在，试下一个
      tryPython(idx + 1, target, extraArgs);
    } else {
      console.error(`REGRESS-GUARD: ❌ 启动 ${py} 失败: ${err.message}`);
      console.error("  这通常是权限问题。尝试: chmod +x " + target);
      process.exit(2);
    }
  });

  child.on("exit", (code) => {
    // 批135 fail-closed：信号击杀（code=null，如 OOM/外部 kill）从 1 改 2——
    // 非 2 会被宿主当「非阻断错误」放行，门禁在崩溃瞬间不应失守
    process.exit(code ?? 2);
  });
}

// launcher 自身未捕获异常 → fail-closed（批135）
process.on("uncaughtException", (err) => {
  console.error("REGRESS-GUARD: ❌ launcher 内部异常（fail-closed）: "
    + (err && err.message));
  process.exit(2);
});

// 直接运行才启动；被 require（测试）时只导出纯函数，不 spawn
if (require.main === module) {
  const argv = process.argv.slice(2);
  const script = argv.length > 0 ? argv[0] : DEFAULT_GUARD;
  const target = resolveTarget(script);
  tryPython(0, target, argv.slice(1));
}
