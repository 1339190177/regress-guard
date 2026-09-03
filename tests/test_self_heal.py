"""self_heal（SessionStart 自愈）的单元测试——老项目 README 自动迁移。"""
import os
import sys

HEAL = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "self_heal.py")
_SCRIPTS = os.path.dirname(os.path.abspath(HEAL))
sys.path.insert(0, os.path.join(_SCRIPTS, "lib"))
sys.path.insert(0, _SCRIPTS)


def _load_heal(tmp_path, monkeypatch):
    import importlib
    import self_heal
    importlib.reload(self_heal)
    tpl_dir = tmp_path / "hookhome" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "regress-dir-readme.md").write_text("# 先读我\n模板内容\n", encoding="utf-8")
    monkeypatch.setattr(self_heal, "HOOK_HOME", str(tmp_path / "hookhome"))
    return self_heal


def test_backfill_missing_readme(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    note = sh.backfill_project_readme(str(rg))
    assert note and "零号入口" in note
    assert (rg / "README.md").read_text(encoding="utf-8").startswith("# 先读我")


def test_backfill_never_overwrites_custom(tmp_path, monkeypatch):
    """用户定制过的 README 永不覆盖。"""
    sh = _load_heal(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    (rg / "README.md").write_text("我的定制版", encoding="utf-8")
    assert sh.backfill_project_readme(str(rg)) is None
    assert (rg / "README.md").read_text(encoding="utf-8") == "我的定制版"


def test_backfill_idempotent(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    assert sh.backfill_project_readme(str(rg)) is not None
    assert sh.backfill_project_readme(str(rg)) is None  # 第二次幂等


def test_required_commands_include_new_ones():
    import self_heal
    assert "regress:trace" in self_heal.REQUIRED_COMMANDS
    assert "regress:resume" in self_heal.REQUIRED_COMMANDS


# ── v1.17：活跃清单哨兵 ──

_MF_ACTIVE = """---
id: R1
status: {status}
planned_changes:
  - id: F1
    file: "src/a.ts"
    type: method-logic
fragile_points:
  - id: V1
    kind: env
    description: "d"
    verify: "true"
    status: {fp}
blocked:
  reason: "Redis 不通"
  need: "开白名单"
---
body
"""


def _mk_proj_manifest(tmp_path, status="in-progress", fp="open"):
    proj = tmp_path / "sproj"
    (proj / ".regress" / "manifests").mkdir(parents=True, exist_ok=True)
    (proj / ".regress" / "manifests" / "R1.md").write_text(
        _MF_ACTIVE.format(status=status, fp=fp), encoding="utf-8")
    return proj


def test_sentinel_in_progress(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    proj = _mk_proj_manifest(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "🎯 R1" in out and "1 个脆弱点未锁" in out
    assert "/regress:resume" in out


def test_sentinel_done_returns_none(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    proj = _mk_proj_manifest(tmp_path, status="done", fp="locked")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    assert sh._active_manifest_sentinel() is None


def test_sentinel_blocked_shows_need(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    proj = _mk_proj_manifest(tmp_path, status="blocked")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "🛑 R1" in out and "开白名单" in out


def test_sentinel_planning(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    proj = _mk_proj_manifest(tmp_path, status="planning")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "⏸ R1" in out and "待人类批准" in out


def test_required_commands_include_finish():
    import self_heal
    assert "regress:finish" in self_heal.REQUIRED_COMMANDS


def test_sentinel_provisional(tmp_path, monkeypatch):
    """临行任务显示 🚀 否决窗标注。"""
    sh = _load_heal(tmp_path, monkeypatch)
    proj = _mk_proj_manifest(tmp_path)
    mf = proj / ".regress" / "manifests" / "R1.md"
    mf.write_text(mf.read_text().replace(
        "status: in-progress",
        'status: in-progress\nprovisional:\n  at: "2026-08-26T11:00:00"\n  advisor: "无异议"'),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "🚀 R1" in out and "否决窗" in out and "--cancel" in out


# ── v1.21：README 刷新三分法（机器写的旧版才刷新，定制永不动）──

_TPL_V121 = "# 先读我\n机器版\n<!-- generated-by: regress-guard v1.21.0 -->\n"


def _tpl_with_marker(tmp_path, monkeypatch):
    sh = _load_heal(tmp_path, monkeypatch)
    tpl = tmp_path / "hookhome" / "templates" / "regress-dir-readme.md"
    tpl.write_text(_TPL_V121, encoding="utf-8")
    return sh


def test_refresh_stale_machine_readme(tmp_path, monkeypatch):
    """带旧版本标记（机器生成）→ 自动刷新到新版。"""
    sh = _tpl_with_marker(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    (rg / "README.md").write_text(
        "旧机器版\n<!-- generated-by: regress-guard v1.16.0 -->\n", encoding="utf-8")
    note = sh.backfill_project_readme(str(rg))
    assert note and "刷新" in note and "v1.16.0→v1.21.0" in note
    assert "机器版" in (rg / "README.md").read_text(encoding="utf-8")


def test_no_marker_never_touched_even_if_stale_content(tmp_path, monkeypatch):
    """无标记（人类定制）→ 即便内容是旧措辞也永不动。"""
    sh = _tpl_with_marker(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    (rg / "README.md").write_text("我的定制版（旧措辞）", encoding="utf-8")
    assert sh.backfill_project_readme(str(rg)) is None
    assert "我的定制版" in (rg / "README.md").read_text(encoding="utf-8")


def test_same_version_no_refresh(tmp_path, monkeypatch):
    sh = _tpl_with_marker(tmp_path, monkeypatch)
    rg = tmp_path / "proj" / ".regress"
    rg.mkdir(parents=True)
    (rg / "README.md").write_text(_TPL_V121, encoding="utf-8")
    assert sh.backfill_project_readme(str(rg)) is None


def test_sentinel_stale_planning_hint(tmp_path, monkeypatch):
    """v1.23.2 长寿可见化：planning 搁置 >30 天 → 哨兵标 ⏰（只提示不处置）。"""
    from datetime import date, timedelta
    sh = _load_heal(tmp_path, monkeypatch)
    proj = tmp_path / "sproj"
    (proj / ".regress" / "manifests").mkdir(parents=True, exist_ok=True)
    old = (date.today() - timedelta(days=40)).isoformat()
    (proj / ".regress" / "manifests" / "R1.md").write_text(
        _MF_ACTIVE.format(status="planning", fp="open").replace(
            "status: planning", f'status: planning\ncreated_at: "{old}"'),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "⏸ R1" in out and "已搁置40天" in out


def test_sentinel_fresh_planning_no_stale_hint(tmp_path, monkeypatch):
    """对照：新建 planning 不带 ⏰（30 天内的等待是正常节奏）。"""
    from datetime import date
    sh = _load_heal(tmp_path, monkeypatch)
    proj = tmp_path / "sproj"
    (proj / ".regress" / "manifests").mkdir(parents=True, exist_ok=True)
    (proj / ".regress" / "manifests" / "R1.md").write_text(
        _MF_ACTIVE.format(status="planning", fp="open").replace(
            "status: planning", f'status: planning\ncreated_at: "{date.today().isoformat()}"'),
        encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "⏸ R1" in out and "⏰" not in out


def test_sentinel_stale_mtime_fallback(tmp_path, monkeypatch):
    """v1.23.3 田阶：旧模板清单无 created_at（lqgd 全部 5 个实测如此）→ mtime 兜底。"""
    import os as _os
    import time as _time
    sh = _load_heal(tmp_path, monkeypatch)
    proj = tmp_path / "sproj"
    (proj / ".regress" / "manifests").mkdir(parents=True, exist_ok=True)
    mf = proj / ".regress" / "manifests" / "R1.md"
    mf.write_text(_MF_ACTIVE.format(status="planning", fp="open"), encoding="utf-8")
    _os.utime(mf, (_time.time() - 40 * 86400,) * 2)  # mtime 拨回 40 天前
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    out = sh._active_manifest_sentinel()
    assert out and "⏰ 已搁置40天" in out


def test_backfill_lock_gitignore_idempotent(tmp_path):
    """v1.23.3 田阶：windwos 项目 4 个 .lock 残留——回填 manifests/.gitignore，幂等不覆盖。"""
    import importlib.util as _ilu
    src = _ilu.spec_from_file_location(
        "sh_gitignore", os.path.join(os.path.dirname(__file__), "..",
                                     "hooks", "scripts", "self_heal.py"))
    mod = _ilu.module_from_spec(src)
    src.loader.exec_module(mod)
    rg = tmp_path / ".regress"
    (rg / "manifests").mkdir(parents=True)
    assert mod.backfill_lock_gitignore(str(rg)) is not None
    assert (rg / "manifests" / ".gitignore").read_text(encoding="utf-8") == ".*.lock\n"
    # 幂等：已存在不覆盖
    (rg / "manifests" / ".gitignore").write_text("自定义内容\n", encoding="utf-8")
    assert mod.backfill_lock_gitignore(str(rg)) is None
    assert "自定义内容" in (rg / "manifests" / ".gitignore").read_text(encoding="utf-8")
