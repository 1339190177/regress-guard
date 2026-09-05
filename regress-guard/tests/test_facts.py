"""机器事实卡（v1.31）：追加/刷新去重/最新表述为准/health 报表/路径注入。"""
import datetime
import importlib.util as ilu
import os

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))


def _load(tmp_path, monkeypatch):
    card = tmp_path / "facts" / "SKILL.md"
    monkeypatch.setenv("RG_FACTS_CARD", str(card))
    spec = ilu.spec_from_file_location("facts", os.path.join(LIB, "facts.py"))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, card


def test_record_creates_card_with_frontmatter(tmp_path, monkeypatch):
    m, card = _load(tmp_path, monkeypatch)
    assert m.record("SSH直连", "ssh tencent-cloud", "server") == "appended"
    text = card.read_text(encoding="utf-8")
    assert "name: machine-facts" in text and "先查这张机器事实卡" in text
    assert "### " in text and "ssh tencent-cloud" in text


def test_rehit_refreshes_date_not_duplicating(tmp_path, monkeypatch):
    m, card = _load(tmp_path, monkeypatch)
    d1 = datetime.date(2026, 1, 1)
    d2 = datetime.date(2026, 9, 5)
    assert m.record("SSH直连", "旧表述", "server", when=d1) == "appended"
    assert m.record("SSH直连", "新表述", "server", when=d2) == "refreshed"
    text = card.read_text(encoding="utf-8")
    assert text.count("### 2026-") == 1
    assert "### 2026-09-05 · server · SSH直连" in text
    assert "新表述" in text and "旧表述" not in text  # 卡不是审计日志：最新为准


def test_different_domain_or_title_appends(tmp_path, monkeypatch):
    m, _ = _load(tmp_path, monkeypatch)
    m.record("坑", "a", "zsh")
    m.record("坑", "b", "debian")
    m.record("另一个", "c", "zsh")
    assert m.health()["count"] == 3


def test_health_reports_oldest_and_stale(tmp_path, monkeypatch):
    m, _ = _load(tmp_path, monkeypatch)
    old = datetime.date(2025, 1, 1)  # >180d before 2026-09
    m.record("老事实", "x", "server", when=old)
    m.record("新事实", "y", "server")
    h = m.health()
    assert h["count"] == 2
    assert h["oldest_days"] > 180
    assert [s[2] for s in h["stale"]] == ["老事实"]


def test_cli_health_smoke(tmp_path, monkeypatch, capsys):
    m, _ = _load(tmp_path, monkeypatch)
    m.record("CLI冒烟", "z", "env")
    assert m.main(["health"]) == 0
    out = capsys.readouterr().out
    assert "机器事实卡" in out and "1 条" in out
