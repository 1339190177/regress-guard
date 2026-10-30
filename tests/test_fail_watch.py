"""fail_watch 单测（批167：dsh 补位——失败自筛+沙箱感知状态目录）。"""
import io
import json
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "lib"))

import importlib.util as ilu  # noqa: E402

FW = os.path.join(LIB, "fail_watch.py")


def _fw(tmp_path, monkeypatch):
    spec = ilu.spec_from_file_location(f"fw-{id(tmp_path)}", FW)
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setenv("RG_STATE_DIR", str(tmp_path))  # 状态目录钉 tmp（env 覆盖位）
    return m


def _run(monkeypatch, tmp_path, payload):
    """进程内直调 main（stdin 打桩），返回该会话状态文件行数。"""
    m = _fw(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "fw-test-sess")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    try:
        m.main()
    except SystemExit as e:
        assert e.code in (0, None)
    st = tmp_path / "regress-guard-fails-fw-test-sess.jsonl"
    if not st.exists():
        return 0
    return sum(1 for _ in open(st, encoding="utf-8"))


def test_zcode_semantics_pass_through(monkeypatch, tmp_path):
    """ZCode 语义：无 tool_response 键=宿主已筛（PostToolUseFailure），直通记账。"""
    n = _run(monkeypatch, tmp_path, {"tool_name": "Bash",
                                     "tool_input": {"command": "pytest -x"}})
    assert n == 1


def test_dsh_session_id_absorbed(monkeypatch, tmp_path):
    """批167 补：payload session_id 吸收——dsh 侧观测状态按会话分文件
    （无此则 default 键跨会话合并，P2#17 同病理）。"""
    m = _fw(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ZCODE_SESSION_ID", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "sess-dsh-fw", "tool_name": "bash",
         "tool_input": {"command": "x"}, "tool_response": "Error: boom"})))
    try:
        m.main()
    except SystemExit as e:
        assert e.code in (0, None)
    assert (tmp_path / "regress-guard-fails-sess-dsh-fw.jsonl").exists()


def test_dsh_failure_shapes_recorded(monkeypatch, tmp_path):
    """dsh 失败归一化契约两形态：[exit code: N>0] 与 Error: 前缀 → 记账。"""
    n1 = _run(monkeypatch, tmp_path, {"tool_name": "bash",
                                      "tool_input": {"command": "pytest -x"},
                                      "tool_response": "boom\n[exit code: 3]"})
    n2 = _run(monkeypatch, tmp_path, {"tool_name": "edit",
                                      "tool_input": {"file_path": "a.py"},
                                      "tool_response": 'Error: cannot read "a.py": not found'})
    assert n1 == 1 and n2 == 2


def test_dsh_success_not_recorded(monkeypatch, tmp_path):
    """成功文本（exit 0 / 无 Error 前缀）不记账——PostToolUse 高频不噪音。"""
    n1 = _run(monkeypatch, tmp_path, {"tool_name": "bash",
                                      "tool_input": {"command": "ls"},
                                      "tool_response": "a b c\n[exit code: 0]"})
    n2 = _run(monkeypatch, tmp_path, {"tool_name": "bash",
                                      "tool_input": {"command": "echo ok"},
                                      "tool_response": "ok"})
    assert n1 == 0 and n2 == 0


def test_state_dir_rules(tmp_path, monkeypatch):
    """批167 终版三规则：env 覆盖 > 项目亲和（CLAUDE_PROJECT_DIR+.regress）> /tmp。"""
    import host_env
    # 规则1：RG_STATE_DIR 覆盖
    monkeypatch.setenv("RG_STATE_DIR", str(tmp_path / "o"))
    assert host_env.sandbox_aware_state_dir() == str(tmp_path / "o")
    monkeypatch.delenv("RG_STATE_DIR")
    # 规则2：接入项目（CLAUDE_PROJECT_DIR 且 .regress 在）→ 项目 .regress/tmp
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    d = host_env.sandbox_aware_state_dir()
    assert d == str(proj / ".regress" / "tmp") and os.path.isdir(d)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    # 规则3：无 env → gettempdir（旧语义，未接入调用面）
    import tempfile as tf
    monkeypatch.setattr(tf, "gettempdir", lambda: str(tmp_path / "legacy"))
    assert host_env.sandbox_aware_state_dir() == str(tmp_path / "legacy")


def test_hooks_cc_puts_fail_watch_on_post_tool_use(tmp_path):
    """hooks.cc 生成：fail_watch 复挂 PostToolUse（自筛位）且 matcher 展宽。"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import install_dsh as ids
    dest = ids.generate_hooks_cc(root=str(tmp_path))
    data = json.load(open(dest, encoding="utf-8"))
    cmds = [h["command"] for g in data["hooks"]["PostToolUse"] for h in g["hooks"]]
    assert any("fail_watch" in c for c in cmds)
    m = [g["matcher"] for g in data["hooks"]["PostToolUse"]
         if any("fail_watch" in h["command"] for h in g["hooks"])][0]
    import re
    assert re.search(m, "bash") and re.search(m, "edit")
    # ZCode 原位不动：PostToolUseFailure 仍保留
    assert any("fail_watch" in h["command"]
               for g in data["hooks"].get("PostToolUseFailure", []) for h in g["hooks"])
