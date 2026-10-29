"""批158 AGENT-HOOKS 适配层测试（spec §4/§5 钉字段 + 真门禁 E2E）。

契约正本：responsibleai/agent-hooks spec/AGENT-HOOKS-0.1.md——
context core（§4.1）/pre_tool_call 的 tool_call{id,name,args}（§4.2）/
Verdict 字段集与禁令（§5）/响应信封（§5.5）。
"""
import json
import os
import subprocess
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)

from agent_hooks_adapter import RegressGuardInterceptor  # noqa: E402

GUARD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "scripts",
    "pre_commit_guard.py"))


def _ctx(tc_id, name, args, point="pre_tool_call"):
    """spec §4.2 形：core 字段 + pre_tool_call 条件必填。"""
    return {"spec": "agent-hooks/0.1", "interception_point": point,
            "timestamp": "2026-10-29T12:00:00Z", "sequence": 1,
            "agent": {"id": "a1", "framework": "pytest"},
            "session": {"id": "s1"},
            "tool_call": {"id": tc_id, "name": name, "args": args},
            "target": args}


# ── 点分派与三档路径 ──────────────────────────────────────

def test_non_tool_points_allow():
    """声明子集只有 pre_tool_call——其余点零逻辑 allow（§3 八点抽三）。"""
    it = RegressGuardInterceptor(project_dir="/tmp")
    for point in ("agent_startup", "input", "output", "agent_shutdown"):
        v = it.intercept({"spec": "agent-hooks/0.1",
                          "interception_point": point,
                          "timestamp": "2026-10-29T12:00:00Z", "sequence": 1,
                          "agent": {"id": "a1", "framework": "t"},
                          "session": {"id": "s1"}, "target": {}})
        assert v["decision"] == "allow" and len(v) == 1


def test_tier_a_fast_allow_zero_subprocess(monkeypatch):
    """已知非 shell 工具且无命令键 → 零子进程放行（A 档）。"""
    def _boom(*a, **k):
        raise AssertionError("A 档不应派生子进程")
    monkeypatch.setattr(subprocess, "run", _boom)
    it = RegressGuardInterceptor(project_dir="/tmp")
    v = it.intercept(_ctx("t1", "Read", {"path": "/x"}))
    assert v["decision"] == "allow"
    assert v["evidence"]["path_tier"] == "A"


def test_tier_b_non_commit_zero_subprocess(monkeypatch):
    """命令键命中但非提交类 → 进程内检测放行，零子进程（B 档）。"""
    def _boom(*a, **k):
        raise AssertionError("B 档非提交不应派生子进程")
    monkeypatch.setattr(subprocess, "run", _boom)
    it = RegressGuardInterceptor(project_dir="/tmp")
    v = it.intercept(_ctx("t2", "Bash", {"command": "ls -la /tmp"}))
    assert v["decision"] == "allow"
    assert v["evidence"]["path_tier"] == "B"


def test_tier_c_unknown_shape_goes_guard(monkeypatch):
    """未知形态（新工具名+陌生键）→ C 档慢路径让门禁自判（顾问反转：
    不确定一律放慢——宁多付开销不冒漏检险）。"""
    calls = []

    def _fake_run(*a, **k):
        calls.append(a)

        class _P:
            returncode, stderr = 0, ""
        return _P()
    monkeypatch.setattr(subprocess, "run", _fake_run)
    it = RegressGuardInterceptor(project_dir="/tmp")
    v = it.intercept(_ctx("t3", "run_widget",
                          {"snippet": "echo hi", "mode": "fast"}))
    assert v["decision"] == "allow" and v["evidence"]["path_tier"] == "C"
    assert len(calls) == 1  # 走了真门禁调用（此处被替换）


def test_missing_command_explicit_allow():
    """抽不到任何命令 → 显式 allow（无命令即无提交——缺命令策略文档化）。"""
    it = RegressGuardInterceptor(project_dir="/tmp")
    v = it.intercept(_ctx("t4", "mystery_tool", {"n": 5, "flag": True}))
    assert v["decision"] == "allow" and v["evidence"]["path_tier"] == "C"


def test_dedup_by_tool_call_id(monkeypatch):
    """同 tool_call.id 重派 → 去重不重跑门禁（§7 多点触发面）。"""
    n = {"runs": 0}

    def _fake_run(*a, **k):
        n["runs"] += 1

        class _P:
            returncode, stderr = 0, ""
        return _P()
    monkeypatch.setattr(subprocess, "run", _fake_run)
    it = RegressGuardInterceptor(project_dir="/tmp")
    ctx = _ctx("same-id", "weird", {"whatever_key": "git commit -m x"})
    v1 = it.intercept(ctx)
    v2 = it.intercept(dict(ctx, sequence=2))
    assert v1 == v2 and n["runs"] == 1


# ── fail-closed 与 schema ─────────────────────────────────

def test_crash_and_timeout_fail_closed(monkeypatch):
    """门禁崩溃/超时 → deny 且 reason 禁 host_error: 前缀（§5——那是宿主
    合成词）；同时验证适配器自身异常也 deny。"""
    def _crash(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(subprocess, "run", _crash)
    it = RegressGuardInterceptor(project_dir="/tmp", timeout=1)
    v = it.intercept(_ctx("c1", "Bash", {"command": "git commit -m x"}))
    assert v["decision"] == "deny"
    assert v["reason"] == "regress_guard:guard_crash"
    assert not v["reason"].startswith("host_error:")

    def _slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="guard", timeout=1)
    monkeypatch.setattr(subprocess, "run", _slow)
    v2 = it.intercept(_ctx("c2", "Bash", {"command": "git commit -m y"}))
    assert v2["reason"] == "regress_guard:guard_timeout"

    def _bad_ctx(ctx):
        raise RuntimeError("boom")
    monkeypatch.setattr(it, "_intercept", _bad_ctx)
    v3 = it.intercept(_ctx("c3", "Bash", {"command": "z"}))
    assert v3["decision"] == "deny" and v3["reason"] == \
        "regress_guard:adapter_crashed"


def test_verdict_schema_conformance():
    """§5 合规：decision 三值/字段集白名单/reason 前缀禁令/evidence
    canonical ≤10240B/warnings 形态——对全部路径的返回逐个校验。"""
    allowed_keys = {"decision", "reason", "message", "warnings",
                    "approval", "transform", "evidence"}
    it = RegressGuardInterceptor(project_dir="/tmp")
    verdicts = [
        it.intercept(_ctx("s1", "Read", {"path": "/x"})),
        it.intercept(_ctx("s2", "Bash", {"command": "echo ok"})),
        it.intercept(_ctx("s3", "mystery", {"n": 1})),
    ]
    for v in verdicts:
        assert set(v) <= allowed_keys, v
        assert v["decision"] in ("allow", "deny", "transform")
        if "reason" in v:
            assert isinstance(v["reason"], str)
            assert not v["reason"].startswith("host_error:")
        if "warnings" in v:
            assert isinstance(v["warnings"], list)
            for w in v["warnings"]:
                assert set(w) <= {"reason", "message"}
        if "evidence" in v:
            s = json.dumps(v["evidence"], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
            assert len(s.encode()) <= 10240


def test_envelope_shape():
    """§5.5 信封：根封闭 {verdict, extensions} 两键。"""
    it = RegressGuardInterceptor(project_dir="/tmp")
    v = it.intercept(_ctx("e1", "Read", {"path": "/x"}))
    env = it.to_envelope(v)
    assert set(env) == {"verdict", "extensions"}
    assert env["verdict"] is v
    assert "adapter_version" in env["extensions"]["regress_guard"]


# ── 真门禁 E2E（deny + allow 两态）─────────────────────────

def _mk_project(tmp_path, with_manifest):
    proj = tmp_path / "e2e"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    if with_manifest:
        (proj / ".regress" / "manifests").mkdir(parents=True)
        (proj / ".regress" / "manifests" / "R1.md").write_text(
            "---\nid: R1\nstatus: in-progress\ntier: S\n"
            "rollback: git revert 即回滚\nself_review:\n"
            "  计划外: 无\n  调试残留: 无\n"
            'planned_changes:\n  - {id: F1, file: "src/declared.py"}\n'
            "actual_changes: []\n---\n"
            "\n## 验收标准\n\n- When 提交，则 放行（验：pytest -q）\n",
            encoding="utf-8")
    return proj


def test_e2e_deny_through_real_guard(tmp_path):
    """真门禁 E2E deny：清单在场+暂存未声明文件 → F3 拦 → deny+
    reason=regress_guard:blocked+evidence.exit_code=2。"""
    proj = _mk_project(tmp_path, with_manifest=True)
    (proj / "src").mkdir()
    (proj / "src" / "undeclared.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "add", "src/undeclared.py"],
                   check=True)
    it = RegressGuardInterceptor(project_dir=str(proj))
    v = it.intercept(_ctx("d1", "Bash",
                          {"command": "git commit -m 改动（R1）；1/1"}))
    assert v["decision"] == "deny", v
    assert v["reason"] == "regress_guard:blocked"
    assert v["evidence"]["exit_code"] == 2
    assert "不在回归清单" in (v.get("message") or "")


def test_e2e_allow_through_real_guard(tmp_path):
    """真门禁 E2E allow：无治理结构的裸仓 → 门禁放行（exit 0）。"""
    proj = _mk_project(tmp_path, with_manifest=False)
    (proj / "src").mkdir()
    (proj / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "add", "src/a.py"], check=True)
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "init"],
                   check=True,
                   env={**os.environ,
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    it = RegressGuardInterceptor(project_dir=str(proj))
    v = it.intercept(_ctx("a1", "Bash",
                          {"command": "git commit -m followup"}))
    assert v["decision"] == "allow", v
    assert v["evidence"]["exit_code"] == 0
