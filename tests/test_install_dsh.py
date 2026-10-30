"""install_dsh 安装轨道单测（批166：fixture profile，零网络零真 dsh）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import install_dsh as ids  # noqa: E402


def _fixture_profile(tmp_path, with_patch=True):
    dsh = tmp_path / ".dsh"
    prof = dsh / "profiles" / "web"
    prof.mkdir(parents=True)
    if with_patch:
        (prof / "cordis.patch.yml").write_text(
            "# 用户层\n- id: someone-else\n  name: \"@deepseek-ai/dsh-timer\"\n",
            encoding="utf-8")
    return str(dsh), str(prof)


def test_generate_hooks_cc_replaces_and_validates(tmp_path):
    """CC 方言产物：变量全替换+matcher 双方言展宽+dsh bash 工具命中。"""
    dest = ids.generate_hooks_cc(root=str(tmp_path))
    text = open(dest, encoding="utf-8").read()
    assert "${ZCODE_PLUGIN_ROOT}" not in text
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    import json
    import re
    data = json.loads(text)
    assert "PreToolUse" in data["hooks"]  # 门禁点在场
    matchers = [g["matcher"] for g in data["hooks"]["PreToolUse"]]
    bash_m = [m for m in matchers if "bash" in m.lower()]
    assert bash_m and re.search(bash_m[0], "bash") and re.search(bash_m[0], "Bash") \
        and re.search(bash_m[0], "pwsh")
    edit_m = [m for m in matchers if "edit" in m.lower()][0]
    assert re.search(edit_m, "edit") and re.search(edit_m, "write")


def test_patch_entry_idempotent_insert_and_remove(tmp_path):
    dsh, prof = _fixture_profile(tmp_path)
    p = os.path.join(prof, "cordis.patch.yml")
    changed1, _ = ids.install_patch_entry(dsh, "web", root=str(tmp_path),
                                          config_path=str(tmp_path / "cc.json"))
    assert changed1
    body = open(p, encoding="utf-8").read()
    assert "dsh-hooks-claude-code" in body and "- id: someone-else" in body
    changed2, _ = ids.install_patch_entry(dsh, "web", root=str(tmp_path))
    assert not changed2  # 幂等：重复安装=无操作
    removed, _ = ids.remove_patch_entry(dsh, "web")
    assert removed
    body = open(p, encoding="utf-8").read()
    assert ids.PATCH_ENTRY_ID not in body and "someone-else" in body  # 他人条目不动
    removed2, _ = ids.remove_patch_entry(dsh, "web")
    assert not removed2


def test_ensure_bridge_pkg_already_present_via_lock(tmp_path):
    """在位判定走 node_modules 实体双包（批166 活体：lock 字符串会被
    peerDependency 声明行误中=假绿；peer 缺装=桥 import 失败静默放行）。"""
    dsh, prof = _fixture_profile(tmp_path)
    for pkg in (ids.BRIDGE_PKG, ids.PROTOCOL_PKG):
        d = tmp_path / ".dsh" / "profiles" / "web" / "node_modules" / pkg
        d.mkdir(parents=True)
        (d / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    import unittest.mock as mock
    with mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        ok, msg = ids.ensure_bridge_pkg("web", dsh_bin="/nonexistent-dsh")
    assert ok and "已在位" in msg
