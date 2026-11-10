"""session_relay 会话身份中继（v1.34）+ 批218 my_sids 身份集合。"""
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import session_relay  # noqa: E402


# ─── 批218 根治档：双源身份——冲突以 relay 真身为准（env 陈旧即弃） ───

def test_my_sids_conflict_relay_wins(tmp_path, monkeypatch):
    """双源不一致（env 旧号+relay 新鲜真身）→ 真身为准，env 陈旧即弃。

    REGRESS-261110-b9473428 根治判据：守卫判等不得再认 env 旧号——
    否则他清单误归属（旧号属历史会话）与对抗循环（绕 Edit 通道）复发。
    """
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "old-shell-id")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "sess-new-real", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    assert session_relay.my_sids(str(tmp_path)) == {"sess-new-real"}


def test_my_sids_single_source_agree(tmp_path, monkeypatch):
    """单源回归：env=relay 一致 → 既有行为零变化（同号单元素）。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "sess-same")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "sess-same", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    assert session_relay.my_sids(str(tmp_path)) == {"sess-same"}


def test_my_sids_relay_env_only_no_relay_id(tmp_path, monkeypatch):
    """relay 无 id（新会话冷启/中继缺失）→ 回退 env 源。"""
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "env-only-id")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {})
    assert session_relay.my_sids(str(tmp_path)) == {"env-only-id"}


def test_my_sids_relay_sid_env_empty(tmp_path, monkeypatch):
    """env 缺省 + relay 新鲜 → relay 即身份（钩子侧 Bash 进程常态）。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "sess-real-noenv", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    assert session_relay.my_sids(str(tmp_path)) == {"sess-real-noenv"}


def test_my_sids_stale_relay_excluded(tmp_path, monkeypatch):
    """relay 超新鲜窗（5min）=陈旧中继不再代言（会话切换后旧号失效）。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "old-shell-id")
    stale = (datetime.datetime.now() - datetime.timedelta(minutes=30)).isoformat(timespec="seconds")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {"sid": "sess-old-owner", "ts": stale})
    assert session_relay.my_sids(str(tmp_path)) == {"old-shell-id"}


def test_my_sids_empty_env_no_relay(tmp_path, monkeypatch):
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {})
    assert session_relay.my_sids(str(tmp_path)) == set()


def test_my_sids_bad_ts_relay_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "e1")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {"sid": "x", "ts": "not-a-time"})
    assert session_relay.my_sids(str(tmp_path)) == {"e1"}
