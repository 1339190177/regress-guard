"""test_cache 的单元测试（v1.85，074 门禁测试结果缓存）。

覆盖：tree_key 键稳定性/敏感性（tracked 改、未跟踪增、.regress 排除——
死循环回归钉）、非 git 旁路、lookup TTL/只认 pass、enabled 双开关、record 裁剪。
"""
import sys
import os
import json
import time
import subprocess

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)

import test_cache


def _git_repo(tmp_path):
    """带一次初始提交的 tmp git 仓。"""
    p = tmp_path / "repo"
    p.mkdir()
    for args in (["git", "init", "-q"],
                 ["git", "config", "user.email", "t@t.com"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(args, cwd=str(p), check=True)
    (p / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(p), check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(p), check=True)
    return p


_PASS = {"runner": "pytest", "status": "pass", "passed": 3, "total": 3}


# ─── tree_key ────────────────────────────────────────

def test_key_stable_same_tree(tmp_path):
    r = _git_repo(tmp_path)
    assert test_cache.tree_key(str(r)) == test_cache.tree_key(str(r))


def test_key_sensitive_tracked_edit(tmp_path):
    r = _git_repo(tmp_path)
    k1 = test_cache.tree_key(str(r))
    (r / "a.txt").write_text("changed\n", encoding="utf-8")
    assert test_cache.tree_key(str(r)) != k1


def test_key_sensitive_untracked_add(tmp_path):
    r = _git_repo(tmp_path)
    k1 = test_cache.tree_key(str(r))
    (r / "new.txt").write_text("n\n", encoding="utf-8")
    assert test_cache.tree_key(str(r)) != k1


def test_key_ignores_regress_runtime(tmp_path):
    """死循环回归钉：.regress/（含缓存文件自身）不得入键（顾问点根治）。"""
    r = _git_repo(tmp_path)
    k1 = test_cache.tree_key(str(r))
    rg = r / ".regress"
    rg.mkdir()
    (rg / "test-cache.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    (rg / "history.jsonl").write_text('{"x": 2}\n', encoding="utf-8")
    assert test_cache.tree_key(str(r)) == k1


def test_key_ignores_tracked_regress(tmp_path):
    """跟踪态回归钉：.regress 已入 git 的项目，门禁写 done 戳不改键。"""
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    (rg / "manifests").mkdir()
    (rg / "manifests" / "R1.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(r), check=True)
    subprocess.run(["git", "commit", "-qm", "gov"], cwd=str(r), check=True)
    k1 = test_cache.tree_key(str(r))
    (rg / "manifests" / "R1.md").write_text("status: done\n", encoding="utf-8")
    assert test_cache.tree_key(str(r)) == k1


def test_key_staged_equals_unstaged(tmp_path):
    """狗粮标本一号回归钉：同内容不同暂存态 = 同一棵树。"""
    r = _git_repo(tmp_path)
    (r / "a.txt").write_text("dirty\n", encoding="utf-8")   # 未暂存态
    k1 = test_cache.tree_key(str(r))
    subprocess.run(["git", "add", "-A"], cwd=str(r), check=True)  # 暂存态
    assert test_cache.tree_key(str(r)) == k1


def test_key_untracked_staged_equals(tmp_path):
    """狗粮标本二号回归钉（076 翻车原景）：未跟踪→git add，键不变。"""
    r = _git_repo(tmp_path)
    (r / "new.txt").write_text("brand new\n", encoding="utf-8")  # 未跟踪
    k1 = test_cache.tree_key(str(r))
    subprocess.run(["git", "add", "-A"], cwd=str(r), check=True)
    assert test_cache.tree_key(str(r)) == k1


def test_key_sensitive_tracked_delete(tmp_path):
    """tracked 文件删除（工作树缺失）键必变。"""
    r = _git_repo(tmp_path)
    k1 = test_cache.tree_key(str(r))
    (r / "a.txt").unlink()
    assert test_cache.tree_key(str(r)) != k1


def test_key_none_outside_git(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert test_cache.tree_key(str(d)) is None


# ─── enabled 双开关 ──────────────────────────────────

def test_env_off_disables(tmp_path, monkeypatch):
    r = _git_repo(tmp_path)
    monkeypatch.setenv("RG_TEST_CACHE", "off")
    assert test_cache.enabled(str(r)) is False
    assert test_cache.lookup(str(r), str(r / ".regress")) is None


def test_config_off_disables(tmp_path):
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    (rg / "config.json").write_text(
        '{"test_cache": {"enabled": false}}', encoding="utf-8")
    assert test_cache.enabled(str(r)) is False


def test_default_on(tmp_path):
    r = _git_repo(tmp_path)
    assert test_cache.enabled(str(r)) is True


# ─── record / lookup ─────────────────────────────────

def test_record_lookup_roundtrip(tmp_path):
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    assert test_cache.record(str(r), str(rg), dict(_PASS)) is True
    hit = test_cache.lookup(str(r), str(rg))
    assert hit is not None
    assert hit["result"]["passed"] == 3
    assert 0 <= hit["age_min"]


def test_record_rejects_fail(tmp_path):
    """只缓存通过：fail 不落账（文件不增长）。"""
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    assert test_cache.record(str(r), str(rg),
                             {"status": "fail", "passed": 1, "total": 3}) is False
    assert not (rg / "test-cache.jsonl").exists()


def test_lookup_ttl_expiry(tmp_path):
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    test_cache.record(str(r), str(rg), dict(_PASS))
    f = rg / "test-cache.jsonl"
    lines = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines[0]["ts"] = time.time() - 999 * 60  # 远超默认 TTL 240min
    f.write_text("\n".join(json.dumps(ln) for ln in lines) + "\n", encoding="utf-8")
    assert test_cache.lookup(str(r), str(rg)) is None


def test_record_trims(tmp_path):
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir()
    for i in range(60):
        test_cache.record(str(r), str(rg), dict(_PASS, passed=i))
    lines = [ln for ln in (rg / "test-cache.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) <= 50


# ─── 批156：incremental scope 隔离（污染陷阱钉死） ────────────────

def test_incremental_entry_recorded_but_not_replayed(tmp_path):
    """增量子集结果落账带 scope=incremental，lookup 永不回放——子集计数
    不冒充全量（勘察实证的缓存污染陷阱）。"""
    proj = _git_repo(tmp_path)
    rg = proj / ".regress"
    rg.mkdir()
    full = {"status": "pass", "runner": "pytest", "passed": 100, "total": 100}
    assert test_cache.record(str(proj), str(rg), full) is True
    hit = test_cache.lookup(str(proj), str(rg))
    assert hit and hit["result"]["total"] == 100
    # incremental 条目：同树（key 相同）后写，带 scope
    incr = {"status": "pass", "runner": "pytest", "passed": 2, "total": 2,
            "incremental": True}
    assert test_cache.record(str(proj), str(rg), incr,
                             scope="incremental") is True
    hit2 = test_cache.lookup(str(proj), str(rg))
    # 回放的是全量条目（100）而非最新 incremental（2）——隔离生效
    assert hit2 and hit2["result"]["total"] == 100


# ─── v1.108（批160 §17）：record 并发落账锁 ────────────────

def test_record_concurrent_both_survive(tmp_path):
    """两进程并发 record 同树 → 两条都在（读改写互相覆盖丢一条的正确性洞，
    v1.108 file_lock 临界区的契约锁——锁缺席平台丢条同样是真回归）。"""
    r = _git_repo(tmp_path)
    rg = r / ".regress"
    rg.mkdir(exist_ok=True)
    script = (
        "import sys; sys.path.insert(0, %r); "
        "from test_cache import record; "
        "sys.exit(0 if record(%r, %r, {'runner': 'pytest', 'status': 'pass',"
        "'passed': 1, 'total': 1}) else 1)"
        % (LIB, str(r), str(rg)))
    procs = [subprocess.Popen([sys.executable, "-c", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(2)]
    for p in procs:
        assert p.wait(timeout=60) == 0, p.stderr.read().decode()
    lines = [ln for ln in (rg / "test-cache.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, "并发落账丢条（§17 读改写临界区失效）"
