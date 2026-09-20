"""安装后自检（v1.76，065）：三查合同——好树绿、缺件/错版本/坏语法红。"""
import importlib.util as ilu
import json
import os
import sys

CHECK = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "scripts", "post_install_check.py"))


def _load():
    spec = ilu.spec_from_file_location("pic", CHECK)
    m = ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _good_tree(tmp_path):
    """最小源仓+已装目录对：hooks.json 引用一个脚本，戳=源版本。"""
    src = tmp_path / "src"; ins = tmp_path / "ins"
    (src / "hooks").mkdir(parents=True); (src / ".zcode-plugin").mkdir()
    (ins).mkdir()
    (src / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{"type": "command",
                    "command": "python3 \"${ZCODE_PLUGIN_ROOT}/hooks/scripts/guard.py\""}]}]}}),
        encoding="utf-8")
    (src / ".zcode-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8")
    (ins / "guard.py").write_text("x = 1\n", encoding="utf-8")
    (ins / ".source").write_text(
        "source_path=/x\nsource_version=9.9.9\n", encoding="utf-8")
    return str(src), str(ins)


def test_good_tree_passes(tmp_path, capsys):
    m = _load()
    src, ins = _good_tree(tmp_path)
    assert m.main(src, ins) == 0
    out = capsys.readouterr().out
    assert "三查全绿" in out and "guard.py" not in out


def test_missing_script_fails(tmp_path, capsys):
    m = _load()
    src, ins = _good_tree(tmp_path)
    os.remove(os.path.join(ins, "guard.py"))
    assert m.main(src, ins) == 1
    assert "注册面" in capsys.readouterr().out


def test_version_mismatch_fails(tmp_path, capsys):
    m = _load()
    src, ins = _good_tree(tmp_path)
    (tmp_path / "ins" / ".source").write_text(
        "source_path=/x\nsource_version=0.0.1\n", encoding="utf-8")
    assert m.main(src, ins) == 1
    assert "版本面" in capsys.readouterr().out


def test_syntax_error_fails(tmp_path, capsys):
    m = _load()
    src, ins = _good_tree(tmp_path)
    (tmp_path / "ins" / "guard.py").write_text("def broken(:\n", encoding="utf-8")
    assert m.main(src, ins) == 1
    assert "语法面" in capsys.readouterr().out
