"""replay_experiment（批136）：重放实验合同——语料性质/判定器差异/归档 schema/
pinned-SHA 快照对账（顾问三修：确定性声明、边界区间措辞、结构化 boundary、
快照与 git 历史父提交原文对账）。"""
import importlib.util as ilu
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

RE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "scripts", "replay_experiment.py"))
ROOT = os.path.dirname(os.path.dirname(RE))


def _load():
    spec = ilu.spec_from_file_location("rexp", RE)
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ─── 实验一：纠正闭环 ─────────────────────────────────────

def test_correction_escape_form_diverges():
    """0158a98b 逃逸形态（gap=32min）：旧窗漏，高水位窗捕。"""
    m = _load()
    r = m.run_correction_replay()
    per_gap = r["results"]["per_gap"]
    assert per_gap["32"]["old"] == 0 and per_gap["32"]["new"] == 5
    assert per_gap["2"]["old"] == 5 and per_gap["2"]["new"] == 5   # 短 gap 两式同捕
    # 边界区间措辞：不得宣称精确阈值（gap 8/12 之间未采样）
    assert "(8,12)" in r["claim_wording"]


def test_corpus_deterministic():
    """语料确定性（顾问：注明而非默认）——两次运行同参同果。"""
    m = _load()
    a = m.run_correction_replay()["results"]["per_gap"]
    b = m.run_correction_replay()["results"]["per_gap"]
    assert a == b


# ─── 实验二：读门禁 ──────────────────────────────────────

def test_readgate_death_spiral_vs_bounded():
    """f77a 死亡螺旋：旧式终点缺口=60（(39+1)*2-20），per-file=0。"""
    m = _load()
    r = m.run_readgate_replay()
    sp = r["results"]["forms"]["spiral"]
    assert sp["edits"] == 39 and sp["reads"] == 20
    assert sp["old_final_deficit"] == 60
    assert sp["new_final_deficit"] == 0
    # 旧式缺口单调线性增长（死亡螺旋曲线），新式有界
    seq = m._sequence("spiral")
    old_c = m.old_cumulative_deficit(seq)
    assert old_c[-1] > old_c[len(old_c) // 2] > old_c[0]


def test_readgate_disciplined_unpunished():
    """正当工作流（1:1 读后才改）：新式 0 缺口；旧式 (e+1)*ratio 数学下
    1:1 永不满足=仍线性罚读（过度惩罚的另一半实证，忠实历史）。"""
    m = _load()
    r = m.run_readgate_replay()
    d = r["results"]["forms"]["disciplined"]
    assert d["new_final_deficit"] == 0
    assert d["old_final_deficit"] > 0, "旧式对 1:1 流也应罚读（历史行为）"


# ─── 归档 schema（结构化 interpretation_boundary） ─────────

@pytest.mark.parametrize("runner_name", ["run_correction_replay",
                                         "run_readgate_replay"])
def test_boundary_structured(runner_name):
    m = _load()
    res = m._finalize(getattr(m, runner_name)(), "test-feature")
    b = res["interpretation_boundary"]
    for key in ("specimen_id", "within", "without", "confounds"):
        assert key in b and b[key], key
    assert res["corpus"].get("deterministic") is True


# ─── pinned-SHA：冻结快照 vs git 历史父提交原文对账（顾问一修） ──

def test_snapshot_pinned_to_history():
    """内联快照常量必须与真实旧码原文一致——git 检出批 122/111 的父提交，
    断言旧行为特征串在场（防转写漂移：快照≠重构版本）。"""
    m = _load()
    def _parent_show(grep, path):
        c = subprocess.run(["git", "-C", ROOT, "log", "--grep", grep,
                            "-n1", "--format=%H"],
                           capture_output=True, text=True, timeout=15)
        sha = c.stdout.strip()
        if not sha:
            pytest.skip("git 历史无该批提交锚点（浅克隆环境）")
        s = subprocess.run(["git", "-C", ROOT, "show", f"{sha}^:{path}"],
                           capture_output=True, text=True, timeout=15)
        return s.stdout
    # 批122 父提交的 reflection_check 含 10 分钟窗特征
    old_refl = _parent_show("纠正闭环 v2", "hooks/scripts/reflection_check.py")
    assert ("600" in old_refl or "minutes=10" in old_refl
            or "10 分钟" in old_refl), "旧 10 分钟窗特征串不在历史原文"
    assert m.OLD_CORRECTION_WINDOW_MIN == 10
    # 批111 父提交的 read_before_edit_guard 含累计乘法特征
    old_rbe = _parent_show("per-file 语义重构", "hooks/scripts/read_before_edit_guard.py")
    assert "edit_count" in old_rbe and ("*ratio" in old_rbe
                                        or "* ratio" in old_rbe
                                        or "＊ratio" in old_rbe), \
        "旧累计乘法特征串不在历史原文"
    assert "(edit_count+1)" in m.OLD_READ_FORMULA.replace(" ", "")
