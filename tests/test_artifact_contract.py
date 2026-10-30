"""产物 schema 契约（v2.0.0 批162）：三族立桩 + 考古夹具 + run 因果链。

夹具（tests/fixtures/archaeology/）从工作区真实地层取样脱敏（2026-10-30，
每 kind/形态取最早一条=最老格式）——「当前读者读得起历史格式」这一考古
承诺的机器位：tolerant reader 在此钉死；格式变更 bump SCHEMA_VERSION 时
在此补新形态夹具。
"""
import importlib.util as ilu
import json
import os
import shutil
import subprocess
import sys

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                   "hooks", "scripts", "lib"))
sys.path.insert(0, LIB)

import history  # noqa: E402
import journal  # noqa: E402
import pending  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "archaeology")
PLAN_APPROVE = os.path.join(LIB, "plan_approve.py")
BRIDGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                      "hooks", "scripts", "plan_bridge.py"))


def _copy_fixture(tmp_path, family):
    proj = tmp_path / "proj"
    src = os.path.join(FIX, f"{family}.jsonl")
    if family == "journal":
        dst_dir = proj / ".regress" / "journal"
        dst_dir.mkdir(parents=True)
        shutil.copy(src, dst_dir / "events.jsonl")
    elif family == "history":
        (proj / ".regress").mkdir(parents=True, exist_ok=True)
        shutil.copy(src, proj / ".regress" / "history.jsonl")
    else:
        (tmp_path / "led").write_text(
            open(src, encoding="utf-8").read(), encoding="utf-8")
    return proj


# ─── 考古夹具：tolerant reader 三族 ─────────────────────

def test_journal_loader_tolerates_strata(tmp_path):
    proj = _copy_fixture(tmp_path, "journal")
    n_fixture = len(open(os.path.join(FIX, "journal.jsonl"),
                         encoding="utf-8").read().splitlines())
    # 外加一条真坏行（地层里真实存在的形态）——坏行跳过不炸
    with open(proj / ".regress" / "journal" / "events.jsonl", "a",
              encoding="utf-8") as f:
        f.write("{not-json-at-all\n")
    events = journal.load_journal(str(proj))
    assert len(events) == n_fixture  # 坏行被跳过，其余全读出


def test_history_loader_tolerates_strata(tmp_path):
    proj = _copy_fixture(tmp_path, "history")
    events = history.load_history(str(proj / ".regress"))
    kinds = {e.get("event") for e in events}
    assert {"commit_passed", "commit_blocked"} <= kinds  # 新老形态都在


def test_pending_loader_tolerates_strata(tmp_path, monkeypatch):
    _copy_fixture(tmp_path, "pending")
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "led"))
    adds, resolves = pending._load()
    assert len(adds) == 2 and len(resolves) >= 1  # 无 fp 旧形态+带 fp 新形态
    assert pending.count_merged() >= 1             # merge_into 旁路行可读


# ─── 写侧立桩：三族新行带 schema_version ────────────────

def test_journal_write_stamps_schema_version(tmp_path, monkeypatch):
    monkeypatch.setenv("REGRESS_JOURNAL", "on")
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    assert journal.journal_append("note", start_dir=str(proj), x="y") is True
    last = journal.load_journal(str(proj))[-1]
    assert last["schema_version"] == 1 and last["kind"] == "note"


def test_history_write_stamps_schema_version(tmp_path):
    rd = tmp_path / "proj" / ".regress"
    rd.mkdir(parents=True)
    history.record(str(rd), "note", "R1", detail="x")
    last = history.load_history(str(rd))[-1]
    assert last["schema_version"] == 1 and last["event"] == "note"


def test_pending_write_stamps_schema_version(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_PENDING_LEDGER", str(tmp_path / "p.jsonl"))
    nid = pending.add("proj-arch", "blocked", "拦截", ref="R9", fp="ab")
    line = open(tmp_path / "p.jsonl", encoding="utf-8").read().splitlines()[-1]
    e = json.loads(line)
    assert e["schema_version"] == 1 and e["id"] == nid


# ─── run 因果链：plumbing 三路 ──────────────────────────

def test_run_kw_unit_plan_approve_and_bridge():
    import plan_approve as pa
    assert pa._run_kw("id: X\nrun: amg-v2\n") == {"run_id": "amg-v2"}
    assert pa._run_kw("id: X\n") == {}
    spec = ilu.spec_from_file_location("pb_run_t", BRIDGE)
    pb = ilu.module_from_spec(spec)
    spec.loader.exec_module(pb)
    assert pb._run_kw("run: amg-v2\n") == {"run_id": "amg-v2"}
    assert pb._run_kw("") == {}


def test_plan_approve_event_carries_run_id(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".regress" / "manifests").mkdir(parents=True)
    (proj / "src").mkdir()
    (proj / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    mp = proj / ".regress" / "manifests" / "R1.md"
    mp.write_text("---\nid: R1\nrequirement: \"r\"\nstatus: planning\n"
                  "run: run-x1\n"
                  "planned_changes:\n  - id: F1\n    file: \"src/a.py\"\n"
                  "    type: method-logic\nactual_changes: []\n---\nb\n",
                  encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj),
           "CLAUDE_SESSION_ID": "s1", "REGRESS_JOURNAL": "on",
           "RG_NO_NOTIFY": "1",
           "RG_MACHINE_NOTIFY": str(tmp_path / "nm.json"),
           "RG_PENDING_LEDGER": str(tmp_path / "p.jsonl"),
           "RG_SEND_LEDGER": str(tmp_path / "s.log"),
           "RG_CHAT_STATE": str(tmp_path / "c.json")}
    r = subprocess.run([sys.executable, PLAN_APPROVE, str(mp)],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    ev = [json.loads(ln) for ln in
          (proj / ".regress" / "journal" / "events.jsonl")
          .read_text(encoding="utf-8").splitlines() if ln.strip()]
    approved = [e for e in ev if e.get("kind") == "plan_approved"]
    assert approved and approved[0].get("run_id") == "run-x1"
    assert approved[0].get("schema_version") == 1


def test_gate_record_injects_run_id(tmp_path):
    spec = ilu.spec_from_file_location(
        "pcg_run_t", os.path.abspath(os.path.join(
            os.path.dirname(LIB), "pre_commit_guard.py")))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    rd = tmp_path / ".regress"
    rd.mkdir(parents=True)
    m._RUN_ID["v"] = "amg-v2"
    m.record(str(rd), "note", "R1", note="t")
    m._RUN_ID["v"] = ""
    m.record(str(rd), "note", "R1", note="t2")
    evs = history.load_history(str(rd))
    with_run = [e for e in evs if e.get("note") == "t"]
    without = [e for e in evs if e.get("note") == "t2"]
    assert with_run and with_run[0].get("run_id") == "amg-v2"
    assert without and "run_id" not in without[0]  # 无 run 语义不带空值


def test_trace_run_filter(tmp_path):
    rd = tmp_path / "proj" / ".regress"
    rd.mkdir(parents=True)
    with open(rd / "history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2026-10-30T10:00:00",
                            "event": "commit_passed", "manifest_id": "R-in",
                            "session_id": "s", "run_id": "run-x1"}) + "\n")
        f.write(json.dumps({"timestamp": "2026-10-30T11:00:00",
                            "event": "commit_passed", "manifest_id": "R-out",
                            "session_id": "s"}) + "\n")
    out = history.build_trace(str(rd), run="run-x1")
    assert "R-in" in out and "R-out" not in out
    full = history.build_trace(str(rd))
    assert "R-in" in full and "R-out" in full  # 不过滤=全量（现行为回归）


# ─── 跨格式折叠点：feature_fire_health 对新旧混排不炸 ───

def test_fold_mixed_old_new_journal(tmp_path):
    proj = _copy_fixture(tmp_path, "journal")     # 44 种真实 kind 的最老形态
    _copy_fixture(tmp_path, "history")            # 新老 history 形态
    shutil.move(str(tmp_path / "proj" / ".regress" / "history.jsonl"),
                str(proj / ".regress" / "history.jsonl"))
    res = history.feature_fire_health(str(proj / ".regress"))
    assert isinstance(res, dict)  # 唯一跨格式耦合点：旧格式行不炸探针
