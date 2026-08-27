#!/usr/bin/env node
/**
 * launcher.js — 跨平台 hook 启动器。
 *
 * ZCode 的 process hook command 固定为一个可执行文件名。
 * Windows 上 python3 不存在（通常是 python 或 py），所以用 Node（ZCode 必有）
 * 作为入口，由它找到正确的 Python 解释器并转发。
 *
 * hook.json 配置：
 *   { "type": "process", "command": "node", "args": ["${ZCODE_PLUGIN_ROOT}/hooks/scripts/launcher.js"] }
 */
const { spawn } = require("child_process");
const path = require("path");

const guardPy = path.join(__dirname, "pre_commit_guard.py");

// 候选 Python 解释器（按优先级）
const candidates = ["python3", "python", "py"];

function tryPython(idx) {
  if (idx >= candidates.length) {
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

  const py = candidates[idx];
  const child = spawn(py, [guardPy], {
    stdio: ["inherit", "inherit", "inherit"],
    env: { ...process.env },
  });

  child.on("error", (err) => {
    if (err.code === "ENOENT") {
      // 这个解释器不存在，试下一个
      tryPython(idx + 1);
    } else {
      console.error(`REGRESS-GUARD: ❌ 启动 ${py} 失败: ${err.message}`);
      console.error("  这通常是权限问题。尝试: chmod +x " + guardPy);
      process.exit(2);
    }
  });

  child.on("exit", (code) => {
    process.exit(code ?? 1);
  });
}

tryPython(0);
