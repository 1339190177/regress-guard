"""execution_valve（公理四：执行阀/令牌制）的单元测试。"""
import sys
import os
import json
import subprocess

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
sys.path.insert(0, os.path.abspath(LIB))

from execution_valve import evaluate, TOKEN  # noqa: E402

VALVE = os.path.abspath(os.path.join(LIB, "execution_valve.py"))
PROJ = os.path.abspath(os.path.join(LIB, ".."))  # 插件根（动态推导，可移植）


def run_valve(command, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    inp = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["python3", VALVE], input=inp, capture_output=True, text=True,
        env=env, timeout=10,
    )
    return proc.returncode, proc.stderr


# ── 纯函数层 ──────────────────────────────────────────────

def test_catastrophic_patterns_block():
    for cmd in ["mkfs /dev/sda1", "dd if=/dev/zero of=/dev/sdb",
                "git push --force origin main", "git push -f",
                "DROP TABLE users", "DROP DATABASE prod", "TRUNCATE TABLE logs",
                "chmod -R 777 /var/www"]:
        assert evaluate(cmd, PROJ), f"应阻断: {cmd}"


def test_benign_commands_pass():
    for cmd in ["npm test", "git push origin main", "chmod 644 a.txt",
                "truncate this word", "rm -f single.txt",
                "rm -rf node_modules", "rm -rf /tmp/build-cache",
                f"rm -rf {PROJ}/tests"]:
        assert not evaluate(cmd, PROJ), f"不应阻断: {cmd}"


def test_rm_rf_outside_project_blocks():
    assert evaluate("rm -rf /usr/local/share", PROJ)
    assert evaluate("rm -rf ~/some-other-project", PROJ)
    assert evaluate("rm -rf /", PROJ)


def test_token_unlocks():
    assert not evaluate(f"{TOKEN} mkfs /dev/sda1", PROJ)
    assert not evaluate(f"{TOKEN} rm -rf /usr/local/share", PROJ)


def test_compound_command_caught():
    assert evaluate("cd /x && git push --force", PROJ)
    assert evaluate("echo hi; rm -rf /opt/data", PROJ)


def test_flag_variants_rm():
    assert evaluate("rm -fr /opt/data", PROJ)
    assert evaluate("rm -ravf /opt/data", PROJ)


def test_empty_and_nonbash_pass():
    assert evaluate("", PROJ) == []
    assert evaluate("ls -la | grep foo", PROJ) == []


# ── 进程层（stdin/exit code/关闭途径）───────────────────

def test_main_blocks_without_token():
    code, err = run_valve("mkfs /dev/sda1")
    assert code == 2
    assert "执行阀" in err and TOKEN in err


def test_main_allows_with_token():
    code, _ = run_valve(f"{TOKEN} mkfs /dev/sda1")
    assert code == 0


def test_main_env_kill_switch():
    code, _ = run_valve("mkfs /dev/sda1", {"REGRESS_VALVE": "off"})
    assert code == 0


def test_main_config_kill_switch(tmp_path):
    rdir = tmp_path / ".regress"
    rdir.mkdir()
    (rdir / "config.json").write_text('{"execution_valve": false}')
    code, _ = run_valve("mkfs /dev/sda1", {"ZCODE_PROJECT_DIR": str(tmp_path)})
    assert code == 0


def test_main_ignores_non_bash():
    env = dict(os.environ)
    inp = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
    proc = subprocess.run(["python3", VALVE], input=inp, capture_output=True,
                          text=True, env=env, timeout=10)
    assert proc.returncode == 0
