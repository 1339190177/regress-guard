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
    monkeypatch.setattr(effect_track, "WORK_DIR", str(root))
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
