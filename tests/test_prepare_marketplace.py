"""prepare_marketplace 的蒸馏测试（099：官方市场上架准备）。"""
import json
import os
import subprocess
import sys

SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "scripts", "prepare_marketplace.py"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dist_excludes_dev_and_keeps_manifest():
    """dev 工具/deploy/tests/.pytest_cache 排除；.zcode-plugin 清单保留。"""
    r = subprocess.run([sys.executable, SCRIPT], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    dist = os.path.join(ROOT, "dist", "plugins", "regress-guard")
    for bad in ("scripts/publish.py", "scripts/gen_reference.py",
                "scripts/prepare_marketplace.py", "tests", "deploy",
                "marketplace.json", "pytest.ini", ".pytest_cache"):
        assert not os.path.exists(os.path.join(dist, bad)), bad
    m = json.load(open(os.path.join(dist, ".zcode-plugin", "plugin.json"),
                       encoding="utf-8"))
    assert m["name"] == "regress-guard" and m["version"].count(".") == 2
    for need in ("README.md", "README_CN.md", "LICENSE", "hooks", "commands"):
        assert os.path.exists(os.path.join(dist, need)), need
    # 机器路径零泄漏
    for dirpath, _, files in os.walk(dist):
        for fn in files:
            if fn.endswith((".py", ".md", ".json", ".sh")):
                p = os.path.join(dirpath, fn)
                t = open(p, encoding="utf-8", errors="ignore").read()
                # 机器专属=绝对个人路径/内网端口；~/.dsh 类家相对可选集成合法（无则降级）
                assert "/home/" not in t and "yelisheng" not in t \
                    and "38046" not in t, p


def test_marketplace_entry_shape():
    r = subprocess.run([sys.executable, SCRIPT], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    e = json.load(open(os.path.join(ROOT, "dist", "marketplace-entry.json"),
                       encoding="utf-8"))
    for k in ("name", "source", "description", "description_i18n", "version",
              "author", "category", "keywords"):
        assert k in e, k
    assert e["source"] == "./external_plugins/regress-guard"
    assert set(e["description_i18n"]) == {"en", "zh-CN"}
    assert e["category"] == "developer-tools"


def test_pr_payload_mode(tmp_path):
    """批137：--pr-payload 一键蒸馏 external_plugins 形态（取代手工全树拼装
    ——run14/49 的 134 文件 payload 曾混入 dev 件与缓存）。同源保证=
    相对路径+sha256 清单全等（顾问：文件数相等是弱断言）。"""
    import hashlib
    out = tmp_path / "pr"
    r = subprocess.run([sys.executable, SCRIPT, "--pr-payload", str(out)],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    payload = out / "external_plugins" / "regress-guard"
    assert (payload / ".zcode-plugin" / "plugin.json").exists()
    for bad in ("tests", "deploy", ".pytest_cache", "marketplace.json"):
        assert not (payload / bad).exists(), bad

    def _manifest(base):
        m = {}
        for dirpath, _, files in os.walk(base):
            for fn in files:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, base)
                m[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        return m

    dist = os.path.join(ROOT, "dist", "plugins", "regress-guard")
    assert _manifest(dist) == _manifest(str(payload)), \
        "PR 载荷与 dist 清单不全等（路径或内容漂移）"
