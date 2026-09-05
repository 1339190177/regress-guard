"""prompt_intercept / reflection_check 行为测试。

覆盖三件事：
  1. 纠错检测——"自信地错"没有失败信号，用户纠正词是唯一探测器
  2. 摆渡包自组装——轮内失败 ≥3 时注入失败清单原文 + git diff --stat
  3. 卡死计数与纠错的互不干扰——纠正是实质输入，会重置催促计数
"""
import json
import os
import sys
import tempfile
from datetime import datetime

import pytest

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import prompt_intercept  # noqa: E402
import reflection_check  # noqa: E402
import fail_watch  # noqa: E402


@pytest.fixture
def isolated_tmp(monkeypatch, tmp_path):
    """把所有 /tmp 状态文件重定向到测试沙箱（hook 路径函数每次动态取 gettempdir）。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


# ── 1. 纠错检测 ──

def _correction_reminders(text):
    return [r for r in prompt_intercept.analyze_prompt(text) if "纠正" in r]


def test_correction_direction_wrong(isolated_tmp):
    rs = _correction_reminders("不对，你这个方案方向错了，重新想")
    assert len(rs) == 1
    assert "自信地错" in rs[0]
    assert "consult" in rs[0]


def test_correction_understanding_wrong(isolated_tmp):
    assert _correction_reminders("你理解错了，我说的是另一个文件") != []


def test_correction_english(isolated_tmp):
    assert _correction_reminders("wrong direction, try again") != []


def test_error_report_is_not_correction(isolated_tmp):
    """“报错了/出错了”是描述工具报错，不是纠正 AI 方向。"""
    assert _correction_reminders("程序运行报错了，看一下日志排查") == []
    assert _correction_reminders("刚才那条命令出错了") == []


def test_normal_request_no_correction(isolated_tmp):
    assert _correction_reminders("帮我把登录页的按钮改成蓝色，加个圆角") == []


# ── 2. 摆渡包自组装 ──

def _write_fails(n, sig="pnpm test"):
    path = fail_watch.state_path()
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(n):
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "tool": "Bash",
                "sig": sig,
            }, ensure_ascii=False) + "\n")


def test_ferry_package_assembled(isolated_tmp, tmp_path):
    """>=3 次失败 → 注入含失败清单原文 + 摆渡指令，而非口头嘱咐。"""
    project = tmp_path / "proj"
    (project / ".regress").mkdir(parents=True)
    _write_fails(4, "pnpm install")
    reminders = reflection_check.check_context(str(project))
    assert reminders, "应产生摆渡注入"
    ferry = "\n".join(reminders)
    assert "失败清单" in ferry
    assert "pnpm install ×4" in ferry, "失败签名原文必须在场（禁止 AI 二次过滤）"
    assert "禁止原样重试" in ferry
    assert "摆渡" in ferry


def test_ferry_below_threshold_no_trigger(isolated_tmp, tmp_path):
    """2 次失败不触发（容忍偶发失败）。"""
    project = tmp_path / "proj"
    (project / ".regress").mkdir(parents=True)
    _write_fails(2)
    reminders = reflection_check.check_context(str(project))
    assert not reminders, "低于阈值不应有失败注入"


def test_ferry_no_regress_not_connected(isolated_tmp, tmp_path):
    """未接入 .regress 的项目：即使失败也不注入。"""
    _write_fails(5)
    assert reflection_check.check_context(str(tmp_path / "bare")) is None


def test_ferry_in_non_git_dir(isolated_tmp, tmp_path):
    """非 git 目录：diff 为空但不崩，失败清单仍摆渡。"""
    project = tmp_path / "proj"
    (project / ".regress").mkdir(parents=True)
    _write_fails(3)
    reminders = reflection_check.check_context(str(project))
    ferry = "\n".join(reminders)
    assert "失败清单" in ferry
    assert "git diff" not in ferry, "无 diff 时不应输出空的 diff 段"


# ── 3. 卡死计数 × 纠错互不干扰 ──

def test_correction_resets_prod_counter(isolated_tmp):
    """纠正是实质输入：重置催促计数，不会把纠正误判成卡死信号。"""
    assert prompt_intercept.analyze_prompt("继续") == []  # 第 1 次催促：n=1 不触发
    assert prompt_intercept.analyze_prompt("不对，方向错了") != []  # 纠正（含纠错注入）
    assert prompt_intercept.analyze_prompt("继续") == [], "计数被纠正重置，重新累计"


def test_prod_second_time_triggers_scout(isolated_tmp):
    """连续第 2 次无信息催促 → scout 注入（回归保护：本次改动不破坏旧逻辑）。"""
    assert prompt_intercept.analyze_prompt("继续") == []
    rs = prompt_intercept.analyze_prompt("继续")
    assert any("卡死检测" in r for r in rs)


def test_approval_delegation_not_counted_as_prod():
    """v1.29：授权语不算无信息催促（病例：连续"继续，自决策"误报卡死检测）。"""
    import importlib.util as ilu
    import os as _os
    src = _os.path.join(_os.path.dirname(__file__), "..", "hooks", "scripts",
                        "prompt_intercept.py")
    spec = ilu.spec_from_file_location("pi_v129", src)
    pi = ilu.module_from_spec(spec)
    spec.loader.exec_module(pi)
    assert pi.is_content_free_prod("继续，自决策") is False   # 授权语
    assert pi.is_content_free_prod("继续，直接做") is False
    assert pi.is_content_free_prod("继续") is True            # 真空催促仍计
    assert pi.is_content_free_prod("go") is True
