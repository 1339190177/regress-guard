"""history.py 的单元测试（含 Ch9 遗忘、Ch24 指标、Ch21 reason 分布）。"""
import sys
import os
import json
import tempfile
import pytest

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)

from history import record, load_history, summarize, _maybe_archive, build_trace, telemetry


@pytest.fixture
def regress_dir(tmp_path):
    rdir = tmp_path / ".regress"
    rdir.mkdir()
    return str(rdir)


def test_record_and_load(regress_dir):
    record(regress_dir, "commit_passed", "R1", runner="jest", passed=3, total=3)
    record(regress_dir, "commit_blocked", "R1", reason="test_failed")
    events = load_history(regress_dir)
    assert len(events) == 2
    assert events[0]["event"] == "commit_passed"
    assert events[1]["event"] == "commit_blocked"


def test_tech_debt(regress_dir):
    record(regress_dir, "bypass_used", "R1")
    record(regress_dir, "bypass_used", "R1")
    record(regress_dir, "commit_passed", "R1", runner="jest", passed=1, total=1)
    s = summarize(regress_dir)
    assert s["tech_debt"] == 1  # 2 bypass - 1 还债


def test_quality_score(regress_dir):
    record(regress_dir, "commit_passed", "R1", runner="jest")
    record(regress_dir, "commit_passed", "R1", runner="jest")
    record(regress_dir, "commit_blocked", "R1", reason="test_failed")
    s = summarize(regress_dir)
    assert s["quality_score"] == round(2/3, 2)  # 2/3 通过


def test_block_reasons(regress_dir):
    record(regress_dir, "commit_blocked", "R1", reason="test_failed")
    record(regress_dir, "commit_blocked", "R1", reason="test_failed")
    record(regress_dir, "commit_blocked", "R1", reason="untracked_files")
    s = summarize(regress_dir)
    assert s["block_reasons"]["test_failed"] == 2
    assert s["block_reasons"]["untracked_files"] == 1


def test_f3_rate(regress_dir):
    record(regress_dir, "commit_blocked", "R1", reason="untracked_files",
           untracked_files=["src/a.js"])
    record(regress_dir, "commit_passed", "R1", runner="jest")
    s = summarize(regress_dir)
    assert s["f3_rate"] == 0.5  # 1 次 F3 / 2 次总 commit


def test_archive(regress_dir):
    """Ch9 遗忘：超过阈值时归档旧事件。"""
    for i in range(10):
        record(regress_dir, "commit_passed", f"R{i}")
    history_path = os.path.join(regress_dir, "history.jsonl")
    # 手动触发归档（阈值设 5）
    _maybe_archive(regress_dir, history_path, max_events=5)
    # 主文件应只剩 5 条
    events = load_history(regress_dir)
    assert len(events) == 5
    # 归档文件应有 5 条
    archive_path = os.path.join(regress_dir, "history-archive.jsonl")
    assert os.path.exists(archive_path)
    with open(archive_path) as f:
        archive_lines = f.readlines()
    assert len(archive_lines) == 5


def test_empty_summary(regress_dir):
    """无数据时 summary 不崩溃。"""
    s = summarize(regress_dir)
    assert s["total_commits"] == 0
    assert s["quality_score"] == 0
    assert s["tech_debt"] == 0


def test_session_id_recorded(regress_dir):
    """证据链：session_id 自动记录。"""
    os.environ["CLAUDE_SESSION_ID"] = "sess-test-abc"
    try:
        record(regress_dir, "commit_passed", "R1", runner="jest")
        events = load_history(regress_dir)
        assert events[0]["session_id"] == "sess-test-abc"
    finally:
        os.environ.pop("CLAUDE_SESSION_ID", None)


def test_noise_filter(regress_dir):
    """噪声过滤：单 session 重复是噪声，跨 session 重复是经验。"""
    for sid in ["sess-A"]:
        os.environ["CLAUDE_SESSION_ID"] = sid
        for _ in range(5):
            record(regress_dir, "commit_blocked", "R1",
                   reason="untracked_files", untracked_files=["noise.js"])
    for sid in ["sess-B", "sess-C"]:
        os.environ["CLAUDE_SESSION_ID"] = sid
        record(regress_dir, "commit_blocked", "R1",
               reason="untracked_files", untracked_files=["real.js"])
    os.environ.pop("CLAUDE_SESSION_ID", None)

    s = summarize(regress_dir)
    # real.js 跨 2 session → 是经验
    assert any(f == "real.js" for f, _ in s["top_f3_files"]), "real.js 应在经验中"
    # noise.js 单 session → 是噪声
    assert any(f == "noise.js" for f, _ in s["top_f3_noise"]), "noise.js 应在噪声中"


def test_build_trace(regress_dir):
    """交付链：按 manifest→session 组织。"""
    os.environ["CLAUDE_SESSION_ID"] = "sess-trace-1"
    record(regress_dir, "commit_blocked", "R1", reason="untracked_files",
           untracked_files=["src/x.js"])
    record(regress_dir, "commit_passed", "R1", runner="jest", base_head="abc123def")
    os.environ.pop("CLAUDE_SESSION_ID", None)

    trace = build_trace(regress_dir)
    assert "R1" in trace
    assert "sess-trace-1"[:12] in trace or "sess-trace-1" in trace
    assert "commit_blocked" in trace
    assert "abc123def" in trace


def test_avg_coverage(regress_dir):
    """平均覆盖率：有数据时输出均值，无数据时 None。"""
    record(regress_dir, "commit_passed", "R1", runner="jest", coverage_pct=80)
    record(regress_dir, "commit_passed", "R1", runner="jest", coverage_pct=100)
    record(regress_dir, "commit_passed", "R2", runner="none")  # 无覆盖率
    s = summarize(regress_dir)
    assert s["avg_coverage_pct"] == 90




def _block(regress_dir, mid, reason, session, ts):
    """直写事件（record 的 timestamp/session 由 env 推断，测试要显式控制）。"""
    with open(os.path.join(regress_dir, "history.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": ts, "event": "commit_blocked",
                            "manifest_id": mid, "session_id": session,
                            "reason": reason}, ensure_ascii=False) + "\n")


def test_nudge_single_block_unflagged(regress_dir):
    """单次拦截无标——影子模式不制造噪音。"""
    from history import nudge_effectiveness
    _block(regress_dir, "R1", "scan_missing", "s1", "2026-09-16T10:00:00")
    rows = nudge_effectiveness(regress_dir)
    assert len(rows) == 1 and rows[0]["flag"] == "" and rows[0]["blocks"] == 1


def test_nudge_repeat_same_session(regress_dir):
    """同会话 ×2 = repeat（告警级，未到无效候选）。"""
    from history import nudge_effectiveness
    for i in range(2):
        _block(regress_dir, "R1", "card_stale", "s1",
               f"2026-09-16T1{i}:00:00")
    rows = nudge_effectiveness(regress_dir)
    assert rows[0]["flag"] == "repeat" and rows[0]["blocks"] == 2


def test_nudge_ineffective_cross_session(regress_dir):
    """≥3 且跨 ≥2 会话 = ineffective_candidate，分母恒带（顾问判据）。"""
    from history import nudge_effectiveness
    _block(regress_dir, "R1", "rollback_missing", "s1", "2026-09-16T10:00:00")
    _block(regress_dir, "R1", "rollback_missing", "s2", "2026-09-16T11:00:00")
    _block(regress_dir, "R1", "rollback_missing", "s3", "2026-09-16T12:00:00")
    rows = nudge_effectiveness(regress_dir)
    r = rows[0]
    assert r["flag"] == "ineffective_candidate"
    assert r["blocks"] == 3 and r["sessions"] == 3  # 分母+会话数都在


# ─── v1.58 召回有效性代理（B3：弱证据三态，干净才计） ────────

def _ev(regress_dir, event, mid, ts, reason=""):
    with open(os.path.join(regress_dir, "history.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": ts, "event": event,
                            "manifest_id": mid, "reason": reason},
                           ensure_ascii=False) + "\n")


def test_recall_clean_shadow_pending(regress_dir):
    """三态：直接放行=clean；间有拦截=shadow；无放行=pending。"""
    from history import recall_effectiveness
    _ev(regress_dir, "rule_recall", "M1", "2026-09-17T10:00:00", "test_failed")
    _ev(regress_dir, "commit_passed", "M1", "2026-09-17T10:05:00")
    _ev(regress_dir, "rule_recall", "M2", "2026-09-17T11:00:00", "scan_missing")
    _ev(regress_dir, "commit_blocked", "M2", "2026-09-17T11:02:00", "untracked_files")
    _ev(regress_dir, "commit_passed", "M2", "2026-09-17T11:09:00")
    _ev(regress_dir, "rule_recall", "M3", "2026-09-17T12:00:00", "test_failed")
    rows = recall_effectiveness(regress_dir)
    by_mid = {r["manifest_id"]: r["outcome"] for r in rows}
    assert by_mid == {"M1": "resolved_clean", "M2": "resolved_shadow", "M3": "pending"}


def test_recall_cross_manifest_events_ignored(regress_dir):
    """跨清单事件不干扰：M4 的拦截不把 M5 的召回判成 shadow。"""
    from history import recall_effectiveness
    _ev(regress_dir, "rule_recall", "M5", "2026-09-17T10:00:00", "test_failed")
    _ev(regress_dir, "commit_blocked", "M4", "2026-09-17T10:01:00", "x")
    _ev(regress_dir, "commit_passed", "M4", "2026-09-17T10:02:00")
    _ev(regress_dir, "commit_passed", "M5", "2026-09-17T10:03:00")
    rows = recall_effectiveness(regress_dir)
    assert rows[0]["manifest_id"] == "M5" and rows[0]["outcome"] == "resolved_clean"


def test_nudge_keys_isolated(regress_dir):
    """不同 reason 不互相污染分母——键=(manifest_id, reason)。"""
    from history import nudge_effectiveness
    _block(regress_dir, "R1", "a", "s1", "2026-09-16T10:00:00")
    _block(regress_dir, "R1", "b", "s1", "2026-09-16T10:30:00")
    rows = nudge_effectiveness(regress_dir)
    assert all(r["blocks"] == 1 for r in rows) and len(rows) == 2


# ─── v1.62 拦截热力图（B7：召回扩点的数据接口） ────────

def test_block_heatmap_ranking(regress_dir):
    """按频次降序，含清单数与最近时间；reason 缺失归 unknown。"""
    from history import block_heatmap
    _block(regress_dir, "R1", "test_failed", "s1", "2026-09-17T10:00:00")
    _block(regress_dir, "R2", "test_failed", "s1", "2026-09-17T11:00:00")
    _block(regress_dir, "R1", "untracked_files", "s1", "2026-09-17T12:00:00")
    rows = block_heatmap(regress_dir)
    assert rows[0]["reason"] == "test_failed" and rows[0]["blocks"] == 2
    assert rows[0]["manifests"] == 2 and rows[0]["last"].startswith("2026-09-17T11")
    assert rows[1]["reason"] == "untracked_files" and rows[1]["blocks"] == 1


def test_block_heatmap_empty(regress_dir):
    """无拦截：空表不炸。"""
    from history import block_heatmap
    assert block_heatmap(regress_dir) == []


# ─── v1.74 遥测双文件统一视图（063） ────────────────

def test_telemetry_both_files(tmp_path):
    rd = tmp_path / ".regress"
    (rd / "journal").mkdir(parents=True)
    (rd / "history.jsonl").write_text(
        '{"timestamp": "2026-09-20T10:00:00", "event": "commit_passed"}\n',
        encoding="utf-8")
    (rd / "journal" / "events.jsonl").write_text(
        '{"ts": "2026-09-20T10:01:00", "kind": "task_done"}\n', encoding="utf-8")
    t = telemetry(str(rd))
    assert t["history"]["events"] == 1 and t["history"]["last"] == "commit_passed"
    assert t["history"]["fields"] == "event/timestamp"
    assert t["journal"]["events"] == 1 and t["journal"]["last"] == "task_done"
    assert t["journal"]["fields"] == "kind/ts"


def test_telemetry_missing_journal(tmp_path):
    rd = tmp_path / ".regress"
    rd.mkdir()
    t = telemetry(str(rd))
    assert t["history"]["missing"] is True and t["journal"]["missing"] is True
