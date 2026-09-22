"""read_before_edit_guard 的单元测试。"""
import sys
import os
import json
import subprocess
import tempfile

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts")
sys.path.insert(0, LIB)

GUARD = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts",
                     "read_before_edit_guard.py")
GUARD = os.path.abspath(GUARD)
import read_before_edit_guard  # noqa: E402  状态路径单一来源


def _state_file_for(session_id):
    """按目标会话算状态文件路径（P2#17 后路径含会话哈希——pytest 进程自身
    没有会话 env，直接调 get_state_path 会算到 default 的文件=清错对象）。"""
    old = os.environ.get("CLAUDE_SESSION_ID")
    os.environ["CLAUDE_SESSION_ID"] = session_id
    try:
        return read_before_edit_guard.get_state_path()
    finally:
        if old is None:
            os.environ.pop("CLAUDE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_SESSION_ID"] = old


def run_guard(mode, tool_name, file_path, session_id="test-unit", project_dir=None):
    """运行 guard 脚本，返回 (exit_code, stderr)。"""
    env = dict(os.environ)
    env["CLAUDE_SESSION_ID"] = session_id
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    inp = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": file_path}})
    proc = subprocess.run(
        ["python3", GUARD, mode],
        input=inp, capture_output=True, text=True, env=env, timeout=10
    )
    return proc.returncode, proc.stderr


def cleanup(session_id="test-unit"):
    """清理测试状态（按目标会话的文件清，不再是旧全局文件）。"""
    state_file = _state_file_for(session_id)
    try:
        with open(state_file, encoding="utf-8") as f:
            state = json.load(f)
        state.pop(session_id, None)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except (IOError, json.JSONDecodeError):
        pass


def test_blind_edit_blocked():
    """直接改（0 读）应被拦。"""
    cleanup()
    code, err = run_guard("pre", "Edit", "src/app.js")
    assert code == 2, f"盲改应被拦，exit={code}"
    assert "先读后改" in err
    cleanup()


def test_read_then_edit_allowed():
    """读 2 次后改 1 次应放行（ratio 默认 2）。"""
    cleanup()
    for f in ["src/a.js", "src/b.js"]:
        run_guard("post", "Read", f)
    code, _ = run_guard("pre", "Edit", "src/app.js")
    assert code == 0, f"读够后应放行，exit={code}"
    cleanup()


def test_partial_read_blocked():
    """只读 1 次（差 1 次）应被拦。"""
    cleanup()
    run_guard("post", "Read", "src/a.js")
    code, err = run_guard("pre", "Edit", "src/app.js")
    assert code == 2, f"读不够应拦截，exit={code}"
    cleanup()


def test_new_file_exempt():
    """Write 不存在的文件应豁免。"""
    cleanup()
    code, _ = run_guard("pre", "Write", "/nonexistent/path/new.js")
    assert code == 0, f"新文件应豁免，exit={code}"
    cleanup()


def test_regress_files_exempt():
    """写 .regress/ 下的文件应豁免。"""
    cleanup()
    code, _ = run_guard("pre", "Write", ".regress/config.json")
    assert code == 0, f".regress/ 应豁免，exit={code}"
    cleanup()


def test_ratio_zero_disables(tmp_path):
    """ratio=0 时关闭门禁。"""
    cleanup()
    rdir = tmp_path / ".regress"
    rdir.mkdir()
    (rdir / "config.json").write_text('{"read_before_edit_ratio": 0}')
    code, _ = run_guard("pre", "Edit", "src/app.js",
                        project_dir=str(tmp_path),
                        session_id="test-ratio0")
    assert code == 0, f"ratio=0 应放行，exit={code}"
    cleanup("test-ratio0")


def test_no_spiral_v1120():
    """v1.92.0（111，野外 F1）无螺旋证明：改 1 次后改第 2 个未读文件——
    旧语义 required=(1+1)*2=4>3 会拦（死亡螺旋第一格）；新语义 bootstrap
    已满足（3 读 ≥ N=2）→ 放行+软提示，需求不随编辑数增长。"""
    cleanup()
    for f in ["a", "b", "c"]:
        run_guard("post", "Read", f"src/{f}.js")
    run_guard("pre", "Edit", "src/app.js")  # 第 1 次改通过
    code, err = run_guard("pre", "Edit", "src/other.js")  # 第 2 次改（未读）
    assert code == 0, f"第 2 次改不应再被累计比例拦，exit={code}"
    assert "hint" in err or "建议先 Read" in err  # 软提示在场
    cleanup()


def test_long_session_no_growth():
    """百次重复编辑后改新文件：需求仍只有 bootstrap（无螺旋的极限证明）。"""
    cleanup()
    for f in ["src/a.js", "src/b.js"]:
        run_guard("post", "Read", f)
    for i in range(100):
        run_guard("pre", "Edit", "src/a.js")  # 已读文件迭代改 ×100
    code, err = run_guard("pre", "Edit", "src/brand-new.js")
    assert code == 0, f"百次编辑后改新文件不应需求增长，exit={code}"
    cleanup()


def test_edit_already_read_file_exempt():
    """改一个已读过的文件应豁免（允许迭代修改同一文件）。"""
    cleanup()
    # 读 src/app.js + 2 个依赖
    for f in ["src/app.js", "src/utils.js", "src/config.js"]:
        run_guard("post", "Read", f)
    # 第 1 次改 app.js 通过
    code1, _ = run_guard("pre", "Edit", "src/app.js")
    assert code1 == 0, f"第 1 次改应通过，exit={code1}"
    # 第 2 次改同一个 app.js → 应豁免（已读过）
    code2, _ = run_guard("pre", "Edit", "src/app.js")
    assert code2 == 0, f"同文件已读应豁免，exit={code2}"
    # 第 3 次改还是 app.js → 仍豁免
    code3, _ = run_guard("pre", "Edit", "src/app.js")
    assert code3 == 0, f"同文件多次改应豁免，exit={code3}"
    cleanup()


def test_edit_unread_after_bootstrap_soft_hint():
    """v1.92.0：读了 a/b/c（bootstrap 满）改未读的 d → 放行+软提示不拦
    （旧语义此处 required=(1+1)*2=4>3 拦——判据链已换，per-file 为主）。"""
    cleanup()
    for f in ["src/a.js", "src/b.js", "src/c.js"]:
        run_guard("post", "Read", f)
    run_guard("pre", "Edit", "src/a.js")  # 第 1 次改通过（a 已读豁免）
    code, err = run_guard("pre", "Edit", "src/d.js")  # 改未读的 d
    assert code == 0, f"bootstrap 满足后改未读文件应放行，exit={code}"
    assert "src/d.js" in err and "建议先 Read" in err  # 软提示点名目标
    cleanup()


def test_bootstrap_floor_blocks_blind_dive():
    """开局盲潜：读了 1 个（< N=2）改另一个未读文件 → 拦（防盲潜地板）。"""
    cleanup()
    run_guard("post", "Read", "src/a.js")  # 仅 1 读
    code, err = run_guard("pre", "Edit", "src/d.js")  # 改未读的 d
    assert code == 2, f"开局盲潜应拦，exit={code}"
    assert "盲潜" in err
    cleanup()


# ── 文件指纹（公理二：每一粒灰尘都必须对得上）──────────

def _bump_mtime_ns(path, delta_ns=2 * 10**9):
    """确定性改 mtime（避免同纳秒竞态）：读现值 +delta 写回。"""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns + delta_ns, st.st_mtime_ns + delta_ns))


def test_fingerprint_blocks_external_change(tmp_path):
    """读后被外部修改（另一会话/git/格式化）→ 禁止盲改。"""
    cleanup()
    f = tmp_path / "app.js"
    f.write_text("let a = 1\n")
    fp = str(f)
    run_guard("post", "Read", fp)          # 采集指纹
    _bump_mtime_ns(fp)                      # 模拟外部修改
    code, err = run_guard("pre", "Edit", fp)
    assert code == 2, f"指纹不匹配应阻断, exit={code}"
    assert "指纹" in err
    cleanup()


def test_fingerprint_reread_restores(tmp_path):
    """被拦后重新 Read（刷新指纹）→ 放行。"""
    cleanup()
    f = tmp_path / "app.js"
    f.write_text("let a = 1\n")
    fp = str(f)
    run_guard("post", "Read", fp)
    _bump_mtime_ns(fp)
    assert run_guard("pre", "Edit", fp)[0] == 2   # 拦
    run_guard("post", "Read", fp)                  # 重读刷新
    assert run_guard("pre", "Edit", fp)[0] == 0    # 放行
    cleanup()


def test_fingerprint_unchanged_allows(tmp_path):
    """读后没动过 → 指纹一致 → 放行。"""
    cleanup()
    f = tmp_path / "app.js"
    f.write_text("let a = 1\n")
    fp = str(f)
    run_guard("post", "Read", fp)
    assert run_guard("pre", "Edit", fp)[0] == 0
    cleanup()


def test_self_edit_suspends_fingerprint(tmp_path):
    """自己改完再改（未重读）→ 哨兵挂起校验，不误拦。"""
    cleanup()
    f = tmp_path / "app.js"
    f.write_text("let a = 1\n")
    fp = str(f)
    run_guard("post", "Read", fp)
    run_guard("pre", "Edit", fp)           # 自己改 → sentinel
    f.write_text("let a = 2\n")            # 内容变了（mtime 变）
    # 未重读但已在本会话 read_files 里 → 豁免路径 + sentinel 挂起 → 放行
    assert run_guard("pre", "Edit", fp)[0] == 0
    cleanup()


def test_fingerprint_only_checked_for_real_files(tmp_path):
    """指纹校验对从未 Read 过的文件不生效（走 ratio 门禁，互不干扰）。"""
    cleanup()
    # 0 读直接改 → 走先读后改门禁（不是指纹拦截）
    code, err = run_guard("pre", "Edit", str(tmp_path / "never-read.js"))
    assert code == 2
    assert "先读后改" in err
    cleanup()
