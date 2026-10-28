"""写入完整性钉测试（批154，哨兵 run54 立查产出）。

病例（2026-10-24×2 + 2026-10-27×2）：python heredoc 对 .regress 下清单
读改写打印成功但盘上未持久化——四次事件同会话同形态一成三败=并发竞态
嫌疑（纯 heredoc 机制已排除：探察 10/10 持久化）。本测试把该形态钉进
回归网：绿=当下环境健康（不是问题不存在的证明）；红=环境级丢失再现，
证据自携，升 strace 级根因批（FP1 语义）。
"""
import os
import subprocess
import sys

import pytest

PROBE = r"""
import sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read()
t += "\n## probe-" + sys.argv[2] + "\n"
open(p, "w", encoding="utf-8").write(t)
print("written ok")
"""


def test_heredoc_write_integrity(tmp_path):
    """5 轮 heredoc 形态读改写循环，独立进程读回全命中（环境级哨兵）。"""
    target = tmp_path / ".regress" / "m.md"
    target.parent.mkdir()
    target.write_text("---\nid: W1\n---\n基线\n", encoding="utf-8")
    for i in range(5):
        r = subprocess.run(
            [sys.executable, "-", str(target), str(i)],
            input=PROBE, capture_output=True, text=True, timeout=15)
        assert r.returncode == 0 and "written ok" in r.stdout
    # 独立读回（新进程，非同进程内存）
    n = subprocess.run(
        ["grep", "-c", "^## probe-", str(target)],
        capture_output=True, text=True, timeout=10)
    assert n.stdout.strip() == "5", \
        f"写入丢失再现：期望 5 段读回 {n.stdout.strip()}（升 strace 级根因批）"
    # 内容完整性：基线未被回写覆盖
    assert "基线" in target.read_text(encoding="utf-8")


def test_concurrent_writer_last_write_wins_visible(tmp_path):
    """并发写者场景的语义锚：慢读改写者覆盖快写者=经典丢失形态。

    这是嫌疑机制的机内演示（非重现）：读改写窗口内另一进程追加，
    慢写者基于旧快照回写→快写者内容丢。钉住语义防止未来有人把
    「没丢过」误当「不会丢」。
    """
    target = tmp_path / "m2.md"
    target.write_text("base\n", encoding="utf-8")
    slow_snapshot = target.read_text(encoding="utf-8")  # 慢读者先取快照
    with open(target, "a", encoding="utf-8") as f:      # 快写者追加
        f.write("fast-append\n")
    with open(target, "w", encoding="utf-8") as f:      # 慢写者回写旧快照
        f.write(slow_snapshot + "slow-append\n")
    text = target.read_text(encoding="utf-8")
    assert "fast-append" not in text and "slow-append" in text
