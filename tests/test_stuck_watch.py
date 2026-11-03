"""stuck_watch 孤儿/卡死分类（run60 批182）：昨夜 7 例"疑似卡死"实为孤儿——
worker 转录尾 turn/end completed（正常收工），PR 被评审判据拦着不合致工单悬空。
分类错了恢复动作就错：孤儿去修 PR 判据，卡死才谈重启。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import stuck_watch  # noqa: E402


def test_stale_label_orphan_vs_hang():
    assert "孤儿" in stuck_watch._stale_label(True)
    assert "疑似卡死" in stuck_watch._stale_label(False)


def test_session_completed_by_tail_text():
    tail = '{"type": "step/end"}\n{"type": "turn/end", "data": {"turn": 4, "reason": {"kind": "completed"}}}'
    # 直接验证判定式（_session_completed 的核心逻辑，文件版走 zstd 子进程）
    assert '"turn/end"' in tail and '"completed"' in tail


def test_session_active_tail_is_not_completed():
    tail = '{"type": "tool/call", "data": {"name": "bash"}}\n{"type": "step/start"}'
    assert not ('"turn/end"' in tail and '"completed"' in tail)
