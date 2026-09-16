"""原生计划模式桥（v1.39，REGRESS-2026-028）。

批准点对齐：ExitPlanMode 批准 → 转录清单原子盖章；拒绝 → 零残留+化石。
覆盖：原文落档/幂等键(session+plan_hash)/修订更新/盖章既有 planning（双轨合一）/
拒绝双防御（failure 事件 + response 特征）/未接入项目不惊动/kill-switch。
"""
import io
import json
import os
import sys

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                       "hooks", "scripts"))
BRIDGE = os.path.join(SCRIPTS, "plan_bridge.py")

PLAN1 = "# 桥测试计划\n改 `src/a.py` 与 `tests/b.py`，参考 docs/c.md"
PLAN2 = "# 桥测试计划\n改 src/z.py 一处"  # 同标题修订（stem 稳定）
PAYLOAD1 = {"tool_name": "ExitPlanMode", "tool_input": {"plan": PLAN1}}


def _load():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("pb_test", BRIDGE)
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _proj(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".regress" / "manifests").mkdir(parents=True)
    return proj


def _env(monkeypatch, proj):
    monkeypatch.setenv("ZCODE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess_bridge_t")
    monkeypatch.setenv("REGRESS_JOURNAL", "on")  # conftest 默认 off，桥测试要化石


def _run(pb, payload, mode="post"):
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        assert pb.main([mode]) in (0, None)
    finally:
        sys.stdin = sys.__stdin__


def _manifests(proj):
    return list((proj / ".regress" / "manifests").glob("*.md"))


def _journal(proj):
    p = proj / ".regress" / "journal" / "events.jsonl"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_post_creates_manifest_verbatim(tmp_path, monkeypatch, capsys):
    """转录：原文整段落档（证据律）+ approved/session/via 盖章 + 边界提取。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    pb = _load()
    _run(pb, PAYLOAD1)
    files = _manifests(proj)
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "status: in-progress" in content and "via: native-plan-bridge" in content
    assert "session: sess_bridge_t" in content and "approved:" in content
    assert PLAN1 in content                          # 计划原文不改写
    assert 'file: "src/a.py"' in content and 'file: "tests/b.py"' in content
    assert "docs/c.md" in content
    ev = _journal(proj)
    assert "plan_approved" in ev and "native-plan-bridge" in ev
    assert capsys.readouterr().out == ""             # stdout 静默（schema 不冒险）


def test_post_idempotent_same_plan_hash(tmp_path, monkeypatch):
    """幂等键（顾问修正采纳）：同 session 同 plan_hash 重复事件完全 no-op。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    pb = _load()
    _run(pb, PAYLOAD1)
    _run(pb, PAYLOAD1)
    assert len(_manifests(proj)) == 1
    assert "plan_refined" not in _journal(proj)      # 无修订化石=真 no-op


def test_post_revision_updates_in_place(tmp_path, monkeypatch):
    """计划修订：同 via 清单整档重写（approved 取新批准时刻），不新建。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    pb = _load()
    _run(pb, PAYLOAD1)
    name = _manifests(proj)[0].name
    _run(pb, {"tool_name": "ExitPlanMode", "tool_input": {"plan": PLAN2}})
    files = _manifests(proj)
    assert len(files) == 1 and files[0].name == name
    content = files[0].read_text(encoding="utf-8")
    assert "src/z.py" in content and "src/a.py" not in content
    assert "plan_refined" in _journal(proj)


def test_post_stamps_existing_planning_manifest(tmp_path, monkeypatch):
    """双轨合一：同 session 既有 /regress:plan 的 planning 清单 → 直接盖章它。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    m = proj / ".regress" / "manifests" / "2026-001-manual.md"
    m.write_text(
        "---\nid: REGRESS-2026-001\nrequirement: \"手工清单\"\nstatus: planning\n"
        "session: sess_bridge_t\ntier: S\ncreated_at: 2026-09-16\n"
        "planned_changes: []\nactual_changes: []\ntest_results: {}\n---\n"
        "# 手工清单\n", encoding="utf-8")
    pb = _load()
    _run(pb, PAYLOAD1)
    assert len(_manifests(proj)) == 1               # 不新建第二条
    content = m.read_text(encoding="utf-8")
    assert "status: in-progress" in content and "approved:" in content
    assert "via: native-plan-bridge" in content and "plan_hash:" in content
    assert "id: REGRESS-2026-001" in content         # 原编号保留
    assert "dual-track" in _journal(proj)


def test_fail_mode_zero_residue_with_fossil(tmp_path, monkeypatch):
    """拒绝（failure 事件）：零清单残留 + design_rejected 化石带摘录（可考古）。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    pb = _load()
    _run(pb, PAYLOAD1, mode="fail")
    assert _manifests(proj) == []
    ev = _journal(proj)
    assert "design_rejected" in ev and "桥测试计划" in ev  # 摘录在化石里


def test_post_with_rejection_response_treated_as_rejected(tmp_path, monkeypatch):
    """拒绝双防御之二：成功事件内含拒绝语义 → 不建清单（拒绝载荷语义未证）。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    pb = _load()
    payload = dict(PAYLOAD1, tool_response={"error": "user rejected the plan"})
    _run(pb, payload)
    assert _manifests(proj) == []
    assert "design_rejected" in _journal(proj)


def test_no_regress_project_untouched(tmp_path, monkeypatch):
    """未接入项目（无 .regress）：桥不惊动——不建产物不建目录。"""
    bare = tmp_path / "bare"
    bare.mkdir()
    _env(monkeypatch, bare)
    pb = _load()
    _run(pb, PAYLOAD1)
    assert not (bare / ".regress").exists()
    assert list(bare.iterdir()) == []                # 一个文件都没写


def test_kill_switch(tmp_path, monkeypatch):
    """REGRESS_PLAN_BRIDGE=off 一刀关（桥是增强不是依赖）。"""
    proj = _proj(tmp_path)
    _env(monkeypatch, proj)
    monkeypatch.setenv("REGRESS_PLAN_BRIDGE", "off")
    pb = _load()
    _run(pb, PAYLOAD1)
    assert _manifests(proj) == []


def test_extract_paths_filters_url_and_bare_names():
    """URL 先剥（裸正则会抠出 x.y/a/b.py）；无斜杠的纯文件名无边界价值。"""
    pb = _load()
    out = pb.extract_paths("看 https://x.y/a/b.py 和 README.md 与 src/c.py")
    assert out == ["src/c.py"]


def test_next_id_preserves_project_format(tmp_path):
    """编号自推保持项目既有格式：REGRESS-YYYY-NNN 与 REGRESS-NNN 两态。"""
    pb = _load()
    proj = _proj(tmp_path)
    mdir = str(proj / ".regress" / "manifests")
    (proj / ".regress" / "manifests" / "a.md").write_text(
        "---\nid: REGRESS-2026-027\nstatus: done\n---\nx", encoding="utf-8")
    mid, stem = pb.next_id_and_name(mdir, "t")
    assert mid == "REGRESS-2026-028" and stem.startswith("2026-028-")
    proj2 = tmp_path / "proj2"
    (proj2 / ".regress" / "manifests").mkdir(parents=True)
    mdir2 = str(proj2 / ".regress" / "manifests")
    (proj2 / ".regress" / "manifests" / "b.md").write_text(
        "---\nid: REGRESS-005\nstatus: done\n---\nx", encoding="utf-8")
    mid2, _ = pb.next_id_and_name(mdir2, "t")
    assert mid2 == "REGRESS-006"
