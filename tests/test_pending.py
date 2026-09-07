"""决策推送待决台账（v1.34 推送闭环）：add/resolve/list/stats + notify 决策事件落账。"""
import json
import os
import stat

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))
PENDING = os.path.join(LIB, "pending.py")
NOTIFY = os.path.join(LIB, "notify.py")


def _load(path, name):
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(name, path)
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _stub_channel(tmp_path, marker):
    stub = tmp_path / "stub.sh"
    stub.write_text("#!/bin/sh\necho \"$@\" >> %s\n" % marker, encoding="utf-8")
    stub.chmod(stat.S_IRWXU)
    return str(stub)


def _mk_proj(tmp_path, channels):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True, exist_ok=True)
    (proj / ".regress" / "config.json").write_text(
        json.dumps({"notify": {"channels": channels}}, ensure_ascii=False), encoding="utf-8")
    return proj


# ─── 台账本体 ────────────────────────────────────────────

def test_add_returns_incrementing_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    pd = _load(PENDING, "pd")
    assert pd.add("P", "blocked", "t1") == 1
    assert pd.add("P", "blocked", "t2") == 2
    assert len(pd.pending_records()) == 2


def test_resolve_filters_pending_and_feeds_fp_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    pd = _load(PENDING, "pd")
    a, b, c = pd.add("P", "blocked", "t"), pd.add("P", "sensory", "t"), pd.add("P", "blocked", "t")
    pd.resolve(a, "useful")
    pd.resolve(b, "fp")
    s = pd.stats()
    assert s["pending"] == 1 and s["resolved"] == {"useful": 1, "fp": 1, "ignored": 0}
    assert s["fp_rate"] == 0.5  # 1 误报 / 2 已决


def test_resolve_rejects_unknown_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    pd = _load(PENDING, "pd")
    pid = pd.add("P", "blocked", "t")
    try:
        pd.resolve(pid, "meow")
        assert False, "未知 outcome 必须拒绝"
    except ValueError:
        pass


def test_bad_lines_skipped(tmp_path, monkeypatch):
    """坏行跳过（台账是增强不是依赖）——重放不炸、好行不丢。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    with open(tmp_path / "p.jsonl", "w", encoding="utf-8") as f:
        f.write('{"id": 1, "ts": "2026-09-07T00:00:00", "project": "P", '
                '"event": "blocked", "title": "t"}\n')
        f.write('not json\n')
    pd = _load(PENDING, "pd")
    assert pd.add("P", "blocked", "t2") == 2  # max(id)+1，坏行不影响


# ─── notify 集成 ─────────────────────────────────────────

def test_decision_push_creates_pending_with_id_in_body(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    nt = _load(NOTIFY, "nt2")
    marker = tmp_path / "m"
    proj = _mk_proj(tmp_path, [_stub_channel(tmp_path, marker) + " {title} {body}"])
    assert nt.notify(str(proj), "plan_approval", "📋 待批准", "x") == 1
    out = marker.read_text(encoding="utf-8")
    assert "〔待决#1〕" in out and "有用/误报/忽略" in out
    pd = _load(PENDING, "pd2")
    recs = pd.pending_records()
    assert list(recs) == [1] and recs[1]["event"] == "plan_approval"


def test_info_push_creates_no_pending(tmp_path, monkeypatch):
    """done/progress/test 是信息型推送——不产生待决（广播≠决策）。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    nt = _load(NOTIFY, "nt3")
    marker = tmp_path / "m"
    proj = _mk_proj(tmp_path, [_stub_channel(tmp_path, marker) + " {title} {body}"])
    nt.notify(str(proj), "done", "🏁 完成", "y")
    nt.notify(str(proj), "progress", "⏳ 进度", "z")
    out = marker.read_text(encoding="utf-8")
    assert "〔待决#" not in out
    pd = _load(PENDING, "pd3")
    assert pd.pending_records() == {}


def test_stats_dashboard_parses_ledger(tmp_path, monkeypatch, capsys):
    """观察仪表盘：送达率 + event 维度（含旧格式归桶）+ 待决聚合。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    monkeypatch.setenv("RG_SEND_LEDGER", str(tmp_path / "send.log"))
    with open(tmp_path / "send.log", "w", encoding="utf-8") as f:
        f.write("09-07 12:00:00 errcode=0 event=done agent=2 【X】t1\n"
                "09-07 12:01:00 errcode=0 event=blocked agent=2 【X】t2\n"
                "09-07 12:02:00 errcode=40056 event=test agent=2 【X】t3\n"
                "09-07 12:03:00 errcode=0 agent=2 【X】t4\n")
    nt = _load(NOTIFY, "nt4")
    pd = _load(PENDING, "pd4")
    pd.add("X", "sensory", "👀 感官终验")
    nt._stats()
    out = capsys.readouterr().out
    assert "4 条" in out and "75%" in out
    assert "done" in out and "旧格式" in out
    assert "未决 1" in out and "感官终验" in out
