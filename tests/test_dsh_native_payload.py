"""dsh 原生适配层 payload 契约（批171）：tool_name 缺口修复双证。

背景（2026-11-02 super-agent 接入勘察实证）：index.js 构造的 payload 只含
tool_input——而 boundary(:405)/execution_valve(:214)/rbe(:294-323) 都以
tool_name 为门控，dsh 原生路径三守卫整链 no-op，仅提交门禁（不看
tool_name）在工作。本批 JS 侧补 canonicalized tool_name：execution_valve
严格等 "Bash" 且不自行规范化，故 canonicalize 必须在 JS 完成（对已是
CC 形态的名幂等）。

钉死面：
- 源码契约：index.js pre/post 两处 payload 构造都带 canonicalized tool_name
- 行为契约：原生形态 payload（含 tool_name）直打三守卫真实生效
- 缺口标本：旧形态（无 tool_name）三守卫 exit 0 no-op——证明修复必要性
- jobs 中间态：5 秒转后台的 worker 命令在 post-execute 时 result 是
  "moved to background" 中间态——resultFailed 判 false（记为成功），
  fail_watch 迟到失败不可见。已知限制（docs/dsh-support.md 留档）。
"""
import sys
import json
import os
import re
import subprocess

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
LIB = os.path.abspath(LIB)
BOUNDARY = os.path.join(LIB, "boundary_guard.py")
RBE = os.path.join(LIB, "read_before_edit_guard.py")
VALVE = os.path.join(LIB, "execution_valve.py")
INDEX_JS = os.path.join(os.path.dirname(__file__), "..", "deploy",
                        "dsh-native", "lib", "index.js")
INDEX_JS = os.path.abspath(INDEX_JS)


def _src():
    with open(INDEX_JS, encoding="utf-8") as f:
        return f.read()


def _run(script, payload, argv=None, project=None, env_extra=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("ZCODE_PROJECT_DIR", None)
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, script] + (argv or []), input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15,
    )
    return proc.returncode, proc.stderr


def _mk_project(tmp_path, config=None):
    p = tmp_path / "proj"
    (p / ".regress" / "manifests").mkdir(parents=True)
    if config is not None:
        (p / ".regress" / "config.json").write_text(
            json.dumps(config), encoding="utf-8")
    return p


# ─── 源码契约：payload 构造带 tool_name（防回归 ratchet）──────────

def test_pre_execute_payload_carries_tool_name():
    src = _src()
    # base 构造必须含 tool_name（canonicalized）——缺它=三守卫整链 no-op
    assert re.search(
        r"const base = \{ tool_name: canonicalToolName\(exec\.name\),"
        r" tool_input: args \?\? \{\} \};", src), \
        "pre-execute base payload 缺 tool_name（批171 回归）"


def test_post_execute_payloads_carry_tool_name():
    src = _src()
    # rbe post / risk_watch / fail_watch 三处 payload 均需 canonicalized 名
    posts = re.findall(r'\{ tool_name: name, tool_input: args \?\? \{\}'
                       r'(?:, tool_response: response)? \}', src)
    assert len(posts) >= 3, f"post-execute payload 带名不足 3 处：{len(posts)}"


def test_canonical_fn_bash_family_and_idempotence():
    src = _src()
    assert "if (BASH_TOOLS.has(name)) return \"Bash\";" in src, \
        "canonicalize 必须把 bash/pwsh 族归一为 Bash（execution_valve 严格等 Bash）"
    # 对已是 CC 形态的名幂等：首字母大写恒等（Edit/Write/ApplyPatch/Read）
    assert "name.charAt(0).toUpperCase() + name.slice(1)" in src


# ─── 行为契约：原生形态 payload 直打三守卫真实生效 ────────────────

def test_valve_fires_with_canonical_payload(tmp_path):
    p = _mk_project(tmp_path)
    # 靶须为项目外且非 /tmp 绝对路径（阀对 /tmp 清理豁免——见 _rm_targets_dangerous）
    code, _ = _run(VALVE, {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf ~/rg171-valve-probe"},
        "session_id": "test-session",
    }, project=p)
    assert code == 2, "含 canonicalized tool_name 的原生 payload 必须触发执行阀"


def test_boundary_fires_with_canonical_payload(tmp_path):
    p = _mk_project(tmp_path, config={
        "boundary": {"forbidden": ["secrets/**"]}})
    (p / "secrets").mkdir()
    (p / "secrets" / "kv.json").write_text("{}", encoding="utf-8")
    code, err = _run(BOUNDARY, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(p / "secrets" / "kv.json")},
        "session_id": "test-session",
    }, project=p)
    assert code == 2, "含 canonicalized tool_name 的原生 payload 必须触发边界守卫"


def test_rbe_fires_with_canonical_payload(tmp_path):
    p = _mk_project(tmp_path)
    target = p / "app.py"
    target.write_text("print('v1')\n", encoding="utf-8")
    # 未读先改：payload 带 tool_name 后 rbe 的 pre 分支（Edit 族）真实可达
    code, err = _run(RBE, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
        "session_id": "test-session",
    }, argv=["pre"], project=p)
    assert code == 2, "含 canonicalized tool_name 的原生 payload 必须触发先读后改"


# ─── 缺口标本：旧形态（无 tool_name）三守卫 no-op ─────────────────

def test_legacy_payload_without_tool_name_is_noop(tmp_path):
    """2026-11-02 前的原生路径实况：payload 无 tool_name → 守卫自判非管辖。

    这不是期望行为，是缺口标本——证明本批修复的必要性（非装饰性测试）。"""
    p = _mk_project(tmp_path, config={
        "boundary": {"forbidden": ["secrets/**"]}})
    (p / "secrets").mkdir()
    (p / "secrets" / "kv.json").write_text("{}", encoding="utf-8")
    valve_code, _ = _run(VALVE, {
        "tool_input": {"command": "rm -rf ~/rg171-legacy-probe"},
        "session_id": "test-session",
    }, project=p)
    boundary_code, _ = _run(BOUNDARY, {
        "tool_input": {"file_path": str(p / "secrets" / "kv.json")},
        "session_id": "test-session",
    }, project=p)
    assert valve_code == 0 and boundary_code == 0, (
        "旧形态 payload 的 no-op 语义变了——若守卫已自行兼容缺名，请把本标本测"
        "改为断言 exit 2 并更新 docs/dsh-support.md")


# ─── jobs 中间态：resultFailed 对后台化结果的已知限制 ─────────────

def _extract_fn(src, name):
    """从 index.js 抽函数源（花括号配平）——node 直跑行为探查用。"""
    m = re.search(r"function " + name + r"\(", src)
    if not m:
        return None
    start = src.index("{", m.end() - 1)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
    return None


def test_result_failed_on_job_intermediate_state():
    """worker preset 5 秒转后台：post-execute 拿到的是中间态结果。

    断言现状（非期望）：后台化提示不带 [exit code: N>0]/Error: 前缀 →
    resultFailed=False → fail_watch 对迟到的作业失败不可见。已留档
    docs/dsh-support.md「已知边界」；若未来接 job 完成事件，改断言 True。"""
    src = _src()
    blocks = _extract_fn(src, "blocksToText")
    failed = _extract_fn(src, "resultFailed")
    assert blocks and failed, "index.js 缺 blocksToText/resultFailed（重构？）"
    probe = blocks + "\n" + failed + """
const intermediate = { content: [{ type: "text",
  text: "moved to background (job 3); use jobs to wait" }] };
const boom = { content: [{ type: "text", text: "[exit code: 1] boom" }] };
console.log(JSON.stringify({
  intermediate_failed: resultFailed(intermediate),
  real_failure_failed: resultFailed(boom),
}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", probe],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    assert out.returncode == 0, f"node 探针崩：{out.stderr[:200]}"
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["real_failure_failed"] is True, "真失败判定回归"
    assert r["intermediate_failed"] is False, \
        "若中间态已被判失败（接了 job 事件），更新 docs 与本断言"


def test_docs_record_jobs_intermediate_limitation():
    docs = os.path.join(os.path.dirname(__file__), "..", "docs",
                        "dsh-support.md")
    with open(docs, encoding="utf-8") as f:
        text = f.read()
    assert "中间态" in text, "docs/dsh-support.md 已知边界须留档 jobs 中间态限制"


# ─── 批215（公网 issue#4）：childEnv 拒列式透传 ──────────────────

def test_childenv_denylist_passthrough():
    """env 拒列式政策四断言族：透传/拒列/强制/覆写（issue#4 病灶=白名单裁掉
    JAVA_HOME/MISE_* 致 mise 管 JDK 项目门禁 100% 误拦）。"""
    src = _src()
    m = re.search(r"const ENV_DENY_PREFIXES = \[[^\]]*\];", src)
    # _extract_fn 的花括号配平从参数默认值 {} 起跳会截半（childEnv 的
    # extra={} 毁其假设）——签名感知抽取：从函数体开括号起配平
    sig = "function childEnv(hostEnv, extra = {}) {"
    i = src.find(sig)
    assert i >= 0, "index.js 缺 childEnv（重构？）"
    depth, start = 0, i + len(sig) - 1
    for j in range(start, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                fn = src[i:j + 1]
                break
    assert m, "index.js 缺 ENV_DENY_PREFIXES（重构？）"
    probe = m.group(0) + "\n" + fn + """
const host = {
  PATH: "/usr/bin", HOME: "/home/t", JAVA_HOME: "/jdk/21",
  MISE_DATA_DIR: "D:/mise", ASDF_DIR: "/asdf", NVM_DIR: "/nvm",
  SYSTEMROOT: "C:/Windows", LANG: "C.UTF-8",
  // 拒列族样本
  PYTHONSTARTUP: "/tmp/evil.py", PYTHONPATH: "/tmp/evil",
  REGRESS_VALVE: "off", RG_JOURNAL: "off",
  WECOM_API_BASE: "https://evil", GIT_DIR: "/tmp/fake.git",
  NODE_OPTIONS: "--require=/tmp/evil.js", AWS_SECRET_ACCESS_KEY: "k",
  GITHUB_TOKEN: "t", CLAUDE_PROJECT_DIR: "/stale", ZCODE_PROJECT_DIR: "/stale",
};
const out = childEnv(host, { CLAUDE_PROJECT_DIR: "/real", CLAUDE_SESSION_ID: "s1" });
const leak = ["PYTHONSTARTUP","PYTHONPATH","REGRESS_VALVE","RG_JOURNAL",
  "WECOM_API_BASE","GIT_DIR","NODE_OPTIONS","AWS_SECRET_ACCESS_KEY",
  "GITHUB_TOKEN","ZCODE_PROJECT_DIR"].filter(k => k in out);
console.log(JSON.stringify({
  toolchain: [out.JAVA_HOME, out.MISE_DATA_DIR, out.ASDF_DIR, out.NVM_DIR],
  denied: leak,
  forced: out.PYTHONUTF8,
  override: [out.CLAUDE_PROJECT_DIR, out.CLAUDE_SESSION_ID],
  base: [out.PATH, out.HOME, out.SYSTEMROOT],
}));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", probe],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    assert r.returncode == 0, f"node 探针崩：{r.stderr[:300]}"
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["toolchain"] == ["/jdk/21", "D:/mise", "/asdf", "/nvm"], "工具链变量必须透传（issue#4 本体）"
    assert o["denied"] == [], f"拒列族泄漏：{o['denied']}"
    assert o["forced"] == "1", "PYTHONUTF8 强制注入"
    assert o["override"] == ["/real", "s1"], "本会话契约对必须覆写宿主残值"
    assert o["base"] == ["/usr/bin", "/home/t", "C:/Windows"], "基础变量透传"
