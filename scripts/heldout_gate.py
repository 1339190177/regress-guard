#!/usr/bin/env python3
"""held-out 验收门（v1.90.0，批 106：稳定性条件 1 的补法）。

真 held-out 的判定：期望值不住在可被本批合法改写的 tests/ 里。本门的八场景
冻结束直连 hooks/scripts 各脚本（run_guard 契约：JSON stdin + CLAUDE_PROJECT_DIR
subprocess），期望与实况对账；基线住工作区 .regress/heldout-baseline.json
（树键排除面），束摘要哈希钉住——改场景必须显式 --refreeze（journal 留痕），
防静默削弱=Goodhart 锁（稳定性条件表第 1 行 Absent→Partial 的实体）。

exit 语义：0=对账通过（含首跑自动冻结/改善只报不拦）；3=退化（过→不过）；
4=束哈希变（需显式重冻）；其它=束自身故障（调用方 fail-open 记 note）。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "hooks", "scripts", "pre_commit_guard.py")
VALVE = os.path.join(ROOT, "hooks", "scripts", "execution_valve.py")

_S_MANIFEST = ("---\nid: R1\nstatus: in-progress\ntier: S\n"
               "rollback: git revert\nplanned_changes:\n  - id: F1\n"
               "    file: src/app.js\nactual_changes: []\n---\n")
_M_MANIFEST = ("---\nid: R1\nstatus: in-progress\ntier: M\n"
               "rollback: git revert\n"
               "understood_intent:\n"
               "  复述: \"补 held-out 束\"\n"
               "  边界: \"只测门禁契约\"\n"
               "  判据: \"验收全过\"\n"
               "scan:\n"
               "  entry: \"hooks/scripts/pre_commit_guard.py\"\n"
               "  test: \"python3 -m pytest test_smoke.py -q\"\n"
               "  card: \"钩子拦截链\"\n"
               "planned_changes:\n  - id: F1\n"
               "    file: src/app.js\nactual_changes: []\n---\n"
               "\n## 验收标准\n\n"
               "- When 发起请求，则 返回 200（验：python3 -m pytest test_smoke.py -q）✅\n")


def _git(p, *args):
    subprocess.run(["git", *args], cwd=str(p), check=True,
                   capture_output=True)


def _mk_project(root, name="proj", manifest=_S_MANIFEST, runner=False,
                stage="src/app.js", content="x = 1\n"):
    p = root / name
    (p / "src").mkdir(parents=True)
    (p / ".regress" / "manifests").mkdir(parents=True)
    _git(p, "init", "-q")
    _git(p, "config", "user.email", "t@t.com")
    _git(p, "config", "user.name", "t")
    (p / ".regress" / "manifests" / "R1.md").write_text(
        manifest, encoding="utf-8")
    if runner:
        (p / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (p / "test_smoke.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8")
    if stage:
        (p / stage).write_text(content, encoding="utf-8")
        _git(p, "add", "-A")
    return p


def _mk_sub(root, name, files):
    p = root / name
    p.mkdir(parents=True)
    _git(p, "init", "-q")
    _git(p, "config", "user.email", "t@t.com")
    _git(p, "config", "user.name", "t")
    for rel, text in files.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "init")
    return p


def _sh(script, command, project):
    """run_guard 契约：JSON stdin、剥离会话变量、钉 PROJECT_DIR。"""
    env = dict(os.environ)
    env.pop("CLAUDE_SESSION_ID", None)
    env.pop("ZCODE_SESSION_ID", None)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    inp = json.dumps({"tool_name": "Bash",
                      "tool_input": {"command": command}})
    proc = subprocess.run(
        ["python3", script], input=inp, capture_output=True, text=True,
        env=env, cwd=str(project), timeout=30)
    return proc.returncode, proc.stderr


def _sc_h1(root):  # 复合暂存+提交拦（091）
    p = _mk_project(root, "h1")
    return GUARD, "git add src/app.js && git commit -m 改动（R1）", p


def _sc_h2(root):  # M 计数缺席拦（105）
    p = _mk_project(root, "h2", manifest=_M_MANIFEST, runner=True)
    return GUARD, "git commit -m 改动（R1）说明", p


def _sc_h3(root):  # 计数不符拦（092）
    p = _mk_project(root, "h3", manifest=_M_MANIFEST, runner=True)
    return GUARD, "git commit -m 改动（R1）说明；5/5", p


def _sc_h4(root):  # F3 暂存越界拦
    p = _mk_project(root, "h4", manifest=_S_MANIFEST, runner=True,
                    stage="src/other.js")
    return GUARD, "git commit -m 改动（R1）说明", p


def _sc_h5(root):  # M 缺清单号拦（092）
    p = _mk_project(root, "h5", manifest=_M_MANIFEST, runner=True)
    return GUARD, "git commit -m 改动说明", p


def _sc_h6(root):  # 执行阀令牌（灾难模式拒，零副作用——命令永不真执行）
    p = _mk_project(root, "h6", stage=None)
    return VALVE, "mkfs.ext4 /dev/sdz9", p


def _sc_h7(root):  # 泛型名不锚定子仓（103，放行场景）
    p = _mk_project(root, "h7", manifest=_S_MANIFEST.replace(
        "file: src/app.js", "file: README.md"), runner=True, stage=None)
    (p / "README.md").write_text("p\n", encoding="utf-8")
    _git(p, "add", "-A")
    demo = _mk_sub(root, "demo-project", {
        "README.md": "demo\n", ".gitignore": "x\n",
        "src/math.js": "m = 1\n"})
    (demo / "src" / "math.js").write_text("m = 2\n", encoding="utf-8")
    _git(demo, "add", "-A")  # 陈旧暂存标本：不得混入
    return GUARD, "git commit -m 改动（R1）", p


def _sc_h8(root):  # 验收未勾拦（v1.55）
    m = _M_MANIFEST.replace("✅\n", "\n")  # 摘掉勾=未验
    p = _mk_project(root, "h8", manifest=m, runner=True)
    return GUARD, "git commit -m 改动（R1）说明；1/1", p


def _sc_h9(root):  # 密钥泄漏拦（v1.42 供应链层）——假 AKIA 键（非白名单示例值）
    p = _mk_project(root, "h9", manifest=_S_MANIFEST.replace(
        "file: src/app.js", "file: config.py"), runner=True,
        stage="config.py", content='key = "AKIAZZYYXXWWVVUUTSRQ"\n')
    return GUARD, "git commit -m 改动（R1）", p


def _sc_h10(root):  # 缓存伪键拒绝（v1.85 键敏感契约）——错误键条目不命中，
    # 门禁照常全量跑（stderr 无 ♻️）；断言走 expect_none 特判
    p = _mk_project(root, "h10", manifest=_S_MANIFEST, runner=True)
    cc = p / ".regress" / "test-cache.jsonl"
    import json as _j
    import time as _t
    cc.write_text(_j.dumps({"key": "deadbeef", "status": "pass",
                            "ts": _t.time()}) + "\n", encoding="utf-8")
    return GUARD, "git commit -m 改动（R1）", p


SCENARIOS = [
    {"id": "H1-compound", "build": _sc_h1, "code": 2, "has": "复合"},
    {"id": "H2-count-absent", "build": _sc_h2, "code": 2, "has": "计数"},
    {"id": "H3-count-mismatch", "build": _sc_h3, "code": 2, "has": "不符"},
    {"id": "H4-staged-undeclared", "build": _sc_h4, "code": 2, "has": "不在回归清单"},
    {"id": "H5-no-manifest-ref", "build": _sc_h5, "code": 2, "has": "清单号"},
    {"id": "H6-valve-token", "build": _sc_h6, "code": 2, "has": "不可逆"},
    {"id": "H7-generic-no-anchor", "build": _sc_h7, "code": 0, "has": ""},
    {"id": "H8-acceptance-open", "build": _sc_h8, "code": 2, "has": "验收未勾"},
    {"id": "H9-secret-leak", "build": _sc_h9, "code": 2, "has": "密钥"},
    {"id": "H10-cache-poison-key", "build": _sc_h10, "code": 0,
     "has": "", "expect_none": "♻️"},
]


def scenarios_digest(scenarios):
    """束摘要哈希：钉住 id+期望（code/has）——防静默改场景（Goodhart 锁）。
    build 函数不可序列化，脚本归属经 id 间接钉住（场景 id 与目标脚本是稳定映射）。"""
    core = [{"id": s["id"], "code": s["code"], "has": s["has"],
             "expect_none": s.get("expect_none") or ""}
            for s in scenarios]
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def baseline_path(project_dir):
    return os.path.join(str(project_dir), ".regress", "heldout-baseline.json")


def run_battery(scenarios=SCENARIOS, verbose=True):
    """跑全束，返回 {id: pass|fail}（pass=与冻结期望一致）。"""
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="heldout-") as td:
        from pathlib import Path
        root = Path(td)
        for s in scenarios:
            try:
                script, command, proj = s["build"](root)
                code, err = _sh(script, command, proj)
                ok = (code == s["code"]
                      and (not s["has"] or s["has"] in err)
                      and (not s.get("expect_none")
                           or s["expect_none"] not in err))
                outcomes[s["id"]] = "pass" if ok else "fail"
            except Exception as e:  # 束故障≠退化：记 fail 但调用方按 5 处理
                outcomes[s["id"]] = f"error:{type(e).__name__}"
            if verbose:
                print(f"  {outcomes[s['id']]:>5}  {s['id']}", file=sys.stderr)
    return outcomes


def _journal(project_dir, kind, **fields):
    try:
        lib = os.path.join(ROOT, "hooks", "scripts", "lib")
        sys.path.insert(0, lib)
        from journal import journal_append
        journal_append(kind, start_dir=str(project_dir), **fields)
    except Exception:
        pass  # 地层是增强不是依赖


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get(
        "CLAUDE_PROJECT_DIR") or os.getcwd())
    ap.add_argument("--refreeze", action="store_true")
    args = ap.parse_args()
    bp = baseline_path(args.project)
    digest = scenarios_digest(SCENARIOS)

    old = None
    if os.path.exists(bp):
        try:
            old = json.load(open(bp, encoding="utf-8"))
        except Exception:
            old = None

    if args.refreeze:
        outcomes = run_battery(SCENARIOS)
        json.dump({"digest": digest, "outcomes": outcomes,
                   "frozen_at": datetime.now().isoformat()},
                  open(bp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        _journal(args.project, "heldout_refrozen", digest=digest,
                 outcomes=outcomes)
        print(f"held-out 基线已重冻（{digest}）", file=sys.stderr)
        return 0

    if old and old.get("digest") != digest:
        print("REGRESS-GUARD: held-out 场景束已变（摘要不匹配）——期望改动"
              "必须显式：python3 scripts/heldout_gate.py --refreeze"
              "（journal 留痕），不许静默改场景。", file=sys.stderr)
        return 4

    outcomes = run_battery(SCENARIOS)

    if old is None:  # 首跑冻结
        json.dump({"digest": digest, "outcomes": outcomes,
                   "frozen_at": datetime.now().isoformat()},
                  open(bp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        _journal(args.project, "heldout_baseline_frozen", digest=digest)
        print(f"held-out 基线首冻（{len(SCENARIOS)} 场景）", file=sys.stderr)
        return 0

    prev = old.get("outcomes") or {}
    regressed = [i for i, o in outcomes.items()
                 if prev.get(i) == "pass" and o != "pass"]
    improved = [i for i, o in outcomes.items()
                if prev.get(i) not in ("pass", None) and o == "pass"]
    if regressed:
        print(f"REGRESS-GUARD: held-out 退化——{', '.join(regressed)}："
              "冻结期望不再成立。修复行为；确属期望应演进则在批内说明后"
              " --refreeze。", file=sys.stderr)
        _journal(args.project, "heldout_regression",
                 regressed=regressed)
        return 3
    if improved:
        print(f"held-out 改善（{', '.join(improved)}）——建议 --refreeze 收编。",
              file=sys.stderr)
    errored = [i for i, o in outcomes.items() if str(o).startswith("error:")]
    if errored:
        print(f"held-out 束故障（{', '.join(errored)}）——fail-open 记档。",
              file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
