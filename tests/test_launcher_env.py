"""launcher env 白名单（v1.69，058）：钩子入口洁净环境合同。

RG_*/WECOM_*/GIT_* 覆盖类变量不得透传给守卫子进程——env 缝隙族的入口层
根治（057 封了信任解析的 env 影响，本批封宿主进程 env 的注入通道本身）。"""
import json
import os
import subprocess
import sys

LAUNCHER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "scripts", "launcher.js"))

_PROBE = (
    "const { cleanEnv } = require(process.argv[1]);"
    "console.log(JSON.stringify(cleanEnv(JSON.parse(process.argv[2]))));"
)


def _clean(env_dict):
    r = subprocess.run([sys.executable, "-c", "pass"], capture_output=True)  # 预热 noqa
    r = subprocess.run(
        ["node", "-e", _PROBE, LAUNCHER, json.dumps(env_dict)],
        capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout)


def test_poison_env_dropped():
    """毒 env：RG_*/WECOM_*/GIT_* 注入全部不透传。"""
    out = _clean({
        "RG_TRUST_PROJECT_CHANNELS": "1", "RG_TRUSTED_PROJECTS": "/tmp/x",
        "RG_MACHINE_NOTIFY": "/tmp/evil.json", "WECOM_API_BASE": "https://evil.example",
        "GIT_DIR": "/tmp/fake.git", "GIT_INDEX_FILE": "/tmp/poison",
        "PATH": "/usr/bin:/bin", "ZCODE_SESSION_ID": "s1",
    })
    for k in ("RG_TRUST_PROJECT_CHANNELS", "RG_TRUSTED_PROJECTS", "RG_MACHINE_NOTIFY",
              "WECOM_API_BASE", "GIT_DIR", "GIT_INDEX_FILE"):
        assert k not in out, k
    assert out["PATH"] == "/usr/bin:/bin" and out["ZCODE_SESSION_ID"] == "s1"


def test_contract_and_base_vars_kept():
    """契约变量与系统基础保留（守卫合法依赖）。"""
    env = {k: "v-" + k for k in (
        "ZCODE_SESSION_ID", "CLAUDE_SESSION_ID", "ZCODE_PROJECT_DIR",
        "CLAUDE_PROJECT_DIR", "ZCODE_HOME", "ZCODE_PLUGIN_ROOT",
        "HOME", "LANG", "TZ", "TMPDIR", "HTTP_PROXY", "NO_PROXY")}
    out = _clean(env)
    assert out == env


def test_case_insensitive_keys():
    """小写键归一后仍按白名单判（Windows 语义）。"""
    out = _clean({"path": "/x", "zcode_session_id": "s2", "rg_evil": "1"})
    assert out == {"path": "/x", "zcode_session_id": "s2"}
