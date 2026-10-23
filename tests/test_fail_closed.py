"""fail-closed 第二波（批135 波A）：崩溃/形态破坏语义的 subprocess 注入族。

钉死面：
- 非 dict / 畸形 JSON / tool_input 非 dict → exit 2（boundary/rbe/valve/gate）
  （旧行为：AttributeError traceback → exit 1 → 宿主放行 = 编辑穿界/阀门失守）
- 真崩溃注入（闭合 fd 0 → sys.stdin=None → isatty AttributeError）→ exit 2
  ——验证的是 __main__ 兜底本身，非 mock（验证位=运行位：subprocess 直跑脚本）
- 逃生阀在崩溃路径可达（顾问前置条件）：bypass 窗口/config 关闭项 → exit 0
  ——赦免判定只读 env+config，不碰载荷解析

已知残余（不在本族断言，见 WORKFLOW/decisions）：模块级 import 崩溃
（如 PYTHONPATH 投毒）发生在 __main__ 兜底之前 → exit 1 = fail-open；
对策=注册面 python3 -E（忽略 PYTHON* env）+ health_probe 钩子探针可见性。
"""
import json
import os
import subprocess
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
LIB = os.path.abspath(LIB)
BOUNDARY = os.path.join(LIB, "boundary_guard.py")
RBE = os.path.join(LIB, "read_before_edit_guard.py")
VALVE = os.path.join(LIB, "execution_valve.py")
GUARD = os.path.join(LIB, "pre_commit_guard.py")


def _run(script, raw, argv=None, project=None, env_extra=None):
    env = dict(os.environ)
    # 密封：项目定位不由宿主环境决定（test_execution_valve 同款惯例）
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("ZCODE_PROJECT_DIR", None)
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    env.update(env_extra or {})
    proc = subprocess.run(
        ["python3", script] + (argv or []), input=raw, capture_output=True,
        text=True, env=env, timeout=15,
    )
    return proc.returncode, proc.stderr


def _mk_project(tmp_path, config=None):
    p = tmp_path / "proj"
    (p / ".regress" / "manifests").mkdir(parents=True)
    if config is not None:
        (p / ".regress" / "config.json").write_text(
            json.dumps(config), encoding="utf-8")
    return p


# ─── 非dict / 畸形 JSON：统一拦截（顾问裁决②） ────────────

def test_boundary_nondict_blocks(tmp_path):
    code, err = _run(BOUNDARY, "[1, 2, 3]", project=_mk_project(tmp_path))
    assert code == 2
    assert "fail-closed" in err and "bypass" in err


def test_boundary_malformed_blocks(tmp_path):
    code, err = _run(BOUNDARY, "{not valid json]", project=_mk_project(tmp_path))
    assert code == 2
    assert "fail-closed" in err


def test_boundary_tool_input_nondict_blocks(tmp_path):
    raw = json.dumps({"tool_name": "Edit", "tool_input": "not-an-object"})
    code, err = _run(BOUNDARY, raw, project=_mk_project(tmp_path))
    assert code == 2
    assert "fail-closed" in err


def test_rbe_nondict_blocks(tmp_path):
    code, err = _run(RBE, '"just a string"', argv=["pre"],
                     project=_mk_project(tmp_path))
    assert code == 2
    assert "fail-closed" in err


def test_rbe_malformed_blocks(tmp_path):
    code, err = _run(RBE, "{bad json", argv=["pre"],
                     project=_mk_project(tmp_path))
    assert code == 2


def test_valve_nondict_blocks_with_message():
    """P0-1c 只断言 exit 2；批135 补块说明（stderr 无理由=模型盲拦）。"""
    code, err = _run(VALVE, '"just a string"')
    assert code == 2
    assert "fail-closed" in err


def test_valve_malformed_blocks():
    code, _ = _run(VALVE, "{bad json")
    assert code == 2


def test_gate_malformed_blocks():
    """is_git_commit 收窄：畸形 JSON 上抛进 P0-1a 全局兜底（旧=吞错放行）。"""
    code, err = _run(GUARD, "{bad json")
    assert code == 2
    assert "fail-safe" in err


# ─── 真崩溃注入：闭合 fd 0 → sys.stdin=None → __main__ 兜底 ──

def _run_closed_stdin(script, project=None):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("ZCODE_PROJECT_DIR", None)
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    quoted = " ".join(f"'{a}'" for a in (script,))
    proc = subprocess.run(
        ["bash", "-c", f"python3 {quoted} 0<&-"],
        capture_output=True, text=True, env=env, timeout=15,
    )
    return proc.returncode, proc.stderr


def test_boundary_internal_crash_blocks(tmp_path):
    code, err = _run_closed_stdin(BOUNDARY, project=_mk_project(tmp_path))
    assert code == 2, "未捕获异常必须拦（旧行为 traceback exit 1 = 放行）"
    assert "fail-closed" in err


def test_rbe_internal_crash_blocks(tmp_path):
    code, err = _run_closed_stdin(RBE, project=_mk_project(tmp_path))
    assert code == 2
    assert "fail-closed" in err


def test_valve_internal_crash_blocks():
    code, err = _run_closed_stdin(VALVE)
    assert code == 2
    assert "fail-closed" in err


# ─── 逃生阀在崩溃路径可达（顾问前置条件） ────────────────

def test_boundary_bypass_window_rescues_crash(tmp_path):
    """bypass 窗口内 + 非 dict 载荷 → exit 0：赦免不依赖载荷解析。"""
    p = _mk_project(tmp_path, config={"bypass_until": "2099-01-01T00:00:00"})
    code, _ = _run(BOUNDARY, "[1, 2, 3]", project=p)
    assert code == 0


def test_boundary_disabled_config_rescues_crash(tmp_path):
    p = _mk_project(tmp_path, config={"boundary_enforced": False})
    code, _ = _run(BOUNDARY, "{bad json", project=p)
    assert code == 0


def test_rbe_ratio_zero_rescues_crash(tmp_path):
    p = _mk_project(tmp_path, config={"read_before_edit_ratio": 0})
    code, _ = _run(RBE, "[1, 2, 3]", argv=["pre"], project=p)
    assert code == 0


def test_valve_disabled_config_rescues_crash(tmp_path):
    p = _mk_project(tmp_path, config={"execution_valve": False})
    code, _ = _run(VALVE, '"str"', project=p)
    assert code == 0
