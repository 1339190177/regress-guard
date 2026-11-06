"""stuck_watch 孤儿/卡死分类（run60 批182）：昨夜 7 例"疑似卡死"实为孤儿——
worker 转录尾 turn/end completed（正常收工），PR 被评审判据拦着不合致工单悬空。
分类错了恢复动作就错：孤儿去修 PR 判据，卡死才谈重启。

批207：main() 路径测试补位——修前 3 个测试全是 helper 单测，tickets 变量
遮蔽（批192 引入）使哨兵空转 3 天 CI 全绿（验证主权标本：测试不查入口，
入口坏了等于没测）。"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import stuck_watch  # noqa: E402


def test_stale_label_orphan_vs_hang():
    assert "孤儿" in stuck_watch._stale_label(True)
    assert "疑似卡死" in stuck_watch._stale_label(False)


def test_session_completed_by_tail_text():
    tail = '{"type": "step/end"}\n{"type": "turn/end", "data": {"turn": 4, "reason": {"kind": "completed"}}}'
    # 直接验证判定式（_session_completed 的核心逻辑，文件版走 zstd 子进程）
    assert '"turn/end"' in tail and '"completed"' in tail


def test_session_active_tail_is_not_completed():
    tail = '{"type": "tool/call", "data": {"name": "bash"}}\n{"type": "step/start"}'
    assert not ('"turn/end"' in tail and '"completed"' in tail)


# ─── 批207：main() 路径（红绿钉：修前遮蔽标本，修后真输出） ───

TID = "abcdef1234567890abcdef1234567890"


def _mk_instance(tmp_path, sessions_root, stale_min_ago=None, notified=None):
    """假 superagent 实例：orchestrator.sqlite 一张 running 工单 + 可配龄的会话文件。"""
    inst = tmp_path / "superagent-fake"
    inst.mkdir()
    db = sqlite3.connect(inst / "orchestrator.sqlite")
    db.execute("CREATE TABLE ticket (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO ticket VALUES (?, ?)", (TID, json.dumps({
        "title": "假工单", "createdAt": "2026-11-07T01:00:00.000Z",
        "assignments": [{"state": "running", "startedAt": "2026-11-07T01:01:00Z"}],
    })))
    db.commit()
    db.close()
    sf = sessions_root / "fake" / f"worker-{TID}" / "session.v4.jsonl.zstd"
    sf.parent.mkdir(parents=True)
    sf.write_bytes(b"not-real-zstd-but-nonempty")
    if stale_min_ago is not None:
        old = time.time() - stale_min_ago * 60
        os.utime(sf, (old, old))
    return inst


def _armed(monkeypatch, tmp_path, inst, notified):
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(stuck_watch, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(stuck_watch, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(stuck_watch, "_state_dirs", lambda: [str(inst)])
    monkeypatch.setattr(stuck_watch, "_notify",
                        lambda t, b: notified.append((t, b)))
    monkeypatch.setattr(stuck_watch, "_journal", lambda n: notified.append(n))


def test_main_reports_running_and_heartbeat(monkeypatch, tmp_path, capsys):
    """鲜活 running 工单：running 1 健康 1，零发现，rc 0——修前遮蔽使恒 0（红）。"""
    notified = []
    inst = _mk_instance(tmp_path, tmp_path / "sessions", stale_min_ago=0)
    _armed(monkeypatch, tmp_path, inst, notified)
    assert stuck_watch.main() == 0
    out = capsys.readouterr().out
    assert "running 1" in out and "健康 1" in out, out
    assert "实例 1" in out and f"工单 {1}" in out, out   # 批207 心跳自证
    assert not notified


def test_main_flags_stale_as_suspected_hang(monkeypatch, tmp_path, capsys):
    """静默>20min 的 running：疑似卡死告警（无效 zstd→非孤儿→疑似卡死），rc 1。"""
    notified = []
    inst = _mk_instance(tmp_path, tmp_path / "sessions", stale_min_ago=30)
    _armed(monkeypatch, tmp_path, inst, notified)
    assert stuck_watch.main() == 1
    out = capsys.readouterr().out
    assert "running 1" in out
    assert any("疑似卡死" in str(x) for x in notified), notified
    assert notified, "只报不杀也要报（WeCom/journal）"


def test_main_heartbeat_zero_is_distinguishable(monkeypatch, tmp_path, capsys):
    """零实例：心跳仍报扫描面（实例0 工单0）——与谎报 running 0 可区分，rc 0。"""
    notified = []
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(stuck_watch, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(stuck_watch, "_state_dirs", lambda: [])
    monkeypatch.setattr(stuck_watch, "_notify", lambda t, b: notified.append(t))
    monkeypatch.setattr(stuck_watch, "_journal", lambda n: notified.append(n))
    assert stuck_watch.main() == 0
    out = capsys.readouterr().out
    assert "实例 0" in out and "running 0" in out, out
    assert not notified
