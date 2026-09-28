"""critic_pass（127：A 批评臂）测试——管道与解析，批评质量归试点双指标。"""
import importlib.util as ilu
import json
import os
import sys

import pytest

SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "scripts", "critic_pass.py"))


def _load():
    spec = ilu.spec_from_file_location("cp", SCRIPT)
    m = ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _mk_repo(tmp_path):
    import subprocess as sp
    repo = tmp_path / "proj"
    repo.mkdir()
    sp.run(["git", "init", "-q"], cwd=str(repo), check=True)
    sp.run(["git", "config", "user.email", "t@t.com"], cwd=str(repo), check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    (repo / "a.txt").write_text("1\n", encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=str(repo), check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=str(repo), check=True)
    return repo


def test_assemble_carries_artifacts(tmp_path, monkeypatch):
    """摆渡包含清单全文+diff+提交主题——工件齐，未引作者润色叙事。"""
    cp = _load()
    repo = _mk_repo(tmp_path)
    mf = tmp_path / "R1.md"
    mf.write_text("---\nid: REGRESS-2026-127\nstatus: done\n---\n正文判据",
                  encoding="utf-8")
    monkeypatch.setenv("REGRESS_JOURNAL", "off")
    monkeypatch.chdir(repo)  # 仓定位走 cwd 顶层（127：清单路径反推不可靠）
    path = cp.assemble(str(mf), out_dir=str(tmp_path / "c"))
    body = open(path, encoding="utf-8").read()
    assert "REGRESS-2026-127" in body and "HEAD diff" in body
    assert "近三条提交" in body and "init" in body


def test_parse_findings_lenient():
    cp = _load()
    good = ('前置噪音 {"p1": [{"claim": "越界", "evidence": "L4", '
            '"confidence": "high"}], "p2": [], "p3": []} 后置噪音')
    r = cp.parse_findings(good)
    assert r and r["p1"][0]["claim"] == "越界"
    assert cp.parse_findings("完全不是 JSON") is None
    assert cp.parse_findings('{"别的": 1}') is None


def test_run_normal_mode(monkeypatch, tmp_path):
    """顾问可达且格式合规：findings 落盘+journal critic_findings(mode=normal)。"""
    cp = _load()
    ferry = tmp_path / "ferry-X.md"
    ferry.write_text("# 摆渡包内容", encoding="utf-8")
    monkeypatch.setenv("ADVISOR_DSH_TOKEN", "stub")
    monkeypatch.setattr(cp, "_post_critic",
                        lambda url, tok, text: cp.CRITIC_PROMPT_TMPL.format(  # noqa: E731
                            ferry="")[:0] or '{"p1":[{"claim":"c","evidence":"e","confidence":"mid"}],"p2":[],"p3":[]}')
    events = []
    monkeypatch.setattr(cp, "journal_append",
                        lambda kind, **f: events.append((kind, f)) or True)
    r = cp.run_critic(str(ferry))
    assert r["mode"] == "normal" and r["findings"]["p1"][0]["claim"] == "c"
    assert any(k == "critic_findings" and f.get("mode") == "normal"
               for k, f in events)
    assert os.path.exists(r["path"])


def test_run_degrades_when_unreachable(monkeypatch, tmp_path):
    """顾问不可达：降级打标 degraded+prompt 落盘手动派发，退出不炸（臂不死）。"""
    cp = _load()
    ferry = tmp_path / "ferry-Y.md"
    ferry.write_text("# 摆渡包", encoding="utf-8")
    monkeypatch.setenv("ADVISOR_DSH_TOKEN", "stub")
    monkeypatch.setattr(cp, "_post_critic",
                        lambda *a: (_ for _ in ()).throw(OSError("down")))
    events = []
    monkeypatch.setattr(cp, "journal_append",
                        lambda kind, **f: events.append((kind, f)) or True)
    r = cp.run_critic(str(ferry))
    assert r["mode"] == "degraded" and r["findings"] is None
    assert os.path.exists(r["manual_dispatch"])
    assert any(k == "critic_findings" and f.get("mode") == "degraded"
               for k, f in events)  # 分段统计：降级不得与正常混同


def test_canary_defect_embedded(monkeypatch, tmp_path):
    """canary 种子进摆渡包：发现率测试有真 oracle。"""
    cp = _load()
    ferry = tmp_path / "ferry-Z.md"
    ferry.write_text("# 摆渡包", encoding="utf-8")
    seen = {}
    def fake_post(url, tok, text):
        seen["canary_in_ferry"] = "已知缺陷种子" in text
        return '{"p1":[],"p2":[],"p3":[]}'
    monkeypatch.setenv("ADVISOR_DSH_TOKEN", "stub")
    monkeypatch.setattr(cp, "_post_critic", fake_post)
    r = cp.run_critic(str(ferry), canary=True)
    assert r["mode"] == "normal" and seen["canary_in_ferry"]


def test_rebuttal_cli(monkeypatch):
    cp = _load()
    got = {}
    monkeypatch.setattr(cp, "journal_append",
                        lambda kind, **f: got.update(f) or True)
    r = cp.rebuttal('{"p1_0": "已修：边界补丁", "verdict": "confirmed"}')
    assert r["ok"] and got["p1_0"] == "已修：边界补丁"
