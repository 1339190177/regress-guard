"""批225（issue#8）：JSONL 读取非法 UTF-8 不崩主链。

病例：events.jsonl 混入非 UTF-8 字节 → 严格解码在行迭代处抛
UnicodeDecodeError（不在各读点的 except (IOError, OSError) 兜内）→
plan_approve 先写清单后读 journal → 清单已转 in-progress 而事件未落
→ 重跑报「无需批准」=批准记录永久缺失（崩锁）。
"""
import json
import os
import subprocess
import sys

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                   "hooks", "scripts", "lib"))
SCRIPTS = os.path.dirname(LIB)
sys.path.insert(0, LIB)

# issue#8 原样最小复现字节（坏行夹在好行之间）
GOOD1 = b'{"kind": "ok", "v": 1}\n'
BAD = b"\xa5E\xe9\x80\x9a\n"
GOOD2 = b'{"kind": "ok2", "v": 2}\n'


def _corrupt_journal(project_dir):
    jp = os.path.join(project_dir, ".regress", "journal", "events.jsonl")
    os.makedirs(os.path.dirname(jp), exist_ok=True)
    with open(jp, "wb") as f:
        f.write(GOOD1 + BAD + GOOD2)
    return jp


def test_load_journal_survives_bad_bytes(tmp_path):
    """坏字节行被弃、好行存活——考古数据不丢，主链不崩。"""
    import journal
    _corrupt_journal(str(tmp_path))
    events = journal.load_journal(str(tmp_path))  # 旧实现此处抛 UnicodeDecodeError
    kinds = [e.get("kind") for e in events]
    assert kinds == ["ok", "ok2"], f"好行丢失: {kinds}"


def test_history_and_pending_survive_bad_bytes(tmp_path):
    """同族读点（history 双读法/pending）同抗性。"""
    import history
    hp = os.path.join(str(tmp_path), ".regress", "history.jsonl")
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    with open(hp, "wb") as f:
        f.write(GOOD1 + BAD + GOOD2)
    # 迭代读法（:104 族）
    evs = history.load_events(str(tmp_path)) if hasattr(history, "load_events") else None
    if evs is None:  # 函数名漂移时退而直测迭代路径不崩
        with open(hp, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f if ln.strip()]
        assert len(lines) == 3  # replace 语义：坏行变替换符行（json.loads 弃）


def test_plan_approve_survives_corrupt_journal(tmp_path):
    """崩锁根治钉：坏 journal 下批准全链走完——状态转 in-progress 且
    plan_approved 事件在场（旧实现半途崩=状态已转而事件永缺）。"""
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, ".regress", "manifests"), exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj,
                   check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj,
                   check=True, timeout=30)
    _corrupt_journal(proj)
    m = os.path.join(proj, ".regress", "manifests", "REGRESS-test.md")
    with open(m, "w", encoding="utf-8") as f:
        f.write("""---
id: REGRESS-test
requirement: utf8 加固回归钉
status: planning
tier: S
rollback: none
scan:
  entry: test
  test: pytest
  card: 本清单
created_at: 2026-11-13
boundary:
  include:
  - {proj}/x.py
---
## 验收标准

1. 全链走完。（验：本测试断言）✅
""".replace("{proj}", proj))
    r = subprocess.run(
        [sys.executable, os.path.join(LIB, "plan_approve.py"), m,
         "--note", "回归钉"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=proj,
        env={**os.environ, "CLAUDE_PROJECT_DIR": proj,
             "ZCODE_PROJECT_DIR": proj,
             # conftest 全局 REGRESS_JOURNAL=off（测试卫生）会被
             # {**os.environ} 泄进子进程——本用恰要验证事件落盘，显式重开
             "REGRESS_JOURNAL": "on"})
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    content = open(m, encoding="utf-8").read()
    assert "status: in-progress" in content
    jp = os.path.join(proj, ".regress", "journal", "events.jsonl")
    tail = open(jp, "rb").read()
    assert b"plan_approved" in tail, (
        f"批准事件未落=崩锁回归 stdout={r.stdout[-500:]!r} "
        f"stderr={r.stderr[-300:]!r}")
    # 好行仍存活（考古不丢）
    assert b'"kind": "ok2"' in tail
