"""launcher.js cleanEnv 拒列式 env 政策钉（批215，公网 issue#4；前身：REGRESS-2026-078 白名单钉）。

观测路径：node 子进程 require launcher.js（module.exports 导出 cleanEnv/ENV_DENY_PREFIXES，
require.main 守卫保证被 require 时不 spawn 守卫——test_require_does_not_spawn 钉此
合同），对子进程**真实 process.env** 应用 cleanEnv 后 JSON 回传。子进程 env 由
pytest 完全构造，因此钉的正是生产调用形态 cleanEnv(process.env)（launcher.js
tryPython 内）的输入→输出行为，不钉内部实现细节。

政策（批215 反转）：白名单 19 项 → 拒列式——白名单把工具链管理器变量一并裁掉
（JAVA_HOME/MISE_*），Windows 上 mise/asdf 管 JDK 的项目 mvn 起不来→测试没跑
被记 fail→提交 100% 误拦（issue#4 外部用户实证）。拒列族=v1.69 已拒的覆盖类
（RG_*/REGRESS_*/WECOM_*/GIT_*）+ 批191 防投毒（PYTHON* 剥离+强制 PYTHONUTF8）
+ 云凭据族（AWS_* 等：旧白名单顺带剥离的性质升格为显式合同——守卫与测试
进程不该拿到宿主云凭据）；其余宿主变量（含旧 19 项，无一命中拒列前缀）放行。

钉死面（拒列改坏任一方向都红）：
- 放行面回退：test_legacy_contract_vars_pass（旧 19 项）+ test_toolchain_vars_pass 红
- 拒列失效：test_override_injection_denied / test_credential_families_denied 红
- 政策本身即合同：test_deny_list_pinned_exact（增删拒列前缀都红——合同变更须过此钉）
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

LAUNCHER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "scripts", "launcher.js"))
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH，无法观测 launcher.js")

# 旧白名单 19 项（v1.69 契约面）——拒列化后全数保留（向后兼容钉）
LEGACY_KEEP = (
    "ALL_PROXY", "CLAUDE_PROJECT_DIR", "CLAUDE_SESSION_ID", "HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "LANG", "LC_ALL", "LC_CTYPE", "NO_PROXY",
    "PATH", "SYSTEMROOT", "TERM", "TMPDIR", "TZ", "ZCODE_HOME",
    "ZCODE_PLUGIN_ROOT", "ZCODE_PROJECT_DIR", "ZCODE_SESSION_ID",
)

# 工具链管理器样本（issue#4 病灶族：mise/asdf/nvm/sdkman + JAVA_HOME）
TOOLCHAIN = (
    "JAVA_HOME", "JAVA_TOOL_OPTIONS", "MISE_DATA_DIR", "MISE_CONFIG_DIR",
    "MISE_CACHE_DIR", "MISE_STATE_DIR", "ASDF_DIR", "NVM_DIR",
    "SDKMAN_DIR", "GOROOT", "GRADLE_USER_HOME",
)

# 拒列合同（按实现冻结，增删都红——这就是安全合同本身）。
# 注：NODE_*/ELECTRON_* 是 dsh 适配层（index.js childEnv）的卫生拒列族——
# launcher 侧子进程纯 python 无此面，且 NODE_OPTIONS 会先毒到 node 探针
# 自身（观测者悖论标本），故不在此列。
EXPECTED_DENY = [
    "AWS_", "AZURE_", "DOCKER_", "GH_", "GIT_", "GITHUB_", "GITLAB_",
    "GOOGLE_", "NPM_TOKEN", "PYTHON", "RG_", "REGRESS_",
    "WECOM_",
]

_POISON_OVERRIDE = {
    "RG_ATTACK": "1",
    "RG_BYPASS_UNTIL": "2099-01-01T00:00:00",
    "RG_TRUSTED_PROJECTS": "/tmp/evil",
    "RG_MACHINE_NOTIFY": "/tmp/evil.json",
    "REGRESS_VALVE": "off",
    "WECOM_API_BASE": "https://evil.example",
    "GIT_DIR": "/tmp/fake.git",
    "GIT_INDEX_FILE": "/tmp/poison",
    "PYTHONSTARTUP": "/tmp/evil.py",
    "PYTHONPATH": "/tmp/evil",
}

_POISON_CREDS = {
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AZURE_CLIENT_SECRET": "s3cret",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/evil.json",
    "GITHUB_TOKEN": "ghp_evil",
    "GH_TOKEN": "ghp_evil2",
    "GITLAB_TOKEN": "glpat-evIL",
    "NPM_TOKEN": "npm-evIL",
    "DOCKER_HUB_TOKEN": "dck_evil",
}

_PROBE_CLEAN_ENV = (
    "const { cleanEnv } = require(process.argv[1]);"
    "console.log(JSON.stringify(cleanEnv(process.env)));"
)
_PROBE_DENY_LIST = (
    "const m = require(process.argv[1]);"
    "console.log(JSON.stringify(m.ENV_DENY_PREFIXES.slice().sort()));"
)


def _probe(script, env):
    try:
        r = subprocess.run(
            [NODE, "-e", script, LAUNCHER], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=env)
    except subprocess.TimeoutExpired:
        pytest.fail("node 探针超时：launcher.js 可能阻死")
    if r.returncode != 0:
        pytest.fail(f"node 探针退出码 {r.returncode}\nstderr: {r.stderr[:500]}")
    return json.loads(r.stdout)


def _clean(env_dict):
    """以 env_dict 为子进程真实 env，观测 cleanEnv(process.env) 的输出。"""
    return _probe(_PROBE_CLEAN_ENV, env_dict)


# ---------- ① 放行面（向后兼容 + 工具链） ----------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_legacy_contract_vars_pass():
    """①旧白名单 19 项全数保留（拒列化向后兼容钉）+ 毒变量同 env 剥离
    + PYTHONUTF8 强制注入（批215 起 cleanEnv 与 scrubbedEnv 对齐）。"""
    env = {var: f"keep-{var.lower()}" for var in LEGACY_KEEP}
    out = _clean({**env, **_POISON_OVERRIDE})
    assert out == {**env, "PYTHONUTF8": "1"}


@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_toolchain_vars_pass():
    """①工具链管理器变量放行（issue#4 病灶族：JAVA_HOME/MISE_*/ASDF_*/NVM_*…）。"""
    env = {var: f"tc-{var.lower()}" for var in TOOLCHAIN}
    out = _clean({**env, **_POISON_OVERRIDE})
    assert out == {**env, "PYTHONUTF8": "1"}


# ---------- ② 拒列族 ----------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_override_injection_denied():
    """②覆盖类/投毒类全剥离：RG_*/REGRESS_*/WECOM_*/GIT_*/PYTHON*（除强制
    PYTHONUTF8）/NODE_*——纯毒 env 输出恰为 {"PYTHONUTF8": "1"}。"""
    out = _clean(dict(_POISON_OVERRIDE))
    assert out == {"PYTHONUTF8": "1"}


@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_credential_families_denied():
    """②云凭据族剥离（旧白名单顺带剥离的性质升格为显式合同——守卫与测试
    进程不该拿到宿主云凭据）。"""
    out = _clean(dict(_POISON_CREDS))
    assert out == {"PYTHONUTF8": "1"}


@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_custom_vars_pass_by_default():
    """②政策反转钉：非拒列族的自定义变量默认放行（白名单时代恒剥，拒列
    时代放行——这是本批的政策变更本体）。"""
    out = _clean({"MY_CUSTOM_VAR": "custom"})
    assert out == {"MY_CUSTOM_VAR": "custom", "PYTHONUTF8": "1"}


# ---------- ③ 大小写归一（比较归一，保留原键名） ----------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="node 探针需精确 env；windows 下 node.exe 无 "
                           "SYSTEMROOT 不启动（同语义 test_launcher_dispatch 覆盖）")
def test_case_normalized_comparison_keeps_original_key():
    """③小写/混合形态：比较大写归一命中拒列，输出保留放行变量的原键名。"""
    out = _clean({"path": "/lower", "zcode_session_id": "s-lower",
                  "http_proxy": "p-lower",
                  "rg_attack": "1", "aws_secret_access_key": "k",
                  "java_home": "/jdk"})
    assert out == {"path": "/lower", "zcode_session_id": "s-lower",
                   "http_proxy": "p-lower", "java_home": "/jdk",
                   "PYTHONUTF8": "1"}


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows env 键大小写不区分，三形态共存仅 POSIX 可观测")
def test_path_and_PATH_coexist():
    """③path= 与 PATH= 双形态：各自独立判定、各自原样保留（归一只用于比较，不改名不合并）。"""
    out = _clean({"path": "/lower", "Path": "/mixed", "PATH": "/upper"})
    assert out == {"path": "/lower", "Path": "/mixed", "PATH": "/upper",
                   "PYTHONUTF8": "1"}


# ---------- 拒列合同本体 ----------

def test_deny_list_pinned_exact():
    """ENV_DENY_PREFIXES 全集双向钉——增删拒列前缀都红（合同变更必须过此钉，
    白名单时代的 test_whitelist_exact_set 等价物）。"""
    assert _probe(_PROBE_DENY_LIST, dict(os.environ)) == sorted(EXPECTED_DENY)


# ---------- 导出面合同 ----------

def test_require_does_not_spawn():
    """require launcher.js 不启动守卫（require.main 守卫）——本测试族观测路径的安全前提。"""
    r = subprocess.run(
        [NODE, "-e", f"require({json.dumps(LAUNCHER)}); console.log('LOADED_OK')"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert r.returncode == 0
    assert "LOADED_OK" in r.stdout
    assert "REGRESS-GUARD" not in r.stderr


# ─── 批135：信号击穿 fail-closed ────────────────────────────

@pytest.mark.skipif(sys.platform == "win32",
                    reason="win32: pgrep+SIGKILL 信号语义无对应物")
def test_signal_killed_child_exits_2(tmp_path):
    """子进程被信号击杀（code=null）→ launcher 必须以 2 退出（fail-closed）。

    旧行为 code ?? 1 → exit 1 → 宿主按「非阻断错误」放行 = 门禁在崩溃瞬间
    失守。构造：guard 阻塞读 stdin（管道不关），外层 kill -9 子进程。"""
    mk = tmp_path / "mk"
    mk.write_text(
        'import subprocess, sys, os, signal, time, json\n'
        'p = subprocess.Popen(["node", sys.argv[1]],\n'
        '                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,\n'
        '                     stderr=subprocess.PIPE)\n'
        'time.sleep(0.8)  # 等 launcher 完成解释器探测并 spawn guard\n'
        '# 找到 guard 孙进程（python3 pre_commit_guard.py）杀之\n'
        'out = subprocess.run(["pgrep", "-P", str(p.pid), "-f", "pre_commit_guard"],\n'
        '                     capture_output=True, text=True, encoding="utf-8", errors="replace")\n'
        'kids = out.stdout.split()\n'
        'if not kids:\n'
        '    print("NO_GRANDCHILD", file=sys.stderr); sys.exit(97)\n'
        'os.kill(int(kids[0]), signal.SIGKILL)\n'
        'rc = p.wait()\n'
        'print(rc)\n', encoding="utf-8")
    proc = subprocess.run([sys.executable, str(mk), LAUNCHER],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert "NO_GRANDCHILD" not in proc.stderr, proc.stderr
    assert proc.stdout.strip() == "2", f"信号击穿应 exit 2，得 {proc.stdout!r}"


def test_launcher_uncaught_exception_exits_2():
    """launcher 自身未捕获异常 → exit 2（uncaughtException 兜底）。"""
    proc = subprocess.run(
        ["node", "-e",
         f'process.on("uncaughtException", function() {{ process.exit(2); }});'
         f'require({json.dumps(LAUNCHER)});'
         'setTimeout(function() { throw new Error("boom"); }, 50);'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    assert proc.returncode == 2
