"""journal（公理三：考古地层）的单元测试——lib 层 + 探测器接入。"""
import sys
import os
import json
import subprocess

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
LIB = os.path.abspath(LIB)
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "lib"))

from journal import journal_append, load_journal, journal_digest  # noqa: E402

FAIL_WATCH = os.path.join(LIB, "fail_watch.py")
RISK_WATCH = os.path.join(LIB, "risk_watch.py")
PROMPT_HOOK = os.path.join(LIB, "prompt_intercept.py")


def _feed(script, payload, project_dir, tmp_dir, extra_env=None):
    """喂 stdin 给 hook 脚本；项目指向 tmp project，/tmp 指向 tmp_dir。"""
    env = {**os.environ, "ZCODE_PROJECT_DIR": str(project_dir),
           "TMPDIR": str(tmp_dir), "REGRESS_JOURNAL": "on"}
    env.update(extra_env or {})
    return subprocess.run(
        ["python3", script], input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=10,
    )


# ── lib 层 ───────────────────────────────────────────────
# 注意：conftest autouse 夹具默认 REGRESS_JOURNAL=off（保护其他测试），
# 进程内用例须显式覆写为 on，才能走到真实分支


def test_append_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("REGRESS_JOURNAL", "on")
    (tmp_path / ".regress").mkdir()
    assert journal_append("tool_fail", start_dir=str(tmp_path), tool="Bash", sig="npm test")
    events = load_journal(str(tmp_path))
    assert len(events) == 1
    assert events[0]["kind"] == "tool_fail"
    assert events[0]["sig"] == "npm test"
    assert "ts" in events[0] and "session" in events[0]


def test_no_regress_dir_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("REGRESS_JOURNAL", "on")
    assert not journal_append("tool_fail", start_dir=str(tmp_path))
    assert load_journal(str(tmp_path)) == []


def test_kill_switch(tmp_path, monkeypatch):
    (tmp_path / ".regress").mkdir()
    monkeypatch.setenv("REGRESS_JOURNAL", "off")
    assert not journal_append("tool_fail", start_dir=str(tmp_path))


def test_field_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("REGRESS_JOURNAL", "on")
    (tmp_path / ".regress").mkdir()
    journal_append("risk_action", start_dir=str(tmp_path), detail="x" * 5000)
    events = load_journal(str(tmp_path))
    assert len(events[0]["detail"]) == 400


def test_digest_cross_session_filter(tmp_path, monkeypatch):
    """单会话高频=噪声不进经验；跨会话 ≥2 次才是稳定经验。"""
    monkeypatch.setenv("REGRESS_JOURNAL", "on")
    (tmp_path / ".regress").mkdir()
    for sess in ("s1", "s1", "s1", "s2"):
        journal_append("tool_fail", start_dir=str(tmp_path), sig="npm install", session=sess)
    journal_append("tool_fail", start_dir=str(tmp_path), sig="unique-once", session="s9")
    digest = journal_digest(str(tmp_path))
    sigs = [d["sig"] for d in digest]
    assert "npm install" in sigs
    assert "unique-once" not in sigs
    entry = next(d for d in digest if d["sig"] == "npm install")
    assert entry["sessions"] == 2 and entry["total"] == 4


# ── 探测器接入（子进程端到端）────────────────────────────

def test_fail_watch_journals(tmp_path):
    proj, tmpdir = tmp_path / "proj", tmp_path / "tmp"
    (proj / ".regress").mkdir(parents=True)
    tmpdir.mkdir()
    _feed(FAIL_WATCH, {"tool_name": "Bash", "tool_input": {"command": "npm test --json"}},
          proj, tmpdir)
    events = load_journal(str(proj))
    assert any(e["kind"] == "tool_fail" and e["sig"] == "npm test" for e in events)


def test_risk_watch_journals_risk_not_usage(tmp_path):
    proj, tmpdir = tmp_path / "proj", tmp_path / "tmp"
    (proj / ".regress").mkdir(parents=True)
    tmpdir.mkdir()
    _feed(RISK_WATCH, {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}},
          proj, tmpdir)
    _feed(RISK_WATCH, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
          proj, tmpdir)
    events = load_journal(str(proj))
    kinds = [e["kind"] for e in events]
    assert kinds.count("risk_action") == 1  # git reset --hard
    assert "usage" not in kinds  # 普查不入地层


def test_prompt_correction_journals(tmp_path):
    proj, tmpdir = tmp_path / "proj", tmp_path / "tmp"
    (proj / ".regress").mkdir(parents=True)
    tmpdir.mkdir()
    _feed(PROMPT_HOOK, {"prompt": "你这样理解不对，方向反了"}, proj, tmpdir)
    events = load_journal(str(proj))
    assert any(e["kind"] == "user_correction" for e in events)


def test_descriptive_error_not_journaled(tmp_path):
    """“报错了”是描述不是纠正——不得入地层。"""
    proj, tmpdir = tmp_path / "proj", tmp_path / "tmp"
    (proj / ".regress").mkdir(parents=True)
    tmpdir.mkdir()
    _feed(PROMPT_HOOK, {"prompt": "我这边终端报错了，你看看日志输出报错了什么"}, proj, tmpdir)
    events = load_journal(str(proj))
    assert not any(e["kind"] == "user_correction" for e in events)


# ── v1.14：CLI add——命令层埋化石的统一出口 ──

def test_cli_add_buries_assumption_fossil(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    r = subprocess.run(
        [sys.executable, os.path.join(LIB, "lib", "journal.py"),
         str(proj), "add", "assumption_broken",
         '{"manifest_id":"R1","vid":"V5","was":"按1601推测","reality":"Ack=1","evidence":"mock --self-test"}'],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "REGRESS_JOURNAL": "on"})
    assert r.returncode == 0, r.stderr
    assert '"ok": true' in r.stdout
    evts = [e for e in load_journal(str(proj)) if e.get("kind") == "assumption_broken"]
    assert len(evts) == 1
    assert evts[0]["vid"] == "V5" and evts[0]["reality"] == "Ack=1"


def test_cli_add_rejects_bad_json(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    r = subprocess.run(
        [sys.executable, os.path.join(LIB, "lib", "journal.py"),
         str(proj), "add", "assumption_broken", "not-json"],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "REGRESS_JOURNAL": "on"})
    assert r.returncode == 2
    assert "json" in r.stderr
