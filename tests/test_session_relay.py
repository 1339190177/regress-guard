"""session_relay 会话身份中继（v1.34）+ 批218 my_sids 身份集合。"""
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import session_relay  # noqa: E402


# ─── 批218：双 id 工件根治——env∪新鲜 relay 身份集合 ───

def test_my_sids_union_env_and_fresh_relay(tmp_path, monkeypatch):
    """env 旧号 + relay 新鲜新号 → 集合含两者（守卫判等两源任一命中即自己）。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "old-shell-id")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "sess-new-real", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    ids = session_relay.my_sids(str(tmp_path))
    assert ids == {"old-shell-id", "sess-new-real"}


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
