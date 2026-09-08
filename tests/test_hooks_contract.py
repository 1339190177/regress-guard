"""hooks.json 插件契约（评审批次一 P0-2）。

病例（2026-09-08 评审 P0）：插件模式只装了 6 条钩子，边界守卫/执行阀/
失败采集/风险采集/压缩警告/轮末推送全部缺席——install.sh 注册的强制力
在插件模式下名存实亡；UserPromptSubmit 空 matcher 与自家 schema 教训矛盾。
"""
import json
import os

HOOKS = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "hooks.json"))

# 每个事件里必须注册到的脚本名（与 install.sh 语义对齐）
REQUIRED = {
    "PreToolUse": ["launcher.js", "boundary_guard", "execution_valve",
                   "read_before_edit_guard"],
    "PostToolUse": ["risk_watch", "read_before_edit_guard"],
    "PostToolUseFailure": ["fail_watch"],
    "SessionStart": ["self_heal", "compact_notice"],
    "Stop": ["reflection_check", "stop_notify"],
    "UserPromptSubmit": ["prompt_intercept"],
}


def _events():
    h = json.load(open(HOOKS, encoding="utf-8"))
    return h.get("hooks") or h


def test_no_empty_matcher():
    """空 matcher 违反 schema（install.sh:214 自注：会致整份 config 被丢弃）。"""
    for ev, entries in _events().items():
        for e in entries:
            m = e.get("matcher")
            assert m not in ("",), f"{ev} 条目空 matcher——v1.27.1 教训重犯"
            if m is not None:
                assert isinstance(m, str) and m


def test_all_guards_registered():
    """六类缺席守卫全部在插件模式注册（P0-2 核心）。"""
    ev = _events()
    for event, names in REQUIRED.items():
        blob = json.dumps(ev.get(event, []), ensure_ascii=False)
        for name in names:
            assert name in blob, f"{event} 缺 {name} 注册——插件模式强制力缺席"


def test_stop_entry_no_matcher():
    """Stop 事件无 matcher 键（v1.34 已修，防回归）。"""
    for e in _events().get("Stop", []):
        assert "matcher" not in e
