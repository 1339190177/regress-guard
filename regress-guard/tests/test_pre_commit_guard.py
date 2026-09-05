"""pre_commit_guard.py 主流程的端到端测试。

历史上 4 个 bug 都出在这个文件（||吞输出、completed终态、monorepo路径、
no_active_manifest不记录），却没有单元测试。本文件把手工验证固化为可回归。
"""
import sys
import os
import json
import subprocess
import pytest

GUARD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "scripts", "pre_commit_guard.py"))


def run_guard(tool_command, project_dir, cwd=None):
    """运行 guard，返回 (exit_code, stderr, stdout)。"""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    inp = json.dumps({"tool_name": "Bash", "tool_input": {"command": tool_command}})
    proc = subprocess.run(
        ["python3", GUARD],
        input=inp, capture_output=True, text=True,
        env=env, cwd=str(cwd or project_dir), timeout=30
    )
    return proc.returncode, proc.stderr, proc.stdout


@pytest.fixture
def project(tmp_path):
    """标准测试项目：git 仓库 + .regress + 活跃清单。"""
    import subprocess as sp
    p = tmp_path / "proj"
    p.mkdir()
    sp.run(["git", "init", "-q"], cwd=str(p), check=True)
    sp.run(["git", "config", "user.email", "t@t.com"], cwd=str(p), check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=str(p), check=True)
    (p / "src").mkdir()
    (p / "src" / "app.js").write_text("x = 1\n")
    sp.run(["git", "add", "-A"], cwd=str(p), check=True)
    sp.run(["git", "commit", "-q", "-m", "init"], cwd=str(p), check=True)

    rg = p / ".regress"
    (rg / "manifests").mkdir(parents=True)
    (rg / "config.json").write_text('{"strict": true}')
    (rg / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: in-progress\nplanned_changes: []\nactual_changes: []\n---\n"
    )
    return p


def read_history(project):
    events = []
    hf = project / ".regress" / "history.jsonl"
    if hf.exists():
        for line in hf.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


# ─── 场景：命令识别 ────────────────────────────────────

def test_non_commit_command_passes(project):
    """非 git commit 命令直接放行，不记录。"""
    code, err, _ = run_guard("ls -la", project)
    assert code == 0
    assert read_history(project) == []


def test_commit_via_npm_version_detected(project):
    """npm version 会自动 commit，必须被识别为提交类命令。"""
    code, err, _ = run_guard("npm version patch", project)
    # 无测试运行器 + 清单非终态 → 阻断（说明被识别到了）
    assert code == 2
    assert "测试运行器" in err or "未检测到" in err


# ─── 场景：fail-safe ──────────────────────────────────

def test_corrupt_config_blocks(project):
    """config.json 损坏 → fail-safe 阻断。"""
    (project / ".regress" / "config.json").write_text("not json")
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 2
    assert "config.json" in err


def test_corrupt_manifest_blocks(project):
    """清单格式损坏（无 frontmatter）→ fail-safe 阻断。"""
    (project / ".regress" / "manifests" / "R1.md").write_text("不是合法的清单")
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 2
    assert "清单" in err or "frontmatter" in err


# ─── 场景：F3 拦截与终态放行 ────────────────────────────

def test_untracked_file_blocks_and_records(project):
    """staged 文件不在清单 → 阻断 + 记录 untracked_files。"""
    import subprocess as sp
    (project / "src" / "rogue.js").write_text("y = 2\n")
    sp.run(["git", "add", "-A"], cwd=str(project), check=True)
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 2
    assert "rogue.js" in err
    events = read_history(project)
    assert any(e["event"] == "commit_blocked"
               and e.get("reason") == "untracked_files" for e in events)


def test_terminal_status_passes_without_runner(project):
    """清单 status=done 且无测试运行器 → 放行 + 记录。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: done\nplanned_changes: []\n---\n"
    )
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 0
    events = read_history(project)
    assert any(e["event"] == "commit_passed" for e in events)


def test_completed_is_terminal(project):
    """completed 与 done 同为终态（历史 bug 回归测试）。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: completed\nplanned_changes: []\n---\n"
    )
    code, _, _ = run_guard("git commit -m x", project)
    assert code == 0


# ─── 场景：monorepo 向上查找（历史 bug 回归）────────────

def test_monorepo_finds_parent_regress(project, tmp_path):
    """git 仓库在子目录、.regress 在父目录 → 仍能找到。"""
    parent = tmp_path / "monorepo"
    parent.mkdir()
    rg = parent / ".regress"
    (rg / "manifests").mkdir(parents=True)
    (rg / "config.json").write_text('{"strict": true}')
    (rg / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: in-progress\nplanned_changes: []\n---\n"
    )
    # 把 git 项目移进 monorepo 子目录
    sub = parent / "server"
    sub.mkdir()
    import subprocess as sp, shutil
    for item in os.listdir(project):
        shutil.move(str(project / item), str(sub / item))

    code, err, _ = run_guard("git commit -m x", parent, cwd=sub)
    # 找到了清单（in-progress 无 runner）→ 阻断，证明 monorepo 查找成功
    assert code == 2
    assert read_history(parent), "history 应记录到父目录的 .regress"


def test_no_regress_dir_passes(tmp_path):
    """无 .regress/ 的项目 → 放行（不强制未接入项目）。"""
    code, _, _ = run_guard("git commit -m x", tmp_path)
    assert code == 0


# ─── 场景：证据链锚点 ─────────────────────────────────

def test_commit_event_has_anchors(project):
    """放行事件必须含 session_id 证据锚点。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: done\nplanned_changes: []\n---\n"
    )
    code, _, _ = run_guard("git commit -m x", project)
    assert code == 0
    events = read_history(project)
    passed = [e for e in events if e["event"] == "commit_passed"]
    assert passed and "session_id" in passed[0]


def test_invented_status_not_active(project):
    """语义反转回归：AI 自造 status（analysis-done）不算活跃，不卡提交。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: analysis-done\nplanned_changes: []\n---\n"
    )
    code, _, _ = run_guard("git commit -m x", project)
    assert code == 0
    events = read_history(project)
    assert any(e.get("note") == "no_active_manifest" for e in events)


def test_active_manifest_blocks_without_runner(project):
    """明确活跃清单 + 无 runner → 阻断（而非旧的终态表误放行/误卡）。"""
    code, err, _ = run_guard("git commit -m x", project)  # project 清单是 in-progress
    assert code == 2 and ("测试运行器" in err or "未检测到" in err)
