"""规律账本（v1.24 代谢链）：正负路径——从未失败过的守卫等于未验证的守卫。"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))
LEDGER = os.path.join(LIB, "rules_ledger.py")


def _mk(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True)
    return proj


def _run(proj, *args):
    return subprocess.run(
        [sys.executable, LEDGER, str(proj), *(str(a) for a in args)],
        capture_output=True, text=True, timeout=15)


def test_record_first_time_then_hit(tmp_path):
    """首记 hits=1；同签名再记 = 命中 hits+1 且 last_hit 刷新；不同签名分行。"""
    proj = _mk(tmp_path)
    r1 = _run(proj, "record", "--sig", "taos UnsatisfiedLinkError", "--occurrences", 3)
    assert r1.returncode == 0 and "新沉淀" in r1.stdout
    r2 = _run(proj, "record", "--sig", "taos UnsatisfiedLinkError", "--occurrences", 5)
    assert "命中（第 2 次）" in r2.stdout
    _run(proj, "record", "--sig", "port 18801 occupied", "--occurrences", 1)
    data = json.load(open(proj / ".regress" / "rules-ledger.json", encoding="utf-8"))
    assert len(data) == 2
    e = next(e for e in data.values() if e["sig"] == "taos UnsatisfiedLinkError")
    assert e["hits"] == 2 and e["occurrences"] == 5  # occurrences 取 max
    assert e["captured_at"] and e["last_hit"]


def test_health_decay_and_promote(tmp_path, capsys):
    """降级候选（>180 天零命中）与固化候选（hits≥3 且未腐化）分列；腐化者不固化。"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("rl", LEDGER)
    rl = ilu.module_from_spec(spec)
    spec.loader.exec_module(rl)
    proj = _mk(tmp_path)
    old = (date.today() - timedelta(days=200)).isoformat()
    data = {
        "a": {"sig": "老规律没人用了", "captured_at": old, "last_hit": old, "hits": 5, "occurrences": 9},
        "b": {"sig": "高频稳定规律", "captured_at": old, "last_hit": date.today().isoformat(), "hits": 4, "occurrences": 7},
        "c": {"sig": "新规律", "captured_at": date.today().isoformat(), "last_hit": date.today().isoformat(), "hits": 1, "occurrences": 1},
    }
    (proj / ".regress" / "rules-ledger.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = rl.health(str(proj))
    assert [e["sig"] for e in out["promotable"]] == ["高频稳定规律"]
    assert [e["sig"] for e in out["stale"]] == ["老规律没人用了"]
    printed = capsys.readouterr().out
    assert "永不自动删" in printed and "固化候选" in printed


def test_corrupt_ledger_tolerated(tmp_path):
    """坏 JSON 容错：load 返回空表，record 从零重建（地层是增强不是依赖）。"""
    proj = _mk(tmp_path)
    (proj / ".regress" / "rules-ledger.json").write_text("{不是json", encoding="utf-8")
    r = _run(proj, "record", "--sig", "x", "--occurrences", 1)
    assert r.returncode == 0
    data = json.load(open(proj / ".regress" / "rules-ledger.json", encoding="utf-8"))
    assert len(data) == 1


def test_not_initialized_project(tmp_path):
    """未接入项目：exit 1 + stderr 提示，不炸。"""
    r = _run(tmp_path / "nope", "health")
    assert r.returncode == 1 and "未找到" in r.stderr
