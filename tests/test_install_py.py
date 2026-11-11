"""install.py / uninstall.py 安装轨契约（批191，v2.8.0 Windows 兼容）。

安装器 Python 化后的机器合同：注册形态全走 node launcher（零 python3
直调——Windows 无 python3 命令）、幂等、卸载零残留。沙箱走
REGRESS_ZCODE_HOME 覆写（124 先例），不碰真机。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(ROOT, "install.py")
UNINSTALL = os.path.join(ROOT, "uninstall.py")


def _sandbox(tmp_path):
    zh = tmp_path / "zh"
    (zh / "cli").mkdir(parents=True)
    return zh


def _install(zh, expect_ok=True):
    env = {**os.environ, "REGRESS_ZCODE_HOME": str(zh)}
    r = subprocess.run([sys.executable, INSTALL], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
    if expect_ok:
        assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]
    return r


def _events(zh):
    cfg = json.load(open(zh / "cli" / "config.json", encoding="utf-8"))
    return cfg["hooks"]["events"]


def test_install_registers_all_via_launcher(tmp_path):
    """六事件全注册 + 全部经 node launcher.js（零 python3 直调）。"""
    zh = _sandbox(tmp_path)
    _install(zh)
    ev = _events(zh)
    assert set(ev) >= {"PreToolUse", "PostToolUse", "PostToolUseFailure",
                       "SessionStart", "Stop", "UserPromptSubmit"}
    blob = json.dumps(ev)
    assert "python3" not in blob, "python3 直调回归（Windows 必挂）"
    assert blob.count("launcher.js") >= 14, "launcher 路由条数不足"


def test_install_idempotent(tmp_path):
    """二跑不重复添加（事件条数不翻倍）。"""
    zh = _sandbox(tmp_path)
    _install(zh)
    n1 = json.dumps(_events(zh))
    _install(zh)
    assert json.dumps(_events(zh)) == n1, "幂等破坏：二跑改了注册面"


def test_install_lays_out_selfheal_in_lib(tmp_path):
    """self_heal 落 lib/（历史契约）+ launcher 在根 + 无根位残留。"""
    zh = _sandbox(tmp_path)
    _install(zh)
    hook_home = zh / "regress-guard-hooks"
    assert (hook_home / "launcher.js").is_file()
    assert (hook_home / "lib" / "self_heal.py").is_file()
    assert not (hook_home / "self_heal.py").exists(), "根位残留（120 病例）"


def test_install_refreshes_stale_installed_plugin_json(tmp_path):
    """批222：装机树版本档随装刷新——预埋失真残档（标本：市场形态留档冻结在
    首装版本，install.py 拷贝段从不覆盖，取证读出 2.8.4 而真身已 2.8.21）。"""
    zh = _sandbox(tmp_path)
    hook_home = zh / "regress-guard-hooks"
    stale = hook_home / ".zcode-plugin" / "plugin.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"name": "regress-guard-hooks",
                                 "version": "0.0.1"}), encoding="utf-8")
    _install(zh)
    got = json.loads(stale.read_text(encoding="utf-8"))
    src = json.loads(open(os.path.join(ROOT, ".zcode-plugin", "plugin.json"),
                          encoding="utf-8").read())
    assert got["version"] == src["version"], (
        f"装机树版本档未随装刷新（残档冻结：{got['version']} != 源仓 "
        f"{src['version']}——取证误导面）")
    assert got == src, "全量覆盖语义：内容应与源仓 plugin.json 完全一致"


def test_uninstall_zero_residue(tmp_path):
    """卸载后 config 零 regress 痕迹 + hook 目录/命令清除。"""
    zh = _sandbox(tmp_path)
    _install(zh)
    r = subprocess.run([sys.executable, UNINSTALL], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60,
                       env={**os.environ, "REGRESS_ZCODE_HOME": str(zh)})
    assert r.returncode == 0, r.stderr[-400:]
    cfg = json.load(open(zh / "cli" / "config.json", encoding="utf-8"))
    blob = json.dumps(cfg)
    for token in ("launcher.js", "boundary_guard", "self_heal",
                  "pre_commit_guard", "regress-guard"):
        assert token not in blob, f"卸载残留 {token}"
    assert not (zh / "regress-guard-hooks").exists()
    assert not (zh / "regress-guard-docs").exists()
