"""history.py 的单元测试（含 Ch9 遗忘、Ch24 指标、Ch21 reason 分布）。"""
import sys
import os
import json
import tempfile
import pytest

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)

from history import record, load_history, summarize, _maybe_archive, build_trace


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


def test_commit_observed_counted(regress_dir):
    """git 观测事件计入 outside_gate_commits。"""
    record(regress_dir, "commit_observed", "", commit_sha="a1", subject="s", source="git-hook")
    record(regress_dir, "commit_passed", "R1", runner="jest")
    s = summarize(regress_dir)
    assert s["outside_gate_commits"] == 1


def test_observed_source_distinction(regress_dir):
    """来源区分：门禁放行(zcode-gated)不算未走门禁；直提/回填算。"""
    record(regress_dir, "commit_observed", "", commit_sha="g1", subject="s", source="zcode-gated")
    record(regress_dir, "commit_observed", "", commit_sha="g2", subject="s", source="zcode-bypass")
    record(regress_dir, "commit_observed", "", commit_sha="h1", subject="s", source="git-hook")
    record(regress_dir, "commit_observed", "", commit_sha="h2", subject="s", source="git-backfill")
    s = summarize(regress_dir)
    assert s["outside_gate_commits"] == 2  # 只有外部直提+回填
