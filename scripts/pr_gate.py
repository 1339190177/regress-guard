#!/usr/bin/env python3
"""pr_gate —— PR 机械评审闸门（批174，PR 评审事件化的机械层）。

属主协议：docs/pr-auto-review.md（六判据+阻断项+分档）。本脚本承担其中
全部机器可判部分（①边界③描述④hermetic⑤判据机械化⑥人类信号，②体量
记录性）；判据⑤的机械化口径=清单验收行要么自带已验标记（门禁盖过）、
要么是与 hermetic 测试结果可对账的 N/N 模式——两者皆不满足=含糊，
升级不猜（"该升不升"是假阴性通道，宁可多问人）。

形态（health_probe 聚合器模式）：
  单 PR：pr_gate.py --repo owner/name --pr N [--json] [--comment]
  扫描：pr_gate.py --sweep          # 读 pr-review-repos.json，按 pr_review.mode 分档执行
退出码：0=机械判据全过；1=判据红/含糊（升级态）；2=用法/自崩。

红线内置：只碰注册表内的仓（--repo 单 PR 模式仅限人工显式调用）；
升级不拒绝（关闭/拒绝永远是人）；token 永不回显（gh 自管凭据）；
journal 落账 kind=pr_review；合并/升级必推 WeCom（观察层）。
"""
import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB = os.path.join(REPO_ROOT, "hooks", "scripts", "lib")
sys.path.insert(0, _LIB)  # critic_pass.py:28-30 先例
try:
    from manifest_parser import parse_frontmatter, ears_extract
except ImportError:  # 静默失效无告警=新失察层（critic_pass 教训）
    print("pr_gate: manifest_parser 不可导入——lib 目录异常", file=sys.stderr)
    sys.exit(2)

GUARD_ROOT = os.path.expanduser("~/.zcode/regress-guard-hooks")
REGISTRY = os.path.expanduser(
    "~/.zcode/workspace/default/.regress/pr-review-repos.json")
WORKSPACE = os.path.expanduser("~/.zcode/workspace/default")
SUPERAGENT_DB = os.path.expanduser("~/.dsh/state/superagent/orchestrator.sqlite")

DEFAULT_SECTIONS = ["背景", "改动", "验证"]
DEFAULT_MAX_LINES = 200          # 记录性阈值（v2.7.3 起不阻断）
VERIFIED_MARKS = ("✅", "已验", "（过）", "通过")
RATIO_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _gh(args, timeout=60):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}… 失败: {r.stderr.strip()[:150]}")
    return r.stdout


def _notify(title, body):
    """best-effort WeCom 推送（观察层：每合并/升级必推）。"""
    try:
        subprocess.run(
            ["python3", os.path.join(GUARD_ROOT, "lib", "notify.py"), ".", "chat",
             "--title", title, "--body", body],
            cwd=WORKSPACE, capture_output=True, timeout=30)
    except Exception:
        pass


def _journal(fields):
    try:
        subprocess.run(
            ["python3", os.path.join(GUARD_ROOT, "lib", "journal.py"),
             WORKSPACE, "add", "pr_review",
             json.dumps(fields, ensure_ascii=False)],
            capture_output=True, text=True, timeout=15)
    except Exception:
        pass


def _path_forbidden(path, forbidden):
    p = path.lstrip("/")
    for pat in forbidden or []:
        if fnmatch.fnmatch(p, pat.lstrip("/")) or fnmatch.fnmatch(path, pat):
            return True
    return False


def check_boundary(files, manifest_files, forbidden):
    """①：diff 文件 ⊆ 清单 planned ∪ .regress/**；不触禁改区。"""
    allowed = set(manifest_files) | {".regress"}
    for f in files:
        if _path_forbidden(f, forbidden):
            return False, f"触禁改区: {f}"
        if f not in allowed and not f.startswith(".regress/"):
            return False, f"清单外文件: {f}"
    return True, ""


def check_sections(body, required):
    """③：PR 描述段落在场。"""
    missing = [s for s in required if f"## {s}" not in (body or "")]
    return (not missing), ("缺段: " + ",".join(missing) if missing else "")


def check_criteria(ears_rows, passed, total):
    """⑤机械化：验收行逐条找机器可对账的证据；含糊/矛盾 → 升级。

    口径（保守）：行含已验标记（门禁盖过）=过；行含 N/N 且与 hermetic
    结果一致=过、不一致=矛盾；行含"全绿/全过"且测试全过=过；其余=含糊。
    """
    for row in ears_rows:
        if any(m in row for m in VERIFIED_MARKS):
            continue
        m = RATIO_RE.search(row)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if not (a == b == passed == total):
                return False, f"判据矛盾: 「{row[:40]}」 vs hermetic {passed}/{total}"
            continue
        if ("全绿" in row or "全过" in row) and passed == total and total > 0:
            continue
        return False, f"判据含糊(不可机械化): 「{row[:40]}」"
    return True, ""


def review_pr(repo, number, cfg, json_out=False):
    """单 PR 机械评审：返回 (rows, verdict_dict)。抛错=自崩（exit 2）。"""
    meta = json.loads(_gh(["pr", "view", str(number), "-R", repo, "--json",
                           "title,body,files,additions,deletions,reviews,mergeable,author"]))
    tmp = tempfile.mkdtemp(prefix="prgate-")
    try:
        # hermetic 检出（协议第 4 步命令序列）
        wt = os.path.join(tmp, "repo")
        subprocess.run(["git", "clone", "--quiet",
                        f"https://github.com/{repo}.git", wt],
                       check=True, capture_output=True, timeout=300)
        subprocess.run(["git", "-C", wt, "fetch", "--quiet", "origin",
                        f"pull/{number}/head"], check=True, capture_output=True, timeout=120)
        subprocess.run(["git", "-C", wt, "checkout", "--quiet", "FETCH_HEAD"],
                       check=True, capture_output=True, timeout=60)
        # 仓配置以 hermetic clone 内的 .regress 为权威（随仓分发），外部传入仅兜底
        clone_cfg = os.path.join(wt, ".regress", "config.json")
        if os.path.exists(clone_cfg):
            try:
                cfg = json.load(open(clone_cfg, encoding="utf-8"))
            except Exception:
                pass
        # 清单（PR 内随单提交的 .regress/manifests/*.md）与判据配置
        pr_review_cfg = cfg.get("pr_review", {})
        sections = pr_review_cfg.get("require_pr_sections", DEFAULT_SECTIONS)
        forbidden = (cfg.get("boundary") or {}).get("forbidden", [])
        mdir = os.path.join(wt, ".regress", "manifests")
        manifest_files, ears_rows = [], []
        if os.path.isdir(mdir):
            for name in sorted(os.listdir(mdir)):
                if not name.endswith(".md"):
                    continue
                mp = os.path.join(mdir, name)
                data = parse_frontmatter(mp) or {}
                manifest_files += [c.get("file") for c in
                                   (data.get("planned_changes") or [])
                                   if isinstance(c, dict) and c.get("file")]
                _, rows = ears_extract(mp)
                ears_rows += rows
        # hermetic 测试（test_runner CLI 与提交门禁同一事实源）
        tr = subprocess.run(["python3",
                             os.path.join(GUARD_ROOT, "lib", "test_runner.py"), wt],
                            capture_output=True, text=True, timeout=1800)
        try:
            tres = json.loads(tr.stdout or "{}")
        except json.JSONDecodeError:
            tres = {}
        passed, total = tres.get("passed", -1), tres.get("total", -1)
        tests_ok = tr.returncode == 0 and tres.get("status") == "pass"

        rows, fail = [], ""
        ok, why = check_boundary([f["path"] for f in meta["files"]],
                                 manifest_files, forbidden)
        rows.append((ok, f"①边界 {why}"))
        fail = fail or ("" if ok else why)
        size = meta["additions"] + meta["deletions"]
        rows.append((True, f"②体量 {size}（记录性）"))
        ok, why = check_sections(meta.get("body"), sections)
        rows.append((ok, f"③描述 {why}"))
        fail = fail or ("" if ok else why)
        rows.append((tests_ok, f"④hermetic {passed}/{total}"))
        fail = fail or ("" if tests_ok else f"hermetic {passed}/{total}")
        ok, why = check_criteria(ears_rows, passed, total) if ears_rows else (False, "PR 内无清单验收行")
        rows.append((ok, f"⑤判据机械化 {why}"))
        fail = fail or ("" if ok else why)
        bad_reviews = [r["state"] for r in meta.get("reviews", [])
                       if r.get("state") == "CHANGES_REQUESTED"]
        mergeable = meta.get("mergeable") == "MERGEABLE"
        ok = (not bad_reviews) and mergeable
        rows.append((ok, f"⑥人类信号 reviews={bad_reviews or '无'} mergeable={meta.get('mergeable')}"))
        fail = fail or ("" if ok else "人类信号红（changes-requested 或冲突）")
        verdict = {
            "repo": repo, "pr": number, "author": meta["author"]["login"],
            "size": size, "passed": passed, "total": total,
            "mode": pr_review_cfg.get("mode", "auto-merge"),
            "mechanical_pass": not fail, "fail_reason": fail,
            "ears_rows": ears_rows, "rows": [[("✓" if ok else "✗"), msg] for ok, msg in rows],
        }
        if json_out:
            print(json.dumps(verdict, ensure_ascii=False))
        else:
            for mark, msg in verdict["rows"]:
                print(f"  {mark} {msg}")
            print(f"判定: {'机械全过' if not fail else '升级——' + fail}")
        return verdict
    finally:
        if tmp.startswith(tempfile.gettempdir() + "/prgate-"):
            shutil.rmtree(tmp, ignore_errors=True)  # 只清自建前缀目录


def _close_linked_issues(repo, number, body):
    for m in set(re.findall(r"[Ii]ssue\s*#(\d+)", body or "") +
                 re.findall(r"/issues/(\d+)", body or "")):
        _gh(["issue", "close", m, "-R", repo, "--comment",
             f"PR#{number} 已通过机械评审自动合并——工单闭环。"])


def sweep():
    """扫描注册表内各仓的开放 agent PR，按 pr_review.mode 分档执行。"""
    with open(REGISTRY, encoding="utf-8") as f:
        repos = json.load(f)
    merged, escalated = [], []
    for entry in repos:
        repo, agent = entry["repo"], entry["agent_login"]
        try:
            open_prs = json.loads(_gh(["pr", "list", "-R", repo,
                "--author", agent, "--state", "open", "--json", "number"]))
        except Exception as e:
            escalated.append(f"{repo}: 枚举失败 {e}")
            continue
        for pr in open_prs:
            n = pr["number"]
            try:
                v = review_pr(repo, n, {})
            except Exception as e:
                escalated.append(f"{repo}#{n}: 自崩 {str(e)[:100]}")
                continue
            mode = v["mode"]  # 权威源=仓内 .regress（hermetic clone 读得）
            fields = {"repo": repo, "pr": n, "mode": "machine",
                      "decision": "merged" if v["mechanical_pass"] and mode == "auto-merge" else
                                  ("recommend" if v["mechanical_pass"] else "escalate"),
                      "fail_reason": v["fail_reason"], "tier": mode}
            _journal(fields)
            if not v["mechanical_pass"]:
                escalated.append(f"{repo}#{n}: {v['fail_reason']}")
                _gh(["pr", "comment", str(n), "-R", repo, "--body",
                     f"机械评审升级：{v['fail_reason']}（判据逐项见 journal pr_review）——留人类/LLM 裁决。"])
                continue
            if mode == "auto-merge":
                _gh(["pr", "merge", str(n), "-R", repo, "--merge", "--subject",
                     f"auto-review: passed (机械判据全绿·hermetic {v['passed']}/{v['total']})"])
                merged.append(f"{repo}#{n}（{v['passed']}/{v['total']}）")
                # 关联 issue 闭环：body 里的 Issue #N
                meta_body = json.loads(_gh(["pr", "view", str(n), "-R", repo,
                    "--json", "body"]))["body"]
                _close_linked_issues(repo, n, meta_body)
            elif mode == "human-merge":
                _gh(["pr", "comment", str(n), "-R", repo, "--body",
                     "机械评审全过——建议合并（human-merge 档，等人类执行）。"])
                merged.append(f"{repo}#{n} 建议合（human-merge 档）")
            # review-only 档：仅落账
    # ⑦ 拒绝面：superagent 24h 内 ignore 决定未处置 → 提行
    ignored = []
    if os.path.exists(SUPERAGENT_DB):
        try:
            r = subprocess.run(["sqlite3", SUPERAGENT_DB,
                "select at || '|' || value from decision "
                "where at >= datetime('now','-1 day')"],
                capture_output=True, text=True, timeout=15)
            now_ignored = True  # 行内过滤见下（kind=ignore 精确判定）
            for line in (r.stdout or "").splitlines():
                if '"ignore"' not in line:
                    continue
                try:
                    d = json.loads(line.split("|", 1)[1])
                except Exception:
                    continue
                if d.get("kind") == "ignore":
                    ignored.append(d.get("threadKey", "?"))
            ignored = list(dict.fromkeys(ignored))
        except Exception:
            pass
    # 推送纪律：有料才推，单条合并
    parts = []
    if merged:
        parts.append("已合并: " + "; ".join(merged))
    if escalated:
        parts.append("升级待裁: " + "; ".join(escalated))
    if ignored:
        parts.append("近24h被拒未处置: " + ", ".join(dict.fromkeys(ignored)))
    if parts:
        _notify(f"pr-gate 扫描：{len(merged)}合/{len(escalated)}升",
                "；".join(parts)[:900])
    print(f"pr_gate sweep: {len(merged)} merged/recommended, {len(escalated)} escalated"
          + (f", {len(ignored)} ignored-notice" if ignored else ""))
    return 0 if not escalated else 1


def main():
    ap = argparse.ArgumentParser(prog="pr_gate")
    ap.add_argument("--repo", help="owner/name（单 PR 模式）")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--sweep", action="store_true", help="注册表扫描模式")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--comment", action="store_true", help="结果评论到 PR")
    args = ap.parse_args()
    try:
        if args.sweep:
            sys.exit(sweep())
        if not (args.repo and args.pr):
            ap.error("需要 --repo 与 --pr，或 --sweep")
        cfg_path = os.path.expanduser(
            f"~/src/{args.repo.split('/')[1]}/.regress/config.json")
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        v = review_pr(args.repo, args.pr, cfg, json_out=args.json)
        if args.comment:
            _gh(["pr", "comment", str(args.pr), "-R", args.repo, "--body",
                 "pr_gate 机械评审：\n" + "\n".join(
                     f"- {m} {d}" for m, d in v["rows"])])
        sys.exit(0 if v["mechanical_pass"] else 1)
    except subprocess.TimeoutExpired:
        print("pr_gate: 步骤超时", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # 自崩大声（health_probe 语义）
        print(f"pr_gate: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
