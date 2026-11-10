"""effect_track worktree GC（run61 批183）：>3 天终态树回收+取证存档+活跃树不动。
标本：磁盘 7.52G 逼近阈值、13 树无主（人工清理不可持续）。"""
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import effect_track  # noqa: E402


@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    ev_root = tmp_path / "evidence"
    monkeypatch.setattr(effect_track, "_work_dirs", lambda: [str(root)])
    monkeypatch.setattr(effect_track, "EVIDENCE_ROOT",
                        str(ev_root), raising=False)
    yield root, ev_root


def _mk_tree(root, name, age_days, manifest_status=None, with_evidence=False):
    d = root / name
    (d / ".regress" / "manifests").mkdir(parents=True)
    if manifest_status:
        (d / ".regress" / "manifests" / "R.md").write_text(
            f"---\nid: R\nstatus: {manifest_status}\n---\n", encoding="utf-8")
    if with_evidence:
        (d / "ui-evidence").mkdir()
        (d / "ui-evidence" / "shot.png").write_bytes(b"png")
    old = datetime.datetime.now().timestamp() - age_days * 86400
    import os as _os
    _os.utime(d, (old, old))
    return d


def test_gc_removes_stale_ended_tree_and_archives_evidence(workroot):
    root, ev_root = workroot
    _mk_tree(root, "feat-old-aaaabbbbcccc", 5, manifest_status="done",
             with_evidence=True)
    fixed = []
    effect_track.gc_ended_worktrees(fixed)
    assert not (root / "feat-old-aaaabbbbcccc").exists()
    assert (ev_root / "feat-old-aaaabbbbcccc" / "shot.png").exists()
    assert any("回收" in f for f in fixed)


def test_gc_keeps_active_and_fresh_trees(workroot):
    root, _ = workroot
    active = _mk_tree(root, "feat-live-ddddeeeeeeee", 5,
                      manifest_status="in-progress")
    fresh = _mk_tree(root, "feat-new-ffffgggggggg", 1, manifest_status="done")
    effect_track.gc_ended_worktrees([])
    assert active.exists() and fresh.exists()


# ── 批213：lib 路径双布局解析+失败三重可见 ────────────────

def test_lib_path_dual_layout(tmp_path, monkeypatch, capsys):
    """源码树布局（hooks/scripts/lib）与部署位布局（lib）各自命中；
    命中路径打印到 stderr（可见性）。"""
    # 部署位布局：scripts/ 旁有 lib/
    dep = tmp_path / "deploy"
    (dep / "scripts").mkdir(parents=True)
    (dep / "lib").mkdir()
    (dep / "lib" / "journal.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(effect_track, "__file__", str(dep / "scripts" / "effect_track.py"))
    p = effect_track._lib_path("journal.py")
    assert p == str(dep / "lib" / "journal.py")
    assert "lib 命中" in capsys.readouterr().err
    # 源码树布局：scripts/ 旁有 hooks/scripts/lib/
    src = tmp_path / "source"
    (src / "scripts").mkdir(parents=True)
    (src / "hooks" / "scripts" / "lib").mkdir(parents=True)
    (src / "hooks" / "scripts" / "lib" / "journal.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(effect_track, "__file__", str(src / "scripts" / "effect_track.py"))
    assert effect_track._lib_path("journal.py") == \
        str(src / "hooks" / "scripts" / "lib" / "journal.py")


def test_lib_path_env_override(tmp_path, monkeypatch):
    """ZCODE_LIB_PATH 环境变量优先于布局探测（顾问裁第一来源）。"""
    envd = tmp_path / "envlib"
    envd.mkdir()
    (envd / "journal.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "journal.py").write_text("# decoy\n", encoding="utf-8")
    monkeypatch.setattr(effect_track, "__file__",
                        str(tmp_path / "scripts" / "effect_track.py"))
    monkeypatch.setenv("ZCODE_LIB_PATH", str(envd))
    assert effect_track._lib_path("journal.py") == str(envd / "journal.py")


def test_journal_failure_visible_and_fallback(tmp_path, monkeypatch, capsys):
    """journal 子进程失败：stderr 可见+本地 jsonl 兜底落档+返回 False。"""
    dep = tmp_path / "dep"
    (dep / "scripts").mkdir(parents=True)
    monkeypatch.setattr(effect_track, "__file__",
                        str(dep / "scripts" / "effect_track.py"))
    monkeypatch.delenv("ZCODE_LIB_PATH", raising=False)
    # 无任何布局命中 → 末候选 → python3 起不存在的文件 → 必败路径
    monkeypatch.setattr(effect_track, "WORKSPACE", str(tmp_path))
    ok = effect_track._journal("run-测试备注")
    assert ok is False
    err = capsys.readouterr().err
    assert "journal 失败" in err and "兜底落档" in err
    fb = tmp_path / ".regress" / "journal-fallback.jsonl"
    assert fb.exists() and "run-测试备注" in fb.read_text(encoding="utf-8")
