"""host_env 垫片单测（批166：dsh 桌面版支持）。"""
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)
from host_env import absorb_session, canonicalize_tool_names  # noqa: E402


def test_canonicalize_dsh_tool_names():
    """dsh 小写工具名→CC 形态（幂等；未知名/CC 名不动——C 档语义不猜）。"""
    p = {"tool_name": "edit", "tool_input": {"file_path": "a"}}
    assert canonicalize_tool_names(p)["tool_name"] == "Edit"
    assert canonicalize_tool_names({"tool_name": "bash"})["tool_name"] == "Bash"
    assert canonicalize_tool_names({"tool_name": "pwsh"})["tool_name"] == "Bash"
    assert canonicalize_tool_names({"tool_name": "read"})["tool_name"] == "Read"
    assert canonicalize_tool_names({"tool_name": "Bash"})["tool_name"] == "Bash"
    assert canonicalize_tool_names({"tool_name": "mystery"})["tool_name"] == "mystery"
    assert canonicalize_tool_names(None) is None  # 非 dict 直通


def _clear(monkeypatch):
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ZCODE_SESSION_ID", raising=False)


def test_absorb_sets_env_when_absent(tmp_path, monkeypatch):
    """dsh 桥形态：无 env + payload 带 session_id → 吸收生效。"""
    _clear(monkeypatch)
    sid = absorb_session({"session_id": "sess-dsh-abc", "tool_name": "Read"})
    assert sid == "sess-dsh-abc"
    assert os.environ["CLAUDE_SESSION_ID"] == "sess-dsh-abc"


def test_absorb_never_overwrites_existing(monkeypatch):
    """宿主明示的 env 优先（错归属比无归属糟——只补缺不覆盖）。"""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "host-given")
    sid = absorb_session({"session_id": "payload-sid"})
    assert sid == "host-given"
    assert os.environ["CLAUDE_SESSION_ID"] == "host-given"


def test_absorb_degrades_to_default(monkeypatch):
    """非 dict / 缺 session_id / 非字符串 → default（fail-open 垫片）。"""
    _clear(monkeypatch)
    assert absorb_session(None) == "default"
    assert absorb_session({"tool_name": "Read"}) == "default"
    assert absorb_session({"session_id": 12345}) == "default"


def test_absorb_zcode_env_still_wins(monkeypatch):
    """ZCode 形态（env 在场）不被 payload 扰动——双宿主各自成立。"""
    monkeypatch.setenv("ZCODE_SESSION_ID", "zcode-sess")
    _ = monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    sid = absorb_session({"session_id": "dsh-sess"})
    assert sid == "zcode-sess"
