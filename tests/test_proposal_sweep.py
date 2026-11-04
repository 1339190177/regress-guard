"""proposal_sweep 纯件（批185 P1）：差距表解析/本版过滤/执行序提取/覆盖去重/提案草案。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import proposal_sweep as ps  # noqa: E402

_MD = """# 计划
## 1. 差距总表（原型 ↔ 现状）

| 原型页 | B 项 | dap 现状 | 差距 | 本版 |
|---|---|---|---|---|
| login 登录 / account | B17 | 已有 | 15 能力点对齐 | ✅ 执行序 5（0.7） |
| org 组织主数据 | B1 | 平铺目录 | 三层只读树 | ✅ 执行序 1（2.5）+ 6（0.5） |
| wizard 去接入 | B3 | 无 | 五步向导 | ❌ 12 月+ |
| catalog 对方清单 | B7 | 认领雏形 | 四锚定键对账 | 部分（随序 15） |

## 2. 排布
"""


def test_parse_gap_table_rows():
    rows = ps.parse_gap_table(_MD)
    assert len(rows) == 4
    assert rows[0][0].startswith("login")
    assert rows[1][4].startswith("✅")


def test_is_proposable_filters_december():
    assert ps.is_proposable("✅ 执行序 5（0.7）")
    assert ps.is_proposable("部分（随序 15）")
    assert not ps.is_proposable("❌ 12 月+")


def test_seq_extraction_and_coverage():
    assert ps.seq_of("✅ 执行序 14（1.6 对齐版）") == 14
    assert ps.seq_of("部分（随序 15）") is None
    titles = ["[feat][运营端] org 组织主数据三层树", "docs(B1) 挂载"]
    assert ps.already_covered(titles, ("org 组织主数据", "B1", "", "", "✅ 执行序 1"))
    assert ps.already_covered(titles, ("ledger 设备台账", "B2", "", "", "✅")) is None


def test_draft_shape_no_angle_brackets(monkeypatch):
    # 批193：agent 名源自 _agent_login（读本机评审注册表，CI 无此文件落
    # 兜底值）——钉字面量=机器依赖测试（本机/CI 两头各挂一头）；patch
    # 固定值封闭化，注册表路径与兜底行为另由 _agent_login 单测钉
    monkeypatch.setattr(ps, "_agent_login", lambda: "fixture-agent")
    t, b = ps.draft_issue(("ledger 设备台账", "B2", "已有列表", "标段挂载+双视图", "✅ 执行序 14（1.6）"))
    assert t.startswith("[proposal][feat][dap·ledger][P0]")
    assert "<" not in t + b and ">" not in t + b
    assert "@fixture-agent 开工" in b and "机器可对账" in b
