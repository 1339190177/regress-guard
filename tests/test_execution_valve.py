"""execution_valve（公理四：执行阀/令牌制）的单元测试。"""
import sys
import tempfile
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
    # 密封（评审批次一活体标本）：门禁复验在钩子 env 下跑 pytest，
    # CLAUDE/ZCODE_PROJECT_DIR 指向真实工作区会抢在测试自设目录前被读——
    # 两个都显式覆盖，项目定位不由宿主环境决定
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("ZCODE_PROJECT_DIR", None)
    env.update(env_extra or {})
    inp = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        [sys.executable, VALVE], input=inp, capture_output=True, text=True, encoding="utf-8", errors="replace",
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
                "rm -rf node_modules", f"rm -rf {os.path.realpath(tempfile.gettempdir())}/build-cache",
                f"rm -rf {PROJ}/tests"]:
        assert not evaluate(cmd, PROJ), f"不应阻断: {cmd}"


def test_rm_rf_outside_project_blocks():
    assert evaluate("rm -rf /usr/local/share", PROJ)
    assert evaluate("rm -rf ~/some-other-project", PROJ)
    assert evaluate("rm -rf /", PROJ)


def test_token_unlocks():
    assert not evaluate(f"{TOKEN} mkfs /dev/sda1", PROJ)
    assert not evaluate(f"{TOKEN} rm -rf /usr/local/share", PROJ)


# ─── v1.90.1 载荷剥离（107：调试文本污染族 ×2 标本）─────────

def test_quoted_payload_words_do_not_trigger():
    """引号内是数据不是命令：grep 模式串/文案里的危险词不再拆弹。"""
    assert not evaluate("grep -n 'rm -rf\\|mkfs' docs/x.md", PROJ)
    assert not evaluate('echo "历史上 dd if= 的坑" >> notes.md', PROJ)
    assert not evaluate("rg \"git push --force 的教训\" .", PROJ)


def test_heredoc_body_words_do_not_trigger():
    """heredoc 体是文件内容：文档/测试代码里的危险词不拆。"""
    assert not evaluate(
        "cat >> docs/lesson.md << 'EOF'\n那次差点 DROP TABLE 的教训\nEOF",
        PROJ)


def test_interpreter_entry_still_scans_payload():
    """解释器入口例外：引号载荷真的会执行——照拆（顾问微修）。"""
    assert evaluate('bash -c "mkfs /dev/sda1"', PROJ)
    assert evaluate("sh -c 'rm -rf /usr/local/share'", PROJ)


def test_real_dangerous_still_blocks_after_strip():
    """剥离只放行载荷文本：未引号的真危险命令照拆（既有语义回归钉）。"""
    assert evaluate("mkfs /dev/sda1", PROJ)
    assert evaluate("dd if=/dev/zero of=/dev/sdb", PROJ)


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
    (rdir / "config.json").write_text('{"execution_valve": false}', encoding="utf-8")
    code, _ = run_valve("mkfs /dev/sda1", {"ZCODE_PROJECT_DIR": str(tmp_path)})
    assert code == 0


def test_main_ignores_non_bash():
    env = dict(os.environ)
    inp = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
    proc = subprocess.run([sys.executable, VALVE], input=inp, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env, timeout=10)
    assert proc.returncode == 0


# ─── P0-1c：非 dict 载荷 fail-closed（评审批次一） ─────────

def test_nondict_payload_blocks():
    """顶层非 dict JSON（字符串/数组）→ exit 2 阻断。

    旧行为：data.get 抛 AttributeError → exit 1 = 放行，与阀门语义相反
    （2026-09-08 评审 P0 活体路径）。"""
    for raw in ('"just a string"', "[1, 2, 3]"):
        proc = subprocess.run([sys.executable, VALVE], input=raw,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        assert proc.returncode == 2, f"{raw} 应阻断，得 {proc.returncode}"


# ─── 批193（公网 issue#2 P0-3）：PowerShell 灾难级 ───

def test_powershell_remove_item_blocked():
    """Remove-Item -Recurse -Force = 不可逆删除（Windows 用户报告：全放行）。"""
    import json as _json
    payload = _json.dumps({"tool_name": "Bash",
                           "tool_input": {"command": "Remove-Item -Recurse -Force C:\\data"}})
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2, f"Remove-Item -Recurse -Force 应被拦（rc={r.returncode}）"


def test_powershell_format_volume_blocked():
    payload_str = '{"tool_name":"Bash","tool_input":{"command":"Format-Volume -DriveLetter D"}}'
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload_str, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2


def test_powershell_rd_s_blocked():
    payload_str = '{"tool_name":"Bash","tool_input":{"command":"cmd /c rd /s /q D:\\\\data"}}'
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload_str, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2


def test_powershell_remove_item_no_recurse_passes():
    """无 -Recurse 或无 -Force 的 Remove-Item 不是灾难级（合法删单文件）。"""
    payload_str = '{"tool_name":"Bash","tool_input":{"command":"Remove-Item temp.txt"}}'
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload_str, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0


# ─── 批194（issue#2 遗留3）：del /s 与 Remove-Item -Recurse 无 -Force ───

def test_del_s_blocked():
    """cmd del /s /q = 递归强制删（只补 rd/rmdir 不够）。"""
    payload_str = '{"tool_name":"Bash","tool_input":{"command":"del /s /q D:\\\\data"}}'
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload_str, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2


def test_remove_item_recurse_only_blocked():
    """-Recurse 无 -Force 同样删空目录树（只读文件才中断）。"""
    payload_str = '{"tool_name":"Bash","tool_input":{"command":"Remove-Item -Recurse D:\\\\data"}}'
    import subprocess
    import sys
    import os
    r = subprocess.run([sys.executable, "-E",
                        os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "execution_valve.py")],
                       input=payload_str, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2


# ─── 批195（issue#2 第三轮）：递归删三方言目标判定（与 rm -rf 对称） ───

def test_ps_recursive_delete_project_internal_passes():
    """项目内递归删放行——与 rm -rf ./build 对称（第三轮主诉：五形态全误拦）。

    v2.8.2/3 把 Remove-Item -Recurse 直接进 CATASTROPHIC 无条件拦；dsh 在
    Windows 只投递 pwsh → build/dist/node_modules 日常清理全断，"每次带
    令牌"训练习惯性携带反而削弱令牌信号。"""
    for cmd in ("Remove-Item -Recurse -Force ./build",
                "Remove-Item -Recurse -Force build",
                "Remove-Item -Recurse -Force .\\dist",
                "Remove-Item -Recurse -Force node_modules",
                "Remove-Item -Recurse ./build",
                "rm -rf ./build"):  # POSIX 对照（对称性锚点）
        rc, _ = run_valve(cmd)
        assert rc == 0, f"{cmd} 项目内清理应放行（rc={rc}）"


def test_ps_recursive_delete_external_blocked():
    """项目外绝对路径递归删仍拦（保持 v2.8.2/3 拦截面不回退）。

    Linux 宿主上 C:\\Windows 走 win_form 字符串分支——宿主 abspath 会把它
    折进 cwd 成幻影"项目内"路径（假放行），故不走宿主 realpath。"""
    for cmd in ("Remove-Item -Recurse -Force C:\\Windows",
                "Remove-Item -Recurse -Force D:\\data",
                "Remove-Item -Recurse D:\\data",
                "Remove-Item -Recurse -Force -Path D:\\data"):
        rc, _ = run_valve(cmd)
        assert rc == 2, f"{cmd} 项目外应拦（rc={rc}）"


def test_ps_recursive_delete_drive_root_blocked():
    """盘符根递归删应拦（D:\\ 整盘）。"""
    rc, _ = run_valve("Remove-Item -Recurse -Force D:\\")
    assert rc == 2, f"盘符根应拦（rc={rc}）"


def test_ps_recursive_delete_named_path_internal_passes():
    """命名路径参数 -Path 项目内目标放行。"""
    rc, _ = run_valve("Remove-Item -Recurse -Force -Path build")
    assert rc == 0, f"-Path build 项目内应放行（rc={rc}）"


def test_ps_recursive_delete_tmp_zone_passes():
    """临时区递归删放行（与 rm -rf /tmp/x 对称）。"""
    rc, _ = run_valve("Remove-Item -Recurse -Force /tmp/dap-clean-195")
    assert rc == 0, f"临时区应放行（rc={rc}）"


def test_ps_recursive_delete_no_target_fail_closed():
    """无显式目标（管道输入形态）按拦——目标不可知不猜（fail-closed）。

    位置/命名参数形态不受影响；v2.8.3 该形态属无条件拦，此处不回退。"""
    rc, _ = run_valve("Get-ChildItem | Remove-Item -Recurse -Force")
    assert rc == 2, f"管道输入目标不可知应拦（rc={rc}）"


def test_ps_recursive_delete_var_target_worst_case_blocked():
    """变量目标（$env:TEMP\\x）展开不可知按最坏情形拦——POSIX rm -rf $VAR 同款语义。"""
    rc, _ = run_valve("Remove-Item -Recurse -Force $env:TEMP\\dap")
    assert rc == 2, f"变量展开不可知应按最坏拦（rc={rc}）"


def test_del_s_project_internal_passes():
    """cmd del /s 项目内放行（第三轮第二诉：.\\build 直接被拦）。"""
    rc, _ = run_valve("del /s /q .\\build")
    assert rc == 0, f"del /s /q 项目内应放行（rc={rc}）"


def test_del_s_external_blocked():
    """cmd del /s 项目外仍拦。"""
    rc, _ = run_valve("del /s /q E:\\data")
    assert rc == 2, f"del /s /q 项目外应拦（rc={rc}）"


def test_del_q_single_file_passes():
    """del /q 纯静默单文件删不递归——不算递归删（第三轮附带误拦修复）。"""
    rc, _ = run_valve("del /q temp.txt")
    assert rc == 0, f"del /q 单文件应放行（rc={rc}）"


def test_del_forward_slash_path_not_switch():
    """路径斜杠段（src/sub）不冒充 /s 开关——开关须独立成词（前置空白）。"""
    rc, _ = run_valve("del src/sub")
    assert rc == 0, f"路径斜杠段不是开关（rc={rc}）"


def test_win_dialect_judgment_unit():
    """win 方言单目标判定（真 Windows 宿主场景：project/tmp 均为 win 形态）。"""
    from execution_valve import _target_dangerous
    proj = "C:\\Users\\dev\\proj"
    tmp = "C:\\Users\\dev\\AppData\\Local\\Temp"
    ok = [  # 不危险
        "C:\\Users\\dev\\proj\\build",
        "c:\\users\\DEV\\proj\\BUILD",       # NTFS 大小写不敏感
        "C:\\Users\\dev\\AppData\\Local\\Temp\\dap-x",
        "c:/users/dev/proj/x",              # 正斜杠形态
        "build",                            # 相对=项目内
    ]
    bad = [
        "C:\\Windows",
        "D:/",                              # 盘符根
        "\\\\srv\\share",                    # UNC 根
    ]
    for t in ok:
        assert not _target_dangerous(t, proj, tmp), f"{t} 应放行"
    for t in bad:
        assert _target_dangerous(t, proj, tmp), f"{t} 应拦"
