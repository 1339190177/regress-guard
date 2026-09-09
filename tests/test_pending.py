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


# ─── P0-3：结构化 ref 回流（评审批次一） ─────────────────

def test_resolve_by_ref_exact_and_legacy_fallback(tmp_path, monkeypatch):
    """ref 精确匹配必中；无 ref 的旧记录按标题词边界唯一命中才兜底。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    pd = _load(PENDING, "pd5")
    pd.add("X", "plan_approval", "📋 待批准 REGRESS-2026-099", ref="REGRESS-2026-099")
    pd.add("X", "plan_approval", "📋 待批准 REGRESS-2026-100", ref="REGRESS-2026-100")
    pd.add("X", "blocked", "🛑 受阻 REGRESS-9")  # 旧格式无 ref，标题含 REGRESS-9
    assert pd.resolve_by_ref("REGRESS-2026-099") == 1
    s = pd.stats()
    assert s["pending"] == 2  # 只回流了精确那条
    # 词边界：REGRESS-9 不误吃 REGRESS-2026-099（已决的不在未决池）
    assert pd.resolve_by_ref("REGRESS-9") == 1
    s = pd.stats()
    assert s["pending"] == 1 and s["resolved"]["useful"] == 2


def test_resolve_by_ref_no_ambig_no_hit(tmp_path, monkeypatch):
    """空 ref 不动；多条标题都含目标 id 时不兜底（防误匹配）。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    pd = _load(PENDING, "pd6")
    assert pd.resolve_by_ref("") == 0
    pd.add("X", "blocked", "🛑 受阻 R1 复查")
    pd.add("X", "blocked", "🛑 受阻 R1 再看")
    assert pd.resolve_by_ref("R1") == 0  # 两条都命中标题=多义，不动
    assert pd.stats()["pending"] == 2


def test_notify_source_id_flows_into_ref(tmp_path, monkeypatch):
    """notify(--ref/source_id) → 待决记录带 ref 字段（plan_approve 自动回流的数据前提）。"""
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    nt = _load(NOTIFY, "nt5")
    proj = _mk_proj(tmp_path, [_stub_channel(tmp_path, tmp_path / "m") + " {title}"])
    nt.notify(str(proj), "plan_approval", "📋 待批准", "x",
              source_id="REGRESS-2026-024")
    pd = _load(PENDING, "pd7")
    recs = pd._load()[0]
    assert recs[1]["ref"] == "REGRESS-2026-024"
    assert pd.resolve_by_ref("REGRESS-2026-024") == 1


# ─── P2#20：坏通道模板只跳过自身（批次三） ─────────────────

def test_bad_channel_template_isolated(tmp_path):
    """模板含 awk 花括号（format 抛 KeyError）不再废掉后续通道。"""
    nt = _load(NOTIFY, "nt-iso")
    import stat as _stat
    stub = tmp_path / "stub.sh"
    marker = tmp_path / "iso-marker"
    stub.write_text("#!/bin/sh\necho ok >> " + str(marker) + "\n", encoding="utf-8")
    stub.chmod(_stat.S_IRWXU)
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    (proj / ".regress" / "config.json").write_text(json.dumps(
        {"notify": {"channels": [
            "awk '{print}' /nope",               # 坏模板：花括号炸 format
            str(stub) + " {title} {body}",       # 好通道必须仍然跑到
        ]}}, ensure_ascii=False), encoding="utf-8")
    ran = nt.notify(str(proj), "done", "隔离验证", "x")
    assert ran >= 1
    assert marker.exists()
