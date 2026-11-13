"""session_relay 会话身份中继（v1.34）+ 批218 my_sids 身份集合。"""
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, os.path.abspath(LIB))
import session_relay  # noqa: E402


# ─── 批218 双源身份 → 批225（issue#8）payload 锚定+冲突不弃 env ───

def test_my_sids_conflict_union_not_discard_env(tmp_path, monkeypatch):
    """双源不一致 → 并集不弃 env（issue#8 主诉钉）。

    批218 根治档「冲突以 relay 真身为准 env 即弃」在 DSH 同项目多 agent
    会话反噬：relay 被他会话 2-5 分钟踩踏一次，真身 env 被弃→自己拦自己。
    「env 恒陈旧」是 ZCode 续接特例，不是两宿主通例。
    """
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "my-true-env")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "other-session-relay", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    assert session_relay.my_sids(str(tmp_path)) == {"my-true-env", "other-session-relay"}


def test_my_sids_payload_anchors_and_excludes_relay(tmp_path, monkeypatch):
    """批225：payload 在场=真身锚点——relay 退出判等（DSH 踩踏标本：
    他会话新鲜 relay 不得进集合=误放方向同修）。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "other-session", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    ids = session_relay.my_sids(str(tmp_path), payload_sid="payload-true")
    assert ids == {"payload-true"}


def test_my_sids_payload_unions_env_for_dual_id(tmp_path, monkeypatch):
    """批225：payload 新号 ∪ env 旧号——ZCode 续接双 id 形态两代清单皆自己
    （env 是自有谱系旧号，弃 env=双 id 自拦回归——顾问修正案不采纳的理由）。"""
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "old-shell-id")
    ids = session_relay.my_sids(str(tmp_path), payload_sid="sess-new-real")
    assert ids == {"sess-new-real", "old-shell-id"}


def test_my_sids_payload_with_relay_thrash_dsh(tmp_path, monkeypatch):
    """issue#8 端到端形态：DSH 多会话（env=A 真身+relay=B 踩踏）+载荷 A
    → 集合恰为 {A}（B 排除）——既不误拦自己也不误放他会话边界。"""
    import datetime
    monkeypatch.setattr(session_relay, "sid_from_env", lambda: "sess-A")
    monkeypatch.setattr(session_relay, "read_relay", lambda pd: {
        "sid": "sess-B", "ts": datetime.datetime.now().isoformat(timespec="seconds")})
    ids = session_relay.my_sids(str(tmp_path), payload_sid="sess-A")
    assert ids == {"sess-A"}


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
