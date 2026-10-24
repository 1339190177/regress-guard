"""advisor_token（批139）：三级回退读取器合同——七态矩阵（顾问增补）。

优先序：env ADVISOR_DSH_TOKEN（空串=未设置）→ cordis.patch.yml（新正字）
→ settings.yaml（旧机/垫片）。静默分级：缺失/无键=静默；在场但解析炸/
形态异常=WARN（stderr 记路径不记值）走下一级；全空=一行列已试路径。
"""
import importlib.util as ilu
import os

import pytest

LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))
MOD_PATH = os.path.join(LIB, "advisor_token.py")

_GOOD = "dsha_" + "a1" * 20      # 形态合法
_GOOD2 = "dsha_" + "b2" * 20     # 第二个合法值（辨来源）
_BAD = "not-a-token"            # 形态异常


def _load():
    spec = ilu.spec_from_file_location("atok", MOD_PATH)
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _fresh_home(tmp_path, monkeypatch):
    """每用例独立 HOME+env+缓存（模块级缓存按 home 键隔离，另显式清）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ADVISOR_DSH_TOKEN", raising=False)
    m = _load()
    m._CACHE.clear()
    return tmp_path


def _write(home, rel, token=None, raw=None):
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
        return
    p.write_text(f"advisor:\n  token: '{token or _GOOD}'\n", encoding="utf-8")


def test_env_wins(_fresh_home):
    _write(_fresh_home, ".dsh/profiles/web/cordis.patch.yml", _GOOD)
    _write(_fresh_home, ".dsh/settings.yaml", _GOOD2)
    os.environ["ADVISOR_DSH_TOKEN"] = _GOOD2
    m = _load()
    m._CACHE.clear()
    assert m.read_advisor_token() == _GOOD2


def test_env_empty_string_means_unset(_fresh_home, capsys):
    """空串=未设置（顾问增补③）——走文件级。"""
    _write(_fresh_home, ".dsh/settings.yaml", _GOOD)
    os.environ["ADVISOR_DSH_TOKEN"] = "   "
    m = _load()
    m._CACHE.clear()
    assert m.read_advisor_token() == _GOOD


def test_cordis_new_canonical(_fresh_home):
    _write(_fresh_home, ".dsh/profiles/web/cordis.patch.yml", _GOOD)
    assert _load().read_advisor_token() == _GOOD


def test_legacy_settings_fallback(_fresh_home):
    """只有旧 settings.yaml（旧机/垫片形态）照常读到。"""
    _write(_fresh_home, ".dsh/settings.yaml", _GOOD2)
    assert _load().read_advisor_token() == _GOOD2


def test_shadowing_new_wins(_fresh_home):
    """新旧并存取新（键遮蔽治理）。"""
    _write(_fresh_home, ".dsh/profiles/web/cordis.patch.yml", _GOOD)
    _write(_fresh_home, ".dsh/settings.yaml", _GOOD2)
    assert _load().read_advisor_token() == _GOOD


def test_bad_cordis_falls_back_with_warn(_fresh_home, capsys):
    """cordis 在场但形态异常 → WARN（含路径不含值）→ 走旧级（顾问增补①）。"""
    _write(_fresh_home, ".dsh/profiles/web/cordis.patch.yml", _BAD)
    _write(_fresh_home, ".dsh/settings.yaml", _GOOD2)
    assert _load().read_advisor_token() == _GOOD2
    err = capsys.readouterr().err
    assert "形态异常" in err and "cordis" in err
    assert _BAD not in err, "WARN 不得带 token 值"


def test_all_missing_returns_none_with_paths(_fresh_home, capsys):
    """三级全空：None + 一行列已试路径（无值）。"""
    assert _load().read_advisor_token() is None
    err = capsys.readouterr().err
    assert "三级全空" in err and "cordis.patch.yml" in err
    assert "dsha_" not in err
