"""任务租约（v1.109 批161）：盖章/过期收回/输入钉——异步多执行体治理·步一。

覆盖：lib/lease.py 单一来源单元（stamp 三态/expired 四态/drift/hash 敏感性/
TTL 覆写）+ fallback 解析器 lease 块 + plan_approve 批准转写盖章集成 +
边界守卫过期收回集成（未过期/无 lease 回归）+ 哨兵 ⏳/📥 渲染 + 门禁判定函数。
语义红线：过期=收回跨会话保护，不改 status 不处置清单（self_heal 公理）。
"""
import importlib.util as ilu
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                   "hooks", "scripts", "lib"))
sys.path.insert(0, LIB)

import lease  # noqa: E402

GUARD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                     "hooks", "scripts", "boundary_guard.py"))
PLAN_APPROVE = os.path.join(LIB, "plan_approve.py")


def _proj(tmp_path, lease_block="", session="sess-other", status="in-progress",
          config=None):
    proj = tmp_path / "proj"
    (proj / ".regress" / "manifests").mkdir(parents=True)
    (proj / "src").mkdir()
    (proj / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    if config is not None:
        (proj / ".regress" / "config.json").write_text(
            json.dumps(config), encoding="utf-8")
    (proj / ".regress" / "manifests" / "R1.md").write_text(
        f"---\nid: R1\nrequirement: \"租约测试\"\nstatus: {status}\n"
        f"session: {session}\n{lease_block}"
        "boundary:\n  include:\n    - \"src/**\"\n"
        "planned_changes:\n  - id: F1\n    file: \"src/a.py\"\n"
        "    type: method-logic\nactual_changes: []\n---\nbody\n",
        encoding="utf-8")
    return proj


def _iso(dt):
    return dt.isoformat(timespec="seconds")


# ─── lease.stamp（盖章三态） ─────────────────────────────

def test_stamp_inserts_after_session(tmp_path):
    proj = _proj(tmp_path)
    path = str(proj / ".regress" / "manifests" / "R1.md")
    content = open(path, encoding="utf-8").read().replace("lease:\n", "")
    out = lease.stamp(content, path, "sess-a")
    assert "holder: sess-a" in out and "input_hash:" in out
    assert out.index("lease:") > out.index("session: sess-other")
    assert out.count("lease:") == 1


def test_stamp_replaces_existing(tmp_path):
    """重盖=接管/续租：原位替换不重复，holder 换新。"""
    proj = _proj(tmp_path, lease_block=(
        f'lease:\n  holder: sess-old\n  expires_at: "{_iso(datetime.now())}"\n'
        '  input_hash: deadbeef0000\n'))
    path = str(proj / ".regress" / "manifests" / "R1.md")
    out = lease.stamp(open(path, encoding="utf-8").read(), path, "sess-new")
    assert "holder: sess-new" in out and "sess-old" not in out
    assert out.count("lease:") == 1


def test_stamp_no_holder_noop(tmp_path):
    proj = _proj(tmp_path)
    path = str(proj / ".regress" / "manifests" / "R1.md")
    content = open(path, encoding="utf-8").read()
    assert lease.stamp(content, path, "") == content


def test_fallback_parser_reads_lease_block(tmp_path):
    """零解析改动验证：手写 fallback（无 PyYAML）分支③读出 lease 三件。"""
    from manifest_parser import _parse_fallback
    fm = ("id: R1\nstatus: in-progress\nlease:\n"
          "  holder: sess-a\n"
          '  expires_at: "2026-11-02T10:00:00"\n'
          "  input_hash: abc123def456\n")
    parsed = _parse_fallback(fm)
    assert parsed["lease"]["holder"] == "sess-a"
    assert parsed["lease"]["expires_at"] == "2026-11-02T10:00:00"
    assert parsed["lease"]["input_hash"] == "abc123def456"


# ─── expired（四态：无块/未过期/已过期/格式坏） ───────────

def _content_with_lease(exp_line):
    return ("---\nid: X\nstatus: in-progress\nlease:\n  holder: h\n"
            f"  expires_at: {exp_line}\n  input_hash: ab\n---\nbody")


def test_expired_variants():
    assert lease.expired("---\nid: X\nstatus: in-progress\n---\nb") is False
    assert lease.expired(_content_with_lease(
        f'"{_iso(datetime.now() + timedelta(hours=1))}"')) is False
    assert lease.expired(_content_with_lease(
        f'"{_iso(datetime.now() - timedelta(hours=1))}"')) is True
    assert lease.expired(_content_with_lease('"not-a-date"')) is True  # 格式坏=过期


def test_expired_from_dict_variants():
    assert lease.expired_from_dict(None) is False
    assert lease.expired_from_dict({}) is False
    assert lease.expired_from_dict(
        {"expires_at": _iso(datetime.now() + timedelta(hours=1))}) is False
    assert lease.expired_from_dict(
        {"expires_at": _iso(datetime.now() - timedelta(hours=1))}) is True
    assert lease.expired_from_dict({"expires_at": "garbage"}) is True


# ─── input_hash（敏感性/确定性） ────────────────────────

def test_input_hash_sensitive_and_deterministic(tmp_path):
    proj = _proj(tmp_path)
    path = str(proj / ".regress" / "manifests" / "R1.md")
    h1 = lease.input_hash(path)
    assert h1 == lease.input_hash(path) and len(h1) == 12
    (proj / "src" / "a.py").write_text("x = 2  # 改动\n", encoding="utf-8")
    assert lease.input_hash(path) != h1


def test_input_hash_absent_deterministic(tmp_path):
    """声明的文件缺失记 absent——确定性（同布局重算同值）。"""
    proj = _proj(tmp_path)
    path = str(proj / ".regress" / "manifests" / "R1.md")
    os.remove(proj / "src" / "a.py")
    assert lease.input_hash(path) == lease.input_hash(path)


def test_drift_only_when_pinned_differs(tmp_path):
    proj = _proj(tmp_path, lease_block=(
        f'lease:\n  holder: h\n  expires_at: '
        f'"{_iso(datetime.now() + timedelta(hours=1))}"\n'
        '  input_hash: deadbeef0000\n'))
    path = str(proj / ".regress" / "manifests" / "R1.md")
    assert lease.drift(open(path, encoding="utf-8").read(), path) is True
    # 无钉=不诬告（back-compat）：无 lease 块的存量清单永不报漂移
    proj2 = _proj(tmp_path / "np2", lease_block="")
    path2 = str(proj2 / ".regress" / "manifests" / "R1.md")
    assert lease.drift(open(path2, encoding="utf-8").read(), path2) is False


# ─── TTL（config 覆写 / 缺省 72h） ──────────────────────

def test_ttl_config_override(tmp_path):
    proj = _proj(tmp_path, config={"lease": {"ttl_hours": 1}})
    path = str(proj / ".regress" / "manifests" / "R1.md")
    out = lease.stamp(open(path, encoding="utf-8").read(), path, "s")
    from manifest_fields import block_value
    exp = datetime.fromisoformat(
        block_value(out, "lease", "expires_at"))
    delta = (exp - datetime.now()).total_seconds()
    assert 3000 < delta < 3900, delta  # ≈1h（覆写生效）


def test_ttl_default_72h(tmp_path):
    proj = _proj(tmp_path)
    path = str(proj / ".regress" / "manifests" / "R1.md")
    out = lease.stamp(open(path, encoding="utf-8").read(), path, "s")
    from manifest_fields import block_value
    exp = datetime.fromisoformat(
        block_value(out, "lease", "expires_at"))
    delta = (exp - datetime.now()).total_seconds()
    assert 72 * 3600 - 300 < delta < 72 * 3600 + 300, delta


# ─── plan_approve 批准转写盖章（集成） ──────────────────

def test_approve_stamps_lease(tmp_path):
    proj = _proj(tmp_path, status="planning", lease_block="", session="")
    path = proj / ".regress" / "manifests" / "R1.md"
    env = {**os.environ,
           "CLAUDE_PROJECT_DIR": str(proj),
           "CLAUDE_SESSION_ID": "sess-approve",
           "REGRESS_JOURNAL": "off", "RG_NO_NOTIFY": "1",
           "RG_MACHINE_NOTIFY": str(tmp_path / "nm.json"),
           "RG_PENDING_LEDGER": str(tmp_path / "p.jsonl"),
           "RG_SEND_LEDGER": str(tmp_path / "s.log"),
           "RG_CHAT_STATE": str(tmp_path / "c.json")}
    r = subprocess.run([sys.executable, PLAN_APPROVE, str(path)],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    content = path.read_text(encoding="utf-8")
    assert "status: in-progress" in content
    assert "holder: sess-approve" in content and "input_hash:" in content


# ─── 边界守卫：过期收回（集成）+ 未过期/无 lease 回归 ────

def _run_guard(proj, target, extra_env):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}
    env.update(extra_env)
    return subprocess.run(
        ["python3", GUARD],
        input=json.dumps({"tool_name": "Edit",
                          "tool_input": {"file_path": str(target)}}),
        capture_output=True, text=True, env=env, timeout=15)


def test_boundary_expired_lease_allows_edit(tmp_path):
    """过期=收回跨会话保护：他会话清单不再拦编辑（死会话出口）。"""
    proj = _proj(tmp_path, lease_block=(
        'lease:\n  holder: sess-other\n'
        f'  expires_at: "{_iso(datetime.now() - timedelta(hours=1))}"\n'
        '  input_hash: deadbeef0000\n'))
    r = _run_guard(proj, proj / "src" / "a.py",
                   {"CLAUDE_SESSION_ID": "sess-mine"})
    assert r.returncode == 0, r.stderr


def test_boundary_unexpired_lease_still_blocks(tmp_path):
    """v1.34 回归：未过期租约的他会话清单照拦（保护未被过早收回）。"""
    proj = _proj(tmp_path, lease_block=(
        'lease:\n  holder: sess-other\n'
        f'  expires_at: "{_iso(datetime.now() + timedelta(hours=1))}"\n'
        '  input_hash: deadbeef0000\n'))
    r = _run_guard(proj, proj / "src" / "a.py",
                   {"CLAUDE_SESSION_ID": "sess-mine"})
    assert r.returncode == 2 and "跨会话" in r.stderr


def test_boundary_no_lease_legacy_still_blocks(tmp_path):
    """back-compat：无 lease 块=旧语义逐位不变（照拦）。"""
    proj = _proj(tmp_path, lease_block="")
    r = _run_guard(proj, proj / "src" / "a.py",
                   {"CLAUDE_SESSION_ID": "sess-mine"})
    assert r.returncode == 2 and "跨会话" in r.stderr


def test_boundary_expired_bad_format_also_released(tmp_path):
    """格式坏=过期（bypass 先例）：坏租约不许继续占边界。"""
    proj = _proj(tmp_path, lease_block=(
        'lease:\n  holder: sess-other\n'
        '  expires_at: "garbage"\n'
        '  input_hash: deadbeef0000\n'))
    r = _run_guard(proj, proj / "src" / "a.py",
                   {"CLAUDE_SESSION_ID": "sess-mine"})
    assert r.returncode == 0, r.stderr


# ─── 哨兵 ⏳/📥 渲染 ───────────────────────────────────

def test_sentinel_render_flags(tmp_path, capsys):
    proj = _proj(tmp_path, lease_block=(
        'lease:\n  holder: sess-other\n'
        f'  expires_at: "{_iso(datetime.now() - timedelta(hours=2))}"\n'
        '  input_hash: deadbeef0000\n'))  # 过期 + 钉不符=漂移
    import sentinel
    sentinel.render(str(proj))
    out = capsys.readouterr().out
    assert "⏳ 租约可收回" in out and "📥 输入已漂移" in out


# ─── 门禁判定函数 ──────────────────────────────────────

def test_gate_lease_expired_helper():
    spec = ilu.spec_from_file_location(
        "pcg_lease_t",
        os.path.join(os.path.dirname(GUARD), "pre_commit_guard.py"))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m._lease_expired({"lease": None}) is False  # 无块=旧语义
    assert m._lease_expired({"lease": {
        "expires_at": _iso(datetime.now() - timedelta(hours=1))}}) is True
    assert m._lease_expired({"lease": {
        "expires_at": _iso(datetime.now() + timedelta(hours=1))}}) is False
    assert m._lease_expired({"lease": {"expires_at": "garbage"}}) is True
