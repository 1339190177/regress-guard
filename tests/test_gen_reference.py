"""gen_reference（v1.22 派生优于断言 + 批223 双 README）的单元测试。"""
import importlib.util
import os
import subprocess
import sys

GEN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                   "gen_reference.py"))


def _run(args, cwd):
    return subprocess.run([sys.executable, GEN, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=cwd, timeout=60)


def _load():
    spec = importlib.util.spec_from_file_location("gen_reference", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_passes_on_fresh_generation(tmp_path):
    """生成区与实况一致 → --check 通过（双 README 都须一致）。"""
    r = _run(["--check"], os.path.dirname(os.path.dirname(GEN)))
    assert r.returncode == 0, r.stderr + r.stdout


def test_tampered_region_fails_check(tmp_path, monkeypatch):
    """篡改生成区计数 → --check 必须红（病例：手写数字腐烂）。"""
    repo = os.path.dirname(os.path.dirname(GEN))
    readme = tmp_path / "README.md"
    src = open(os.path.join(repo, "README.md"), encoding="utf-8").read()
    readme.write_text(src.replace("个 · hook 注册", "X · hook 注册"), encoding="utf-8")
    mod = _load()
    assert mod.apply(readme_path=str(readme), check=True) == 1


def test_apply_all_covers_both_readmes(monkeypatch):
    """批223：双 README 同刷——CN 不再是单文件设计的静默盲区（563 病例钉）。"""
    mod = _load()
    calls = []

    def fake_apply(readme_path=None, check=False, init=False):
        calls.append(os.path.basename(readme_path))
        return 0

    monkeypatch.setattr(mod, "apply", fake_apply)
    assert mod.apply_all(check=True) == 0
    assert calls == ["README.md", "README_CN.md"], "双文件覆盖回归"


def test_apply_all_propagates_failure(monkeypatch):
    """任一文件红 → apply_all 红（validate 消费退出码）。"""
    mod = _load()
    monkeypatch.setattr(mod, "apply", lambda readme_path=None, check=False,
                        init=False: 1)
    assert mod.apply_all(check=True) == 1


def test_missing_zone_errors_not_inserts(tmp_path):
    """批223：缺区=报错非零而非静默插入（顾问预审：插入会伪装成功）；--init 显式建区。"""
    mod = _load()
    f = tmp_path / "README.md"
    f.write_text("# no zone here\n", encoding="utf-8")
    assert mod.apply(readme_path=str(f)) == 1, "缺区静默插入回归"
    assert mod.apply(readme_path=str(f), init=True) == 0
    assert "generated: reference start" in f.read_text(encoding="utf-8")
