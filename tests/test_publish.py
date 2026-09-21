"""publish.py 的单元测试（v1.87.2，095：发布面三查+固化样板）。"""
import os
import subprocess
import sys

SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "scripts", "publish.py"))


# ─── 消息三查（纯函数） ──────────────────────────────

def _load():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("pub", SCRIPT)
    pub = ilu.module_from_spec(spec)
    spec.loader.exec_module(pub)
    return pub


def test_check_message_rejects_english_only():
    pub = _load()
    errs = pub.check_message("v1.87.2 publish script (095)")
    assert any("中文" in e for e in errs)


def test_check_message_rejects_missing_ref():
    pub = _load()
    errs = pub.check_message("中文消息但没有任何批号引用")
    assert any("批号" in e for e in errs)


def test_check_message_rejects_angle_bracket():
    pub = _load()
    errs = pub.check_message("中文消息（095）含<x>尖括号")
    assert any("尖括号" in e for e in errs)


def test_check_message_accepts_compliant():
    pub = _load()
    assert pub.check_message("v1.87.2 发布脚本（095）：固化样板+三查；645/645") == []


def test_check_message_rejects_empty():
    pub = _load()
    assert any("为空" in e for e in pub.check_message(""))


# ─── 镜像拼接 ────────────────────────────────────────

def test_mirror_since_joins_subjects(tmp_path):
    p = tmp_path / "repo"
    p.mkdir()
    for a in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(a, cwd=str(p), check=True)
    (p / "a.txt").write_text("1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "中文首批（001）"], cwd=str(p), check=True)
    (p / "a.txt").write_text("2\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(p),
                          capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "commit", "-qm", "中文二批（002）"], cwd=str(p), check=True)
    pub = _load()
    msg = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(p)!r}); "
         f"import importlib.util as i; s=i.spec_from_file_location('pub', {SCRIPT!r}); "
         f"m=i.module_from_spec(s); s.loader.exec_module(m); "
         f"print(m.mirror_since({base!r}))"],
        cwd=str(p), capture_output=True, text=True, check=True).stdout.strip()
    assert "（002）" in msg and "（001）" not in msg
    assert pub.check_message(msg) == []


# ─── CLI：dry-run 零网络零 token / 未知参数拒 ────────

def test_cli_dry_run_no_network(tmp_path):
    """dry-run 在无 token 环境也成功（零网络零凭据读取）。"""
    p = tmp_path / "repo"
    p.mkdir()
    for a in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(a, cwd=str(p), check=True)
    (p / "a.txt").write_text("1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "中文（001）"], cwd=str(p), check=True)
    r = subprocess.run(
        [sys.executable, SCRIPT, "--dry-run", "-m", "中文试发布（001）"],
        cwd=str(p), capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "HOME": str(p)}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout and "未发布" in r.stdout


def test_cli_rejects_unknown_flag(tmp_path):
    """未知参数拒绝（#14：gen_reference 静默吞未知 flag 的教训）。"""
    r = subprocess.run(
        [sys.executable, SCRIPT, "--dry-runy", "-m", "中文（001）"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode != 0


def test_cli_rejects_noncompliant_message(tmp_path):
    r = subprocess.run(
        [sys.executable, SCRIPT, "--dry-run", "-m", "english only"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "中文" in r.stderr
