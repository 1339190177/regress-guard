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


def run_guard(tool_command, project_dir, cwd=None, extra_env=None):
    """运行 guard，返回 (exit_code, stderr, stdout)。

    会话变量默认剥离（v1.34 活体标本：门禁复验在钩子 env 下跑 pytest，
    CLAUDE/ZCODE_SESSION_ID 泄漏进"无会话"用例→共享语义断言翻车）——
    需要会话身份的用例经 extra_env 显式注入，密封由构造保证。"""
    env = dict(os.environ)
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("ZCODE_SESSION_ID", None)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.update(extra_env or {})
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


# ─── 场景：会话作用域（v1.34）────────────────────────────

FOREIGN_SID = "sess-foreign-0001"
MY_SID = "sess-mine-00002"


def _stamp(project, mid, session):
    """给清单盖 session 戳（模拟 plan_approve 的转写）。"""
    mf = project / ".regress" / "manifests" / f"{mid}.md"
    text = mf.read_text()
    mf.write_text(text.replace("status:", f"session: {session}\nstatus:", 1))


def test_foreign_manifest_does_not_block_my_commit(project):
    """标本1 根治：他人 in-progress 清单不再挡我的提交（不涉文件即放行+警示）。"""
    _stamp(project, "R1", FOREIGN_SID)
    code, err, _ = run_guard("git commit -m x", project,
                             extra_env={"CLAUDE_SESSION_ID": MY_SID})
    assert code == 0
    assert "不涉本次提交文件" in err  # emit_warn：放行但留痕
    assert any(e.get("note") == "foreign_active_manifest_untouched"
               for e in read_history(project))


def test_foreign_manifest_undeclared_files_no_clash(project):
    """他有清单但没声明这些文件（planned 空）→ staged 文件不算撞，放行。"""
    _stamp(project, "R1", FOREIGN_SID)
    (project / "src" / "app.js").write_text("x = 2\n")
    import subprocess as sp
    sp.run(["git", "add", "-A"], cwd=str(project), check=True)
    code, err, _ = run_guard("git commit -m x", project,
                             extra_env={"CLAUDE_SESSION_ID": MY_SID})
    assert code == 0  # 空清单无声明文件 → 不构成集成态冲突


def test_foreign_clash_with_declared_file_blocks(project):
    """他清单显式声明 src/app.js，我 staged 同一文件 → 跨会话冲突拦截。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\nid: R1\nstatus: in-progress\nsession: %s\n"
        "planned_changes:\n  - id: F1\n    file: src/app.js\n    type: method-logic\n"
        "actual_changes: []\n---\n" % FOREIGN_SID)
    (project / "src" / "app.js").write_text("x = 2\n")
    import subprocess as sp
    sp.run(["git", "add", "-A"], cwd=str(project), check=True)
    code, err, _ = run_guard("git commit -m x", project,
                             extra_env={"CLAUDE_SESSION_ID": MY_SID})
    assert code == 2 and "跨会话" in err and "src/app.js" in err
    assert any(e.get("reason") == "cross_session_clash"
               for e in read_history(project))


def test_own_manifest_governs_despite_foreign(project):
    """我有清单 + 他有清单：按我的清单走（撞他文件才拦）——选择器不再拿别人清单。"""
    _stamp(project, "R1", FOREIGN_SID)  # R1 是他的
    (project / ".regress" / "manifests" / "R2.md").write_text(
        "---\nid: R2\nstatus: in-progress\nsession: %s\nplanned_changes: []\n"
        "actual_changes: []\n---\n" % MY_SID)
    code, err, _ = run_guard("git commit -m x", project,
                             extra_env={"CLAUDE_SESSION_ID": MY_SID})
    # 选中我的 R2（空清单无脆弱点）→ 走到无 runner 阻断，而不是被 R1 挡
    assert code == 2 and ("测试运行器" in err or "未检测到" in err)


def test_no_session_env_shares_all(project):
    """env 缺失（老钩子环境）：全部视为 mine——fail-safe 老行为不回退。"""
    _stamp(project, "R1", FOREIGN_SID)
    code, err, _ = run_guard("git commit -m x", project)  # 无会话 env
    assert code == 2 and ("测试运行器" in err or "未检测到" in err)


# ─── P0-1：fail-closed 行为锁（评审批次一） ──────────────

def test_non_utf8_manifest_blocks(project):
    """非 UTF-8 清单 → 阻断（不崩溃放行）。

    旧行为：UnicodeDecodeError 穿透无保护循环 → exit 1 = 放行
    （2026-09-08 评审 P0 活体路径）。修复后 errors="replace" 读入：
    替换字符若废掉关键字段 → 解析失败分支阻断；若只是注解位脏 →
    清单照常激活走正常门禁流（本用例 status 行完好 → no runner 阻断）。
    断言锁的是 fail-closed 契约：绝不 exit 0/1。"""
    (project / ".regress" / "manifests" / "R1.md").write_bytes(
        b"---\nid: R1\nstatus: in-progress\nnote: \xff\xfe\n---\nbody")
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 2, f"非 UTF-8 清单必须阻断（exit 2），得 {code}"


def test_garbage_yaml_manifest_blocks(project):
    """坏 YAML（手写 fallback 也拿不到任何字段）→ 阻断。

    旧行为：fallback 返回 {} 非 None → 判"无活跃清单"静默放行，
    与 fail-safe 注释方向相反。"""
    (project / ".regress" / "manifests" / "R1.md").write_text(
        "---\n: : : 乱写一气\n!@#$ 没有 id 也没有 status\n---\nbody")
    code, err, _ = run_guard("git commit -m x", project)
    assert code == 2
