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


# ─── v1.87.3 发布状态文件（096：哨兵轮） ──────────────

def test_state_roundtrip(tmp_path, monkeypatch):
    """状态写读往返：三字段齐（含 last_local_head/remote_commit）。

    cwd 隔离用 monkeypatch.chdir（自动还原）——手搓 finally 曾把 pytest 进程
    cwd 留在 tmp（后续 read-guard 子进程按错 cwd 解析状态→顺序依赖红，
    哨兵轮 096 活体标本）。"""
    (tmp_path / ".regress").mkdir()
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")
    pub = _load()
    pub.write_state("abc123def456789", "fff999")
    st = pub.read_state()
    assert st["last_local_head"].startswith("abc123")
    assert st["remote_commit"] == "fff999" and st["ts"] > 0


def test_mirror_default_takes_state(tmp_path, monkeypatch):
    """--mirror-since 缺省：状态文件值自动取（CLI 层教学行）。"""
    p = tmp_path / "repo"
    p.mkdir()
    (tmp_path / "repo" / ".regress").mkdir()
    for a in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(a, cwd=str(p), check=True)
    (p / "a.txt").write_text("1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "中文首批（001）"], cwd=str(p), check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(p),
                          capture_output=True, text=True, check=True).stdout.strip()
    (p / "a.txt").write_text("2\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "中文二批（002）"], cwd=str(p), check=True)
    import json as _json
    (p / ".regress" / "publish-state.json").write_text(
        _json.dumps({"last_local_head": base, "remote_commit": "x", "ts": 1}),
        encoding="utf-8")
    r = subprocess.run([sys.executable, SCRIPT, "--dry-run"],
                       cwd=str(p), capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert "自动取状态" in r.stdout and "（002）" in r.stdout


def test_no_state_no_rev_teaches(tmp_path):
    """无状态且未给 rev：报错教学不空猜。"""
    p = tmp_path / "repo"
    p.mkdir()
    (p / ".regress").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(p), check=True)
    r = subprocess.run([sys.executable, SCRIPT, "--dry-run"],
                       cwd=str(p), capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
                       timeout=60)
    assert r.returncode == 2 and "不空猜" in r.stderr


def test_check_message_accepts_ref_with_note():
    """（NNN，附注）形态合法（096 活体：发布道曾硬拦自家镜像消息）。"""
    pub = _load()
    assert pub.check_message("v1.87.3 发布状态文件（096，哨兵轮）：x") == []


# ─── 批163 tag 双写（版本取 plugin.json；幂等；失败不 fail 发布） ──

def _mini_repo(p):
    p.mkdir()
    for a in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(a, cwd=str(p), check=True)
    (p / "a.txt").write_text("1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "中文首批（001）"], cwd=str(p),
                   check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(p),
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def test_plugin_version_reads_authoritative_source():
    """版本权威源 = .zcode-plugin/plugin.json（非 commit 主题——有歧义）。"""
    import json
    pub = _load()
    with open(os.path.join(os.path.dirname(SCRIPT), "..",
                           ".zcode-plugin", "plugin.json"),
              encoding="utf-8") as f:
        expected = json.load(f)["version"]
    assert pub._plugin_version() == expected and expected


def test_tag_local_idempotent(tmp_path, monkeypatch):
    """本地 tag：首打创建、重打跳过（幂等）。"""
    p = tmp_path / "repo"
    head = _mini_repo(p)
    monkeypatch.chdir(p)
    pub = _load()
    pub.tag_release(None, head, None)
    tags = subprocess.run(["git", "tag"], cwd=str(p), capture_output=True,
                          text=True).stdout.split()
    assert tags == [f"v{pub._plugin_version()}"]
    pub.tag_release(None, head, None)  # 第二次：已存在跳过，不炸
    tags2 = subprocess.run(["git", "tag"], cwd=str(p), capture_output=True,
                           text=True).stdout.split()
    assert tags2 == tags


def test_tag_no_version_skips(tmp_path, monkeypatch):
    """plugin.json 无 version → 跳过（不 fail 发布路径的教学位）。"""
    p = tmp_path / "repo"
    head = _mini_repo(p)
    monkeypatch.chdir(p)
    pub = _load()
    monkeypatch.setattr(pub, "_plugin_version", lambda: "")
    pub.tag_release(None, head, None)
    assert subprocess.run(["git", "tag"], cwd=str(p), capture_output=True,
                          text=True).stdout.strip() == ""


def test_tag_remote_paths(tmp_path, monkeypatch):
    """远端三态：成功建 ref / 422 已存在跳过 / 其他失败 warn 不 raise。"""
    p = tmp_path / "repo"
    head = _mini_repo(p)
    monkeypatch.chdir(p)
    pub = _load()

    calls = []

    def _api_ok(tok, path, data=None, method=None):
        calls.append((path, data))
        return {}

    monkeypatch.setattr(pub, "_api", _api_ok)
    pub.tag_release("tok", head, "remoteabc")
    assert any(d and d.get("ref", "").startswith("refs/tags/v")
               and d["sha"] == "remoteabc" for _, d in calls)

    def _api_422(tok, path, data=None, method=None):
        raise Exception("HTTP Error 422: Reference already exists")

    monkeypatch.setattr(pub, "_api", _api_422)
    pub.tag_release("tok", head, "remoteabc")  # 已存在：跳过不炸

    def _api_boom(tok, path, data=None, method=None):
        raise Exception("HTTP Error 502")

    monkeypatch.setattr(pub, "_api", _api_boom)
    pub.tag_release("tok", head, "remoteabc")  # 其他失败：不 raise（书签非门禁）


def test_cli_dry_run_shows_tag_plan(tmp_path):
    """dry-run 预告 tag 计划（零网络零 token 的面也教学）。"""
    p = tmp_path / "repo"
    _mini_repo(p)
    r = subprocess.run(
        [sys.executable, SCRIPT, "--dry-run", "-m", "中文试发布（001）"],
        cwd=str(p), capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "HOME": str(p)}, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "tag 计划" in r.stdout
