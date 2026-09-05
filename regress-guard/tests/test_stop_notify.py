"""授权门控轮末推送（v1.32）：授权词推送/非授权静音/冷却防双响。"""
import json
import os
import stat
import sys

import pytest

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
LIB = os.path.join(HERE, "lib")

sys.path.insert(0, HERE)
sys.path.insert(0, LIB)

import importlib.util as ilu

_sn_spec = ilu.spec_from_file_location("stop_notify", os.path.join(HERE, "stop_notify.py"))
sn = ilu.module_from_spec(_sn_spec)
_sn_spec.loader.exec_module(sn)


def _run_main():
    with pytest.raises(SystemExit) as e:
        sn.main()
    assert e.value.code in (0, None)


def _channel_stub(tmp_path, marker):
    stub = tmp_path / "stub.sh"
    stub.write_text("#!/bin/sh\necho \"$@\" >> %s\n" % marker, encoding="utf-8")
    stub.chmod(stat.S_IRWXU)
    return str(stub)


def _mk_proj(tmp_path, mach_channels):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True, exist_ok=True)
    mach = tmp_path / "machine.json"
    mach.write_text(json.dumps({"notify": {"channels": mach_channels}}), encoding="utf-8")
    return proj, mach


def test_autonomy_word_pushes(tmp_path, monkeypatch):
    proj, mach = _mk_proj(tmp_path, [_channel_stub(tmp_path, tmp_path / "m1") + " {title} {body}"])
    monkeypatch.setenv("RG_MACHINE_NOTIFY", str(mach))
    monkeypatch.setenv("ZCODE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("TMPDIR", str(tmp_path))  # 标记文件隔离（否则污染真机 /tmp）
    from prompt_intercept import save_prompt, _state_path
    save_prompt("继续，自决策。开启长程任务推演")
    _run_main()
    out = (tmp_path / "m1").read_text(encoding="utf-8")
    assert "阶段完成" in out and "自决策" in out


def test_normal_chat_also_pushes(tmp_path, monkeypatch):
    """v1.32.2 用户令：正常对话轮末也推（💬 回复完成形态），静音设计废弃。"""
    proj, mach = _mk_proj(tmp_path, [_channel_stub(tmp_path, tmp_path / "m2") + " {title} {body}"])
    monkeypatch.setenv("RG_MACHINE_NOTIFY", str(mach))
    monkeypatch.setenv("ZCODE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    from prompt_intercept import save_prompt
    save_prompt("正常的对话结束，也要发送给人类，通过企业微信")
    _run_main()
    out = (tmp_path / "m2").read_text(encoding="utf-8")
    assert "回复完成" in out and "正常的对话结束" in out
    assert "阶段完成" not in out  # 普通轮与授权轮形态可分辨


def test_cooldown_prevents_double_buzz(tmp_path, monkeypatch):
    proj, mach = _mk_proj(tmp_path, [_channel_stub(tmp_path, tmp_path / "m3") + " {title}"])
    monkeypatch.setenv("RG_MACHINE_NOTIFY", str(mach))
    monkeypatch.setenv("ZCODE_PROJECT_DIR", str(proj))
    from prompt_intercept import save_prompt
    save_prompt("继续，放手做")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert sn.should_notify("继续，放手做", cooled=True)
    sn._mark()  # 模拟刚推过（finish 仪式后 90s 内）
    _run_main()
    assert not (tmp_path / "m3").exists()  # 冷却期内不双响
    assert sn.should_notify("继续，放手做", cooled=False) is False
