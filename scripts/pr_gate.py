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
# 批207：mergeable=UNKNOWN 的 defer 阈值——90s sweep × 4 ≈ 6min，远超 GitHub
# 常规合并性计算延迟（秒级）；连续 4 轮仍未知视为卡死，升级一次后封口
UNKNOWN_MAX_STREAK = 4
# 批218：review_pr 自崩的有界重评阈值——同节拍同语义（评审器侧异常可重试，
# 但 headRefKey 类全量崩不能每 90s 无限重试）。标本=tongtu PR#159：11:15 崩
# （批212 字段病）11:17 根修，旧代码崩即记 escalate 被去重封口→永不复评→
# 人肉双跑复核（人类评论"评审器零置评"）。
CRASH_MAX_STREAK = UNKNOWN_MAX_STREAK
DEFAULT_MAX_LINES = 200          # 记录性阈值（v2.7.3 起不阻断）
VERIFIED_MARKS = ("✅", "已验", "（过）", "通过")
RATIO_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
# 批212：工单号锚（长形式优先防 6 位被 3 位前缀截断——AGENTS 取号纪律正则同序）
REGRESS_ID_RE = re.compile(r"REGRESS-(?:[0-9]{6}-[0-9a-f]{4,8}|[0-9]{3})")


def _gh(args, timeout=60):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}… 失败: {r.stderr.strip()[:150]}")
    return r.stdout


def _notify(title, body):
    """best-effort WeCom 推送（观察层：每合并/升级必推）。"""
    try:
        subprocess.run(
            [sys.executable, os.path.join(GUARD_ROOT, "lib", "notify.py"), ".", "chat",
             "--title", title, "--body", body],
            cwd=WORKSPACE, capture_output=True, timeout=30)
    except Exception:
        pass


def _journal(fields):
    try:
        subprocess.run(
            [sys.executable, os.path.join(GUARD_ROOT, "lib", "journal.py"),
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


def fmt_hermetic(passed, total):
    """④/主题行计数口径：计数不可得(-1)时以 exit code 口径标 exit0，不显示误导性 -1/-1。"""
    return f"{passed}/{total}" if passed >= 0 else "exit0"


def _judge_human_signal(bad_reviews, mergeable_state):
    """⑥拆家（批184）：冲突与人审意见分道——CONFLICTING 走冲突自处理引擎，
    CHANGES_REQUESTED 才是等人审。旧文案两者混为「人类信号红」，worker 收到的
    升级评论无针对性指引（昨夜七单+今晨三 CONFLICTING 实证）。

    批207 三态化：UNKNOWN/缺失≠冲突——GitHub 合并性计算未回的瞬态被误判
    冲突（PR#94 实证：冲突解法指令发给无冲突的 worker + 每轮重评=重复通知，
    在途单卡死 9h+）。瞬态终态裁决归 sweep 侧 streak。"""
    if mergeable_state == "CONFLICTING":
        return False, "冲突（CONFLICTING）", True
    if mergeable_state != "MERGEABLE":
        return False, f"合并性未知（mergeable={mergeable_state}）", False
    if bad_reviews:
        return False, "人审意见（CHANGES_REQUESTED）——等人类评论", False
    return True, "", False


def conflict_directive(agent):
    """解法指令模板（agent 登录名取自注册表配置=权威源；发版卫生禁用户名字面量）。"""
    return _CONFLICT_TMPL.format(agent=agent)


_CONFLICT_TMPL = (
    "@{agent} 本 PR 与 dev 冲突（机械评审⑥），按冲突自解协议处理（AGENTS.md 机器通道第 10 条）：\n"
    "1 归因：git log 本分支..dev 找新合入项，映射工单号\n"
    "2 意图调和：读上游 PR 三段与清单——同特性链=下游适配上游；独立特性=语义并集保留\n"
    "3 merge dev 入本分支（禁 force push）；涉页面文件按 UI 取证范式补证\n"
    "4 本地 test_cmd 全绿后 push——hermetic 门禁自动复审，通过即自动合并\n"
    "串行规则：同仓多 PR 冲突按最小 PR 号先解，非目标请等待（解完自动轮到）。\n"
    "两轮未解：在本 PR 评论含「冲突熔断」四字，系统自动开接力工单（新 agent 接手）。")


def _has_break_marker(comments, self_login):
    """熔断标记：agent 在 PR 评论声明「冲突熔断」（本人发出的指令评论不算）。"""
    for c in comments or []:
        if "冲突熔断" in (c.get("body") or ""):
            author = (c.get("author") or {}).get("login", "")
            if author and author != self_login:
                return True
    return False


def _conflict_engine(repo, n, state, state_path, head, agent):
    """冲突自处理引擎（批184）：pero 单槽串行 × Mergify 冲突评论 × agent 意图合并。

    人类零参与（用户令）：⑥拆家后 CONFLICTING 独走——同仓同时只解最小 PR 号
    一张（单槽，解完 90s sweep 自动易主）；目标 PR 按轮次发解法指令（head 变化=
    新一轮）；worker 两轮不成评论「冲突熔断」→ 自动开 resolver 接力工单
    （agent 找 agent，人类只收 WeCom 知情不需行动）。"""
    rounds = state.setdefault("conflict_rounds", {})
    rk = f"{repo}#{n}"
    r = rounds.setdefault(rk, {"heads": [], "round": 0,
                               "directive_heads": [], "resolver": False})
    if head and head not in r["heads"]:
        r["heads"] = (r["heads"] + [head])[-6:]
        r["round"] = len(r["heads"])
    # 熔断→resolver 接力工单（一次性）
    if not r["resolver"] and r["round"] >= 2:
        try:
            comments = json.loads(_gh(["pr", "view", str(n), "-R", repo,
                                       "--json", "comments"]))["comments"]
        except Exception:
            comments = []
        if _has_break_marker(comments, self_login="1339190177"):
            title = f"[conflict-solver] PR#{n} 冲突解决接力工单"
            _gh(["issue", "create", "-R", repo, "--title", title, "--body",
                 f"@{agent} 冲突熔断自动接力（前 worker 两轮未解）：\n"
                 f"- PR#{n} 与 dev 冲突，前 worker 已声明熔断（评论链可考古归因）\n"
                 "- 解法同冲突自解协议第 1-4 步；此单合入后原 PR 复审自动合并\n"
                 "- 全新视角优先：先读双方清单与验收判据再动手"])
            r["resolver"] = True
            _journal({"repo": repo, "pr": n, "mode": "machine",
                      "decision": "conflict_resolver", "tier": "conflict"})
            return "resolver"
    # 单槽：目标=该仓当前冲突 PR 中最小号
    try:
        open_prs = json.loads(_gh(["pr", "list", "-R", repo,
            "--state", "open", "--json", "number,mergeable"]))
        conflicting = sorted(p["number"] for p in open_prs
                             if p.get("mergeable") == "CONFLICTING")
    except Exception:
        conflicting = [n]
    if not conflicting:
        return None
    target = conflicting[0]
    if n != target:
        _journal({"repo": repo, "pr": n, "mode": "machine",
                  "decision": "conflict_wait", "tier": "conflict",
                  "fail_reason": f"等槽（目标 PR#{target}）"})
        return "wait"
    # 目标：每轮（新 head）发一次解法指令；第 2 轮起附熔断提示
    if head and head not in r["directive_heads"]:
        d = conflict_directive(agent)
        body = d if r["round"] < 2 else (d + "\n（已两轮未解——若仍无法调和意图，请评论「冲突熔断」交棒）")
        _gh(["pr", "comment", str(n), "-R", repo, "--body", body])
        r["directive_heads"] = (r["directive_heads"] + [head])[-6:]
        _journal({"repo": repo, "pr": n, "mode": "machine",
                  "decision": "conflict_dispatch", "tier": "conflict",
                  "fail_reason": f"round {r['round']}"})
        return "dispatch"
    return "hold"


def escalation_hint(fail_reason):
    """判据类升级的教学行（run60 批182，昨夜 PR#20-26 标本：worker 收升级评论后
    不知格式反复重推 15 次零合并）。措辞=须补可核证据（顾问护栏：不是"写这些即过"）。
    批214：含糊分支附转写配方——首过率三连降（42→29→13%）9/11 是自然语言判据
    （「当 X 完成时，脚本…」），旧教学只教"怎么验"不教"怎么改写"，worker 无从下笔。
    非判据类返回空串——评论与旧文等价，教学只进判据信道。"""
    if "判据" not in (fail_reason or ""):
        return ""
    hint = ("\n\n判据行过关须补可核证据（三式任一）：行尾 ✅（已验/通过）｜"
            "行含 N/N 计数且与 hermetic 实跑一致｜行含「全绿/全过」。"
            "禁贴骨架模板原文（占位符未填必拦）——照抄验收节模板行不算判据。")
    if "含糊" in (fail_reason or ""):
        hint += ("\n\n转写配方（把你的自然语言判据改写成可机械化形态）：\n"
                 "「当 X 完成时，脚本 Y…」→「When X，Then <实跑命令> 输出 "
                 "<N passed/exit 0>（验：REGRESS-工单号 N/N）」\n"
                 "三件齐：可跑命令+可数结果+工单号对账。例：「当 fleet 修复完成时，"
                 "脚本通过」→「When fleet 修复合入，Then python tests/test_fleet.py "
                 "输出 12 passed（验：REGRESS-261109-xxxx 12/12）」。\n"
                 "真感官类判据不可机械化→标注 human_check 走人类终验（勿造假配方）；"
                 "实例仅供参考，禁止照抄当测试。")
    return hint


def _pr_manifest_scope(meta, names, head_ref=""):
    """批212：判据核对范围锁 PR 本体——清单名只取两源：
    ①PR diff 内改动的 .regress/manifests/*.md（本单清单随单提交）；
    ②PR 标题/分支名/正文所含工单号能匹配的 manifest 文件名。
    全仓其余 manifest（他单/历史单）一律不采——误引串扰根治
    （tongtu #146：PR#141/#143/#145 连续误引 559dbeec 判据三例）。"""
    picked = set()
    for f in meta.get("files") or []:
        p = f.get("path", "")
        if p.startswith(".regress/manifests/") and p.endswith(".md"):
            picked.add(os.path.basename(p))
    hay = " ".join(filter(None, [
        meta.get("title") or "", head_ref or "", meta.get("body") or ""]))
    ids = set(REGRESS_ID_RE.findall(hay))
    for name in names:
        if any(i in name for i in ids):
            picked.add(name)
    return picked


def _collect_criteria(mdir, picked):
    """批212：按 scope 采清单——planned 文件集与 EARS 判据行同源同锁；
    判据行附出处（.regress/manifests/<名>:<行号>）供升级评论自证。"""
    manifest_files, ears = [], []
    for name in sorted(os.listdir(mdir)):
        if name not in picked or not name.endswith(".md"):
            continue
        mp = os.path.join(mdir, name)
        data = parse_frontmatter(mp) or {}
        manifest_files += [c.get("file") for c in
                           (data.get("planned_changes") or [])
                           if isinstance(c, dict) and c.get("file")]
        _, rows = ears_extract(mp)
        if rows:
            lines = open(mp, encoding="utf-8").read().splitlines()
            src = f".regress/manifests/{name}"
            for row in rows:
                ln = next((i + 1 for i, ln_txt in enumerate(lines)
                           if row.strip() and row.strip() in ln_txt.strip()), 0)
                ears.append((row, f"{src}:{ln}"))
    return manifest_files, ears


def check_criteria(ears_rows, passed, total, tests_ok=True):
    """⑤机械化：验收行逐条找机器可对账的证据；含糊/矛盾 → 升级。

    口径（保守）：行含已验标记（门禁盖过）=过；行含 N/N 且与 hermetic
    结果一致=过、不一致=矛盾；行含"全绿/全过"且测试全过=过（计数不可得
    的 test_cmd 模式下以 exit code 为准）；其余=含糊。

    批212：ears_rows 元素兼容 str 与 (row, 出处) 二元组——判据类失败
    消息附「出处 文件:行号」（升级评论自证来源，误引一眼可辨）。
    """
    for item in ears_rows:
        row, src = item if isinstance(item, tuple) else (item, "")
        cite = f" 出处 {src}" if src else ""
        if any(m in row for m in VERIFIED_MARKS):
            continue
        m = RATIO_RE.search(row)
        if m and passed >= 0:
            a, b = int(m.group(1)), int(m.group(2))
            if not (a == b == passed == total):
                return False, f"判据矛盾: 「{row[:40]}」 vs hermetic {passed}/{total}{cite}"
            continue
        if ("全绿" in row or "全过" in row) and tests_ok and (passed < 0 or (passed == total and total > 0)):
            continue
        return False, f"判据含糊(不可机械化): 「{row[:40]}」{cite}"
    return True, ""


def review_pr(repo, number, cfg, json_out=False):
    """单 PR 机械评审：返回 (rows, verdict_dict)。抛错=自崩（exit 2）。"""
    # 批214附（公网告警 11:15）：headRefKey 非 gh 合法字段（批212 引入，PR#159 实弹
    # 自崩标本）→ 改 headRefOid（合法且语义同源——commit 钉）；消费侧 get 同步改名
    meta = json.loads(_gh(["pr", "view", str(number), "-R", repo, "--json",
                           "title,body,files,additions,deletions,reviews,mergeable,author,headRefOid"]))
    tmp = tempfile.mkdtemp(prefix="prgate-")
    try:
        # hermetic 检出（协议第 4 步命令序列；--reference 本地种子=75MB 级仓秒级克隆）
        wt = os.path.join(tmp, "repo")
        seed = os.path.expanduser(f"~/src/{repo.split('/')[-1]}")
        ref = ["--reference", seed] if os.path.isdir(seed) else []
        subprocess.run(["git", "clone", "--quiet", *ref,
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
        manifest_files, ears = [], []
        if os.path.isdir(mdir):
            # 批212：范围锁 PR 本体——本 PR diff 涉及 manifest ∪ 标题/分支/
            # 正文所含工单号匹配的 manifest；全仓扫描结果按文件名含本单号
            # 过滤（他单清单的判据/planned 不再串入 ①⑤ 对账）
            names = [n for n in os.listdir(mdir) if n.endswith(".md")]
            picked = _pr_manifest_scope(meta, names, head_ref=meta.get("headRefOid", ""))
            manifest_files, ears = _collect_criteria(mdir, picked)
        ears_rows = [r for r, _ in ears]
        # hermetic 测试（④：test-only PR 走 test_cmd_fast 快道；否则 test_cmd；
        # 均未声明走 test_runner CLI=与提交门禁同一事实源）
        test_files = [f["path"] for f in meta["files"]
                      if not f["path"].startswith(".regress/")]
        is_testonly = bool(test_files) and all(
            ("test" in os.path.basename(f) or f.startswith(("tests/", "__tests__/")))
            for f in test_files)
        fast_cmd = pr_review_cfg.get("test_cmd_fast", "")
        test_cmd = fast_cmd if (is_testonly and fast_cmd) else pr_review_cfg.get("test_cmd", "")
        if test_cmd:
            # systemd 服务环境 PATH 极简（无 nvm/corepack/pnpm）——富集常用 bin 路径
            env = dict(os.environ)
            extra = [os.path.expanduser(p) for p in (
                "~/.local/bin", "/usr/local/bin")]
            extra += sorted(__import__("glob").glob(
                os.path.expanduser("~/.nvm/versions/node/*/bin"))) or []
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
            # 批189：ffmpeg-static postinstall 每轮全新 clone 重下 80MB 且 GitHub
            # CDN 爬行（2026-11-03 实证悬挂 15 分钟×2；package.json 权威 env 名=
            # FFMPEG_BIN 跳过下载/BINARIES_URL 镜像会回源）——指宿主二进制直跳
            import shutil as _sh
            if _sh.which("ffmpeg"):
                env.setdefault("FFMPEG_BIN", _sh.which("ffmpeg"))
            tr = subprocess.run(test_cmd, shell=True, cwd=wt, env=env,
                                capture_output=True, text=True, timeout=3600)
            try:
                tres = json.loads(tr.stdout or "{}")
            except json.JSONDecodeError:
                tres = {}
            passed = tres.get("passed", -1)
            total = tres.get("total", -1)
            tests_ok = tr.returncode == 0
            _tail = (tr.stdout or tr.stderr or "").strip()
            hermetic_note = _tail.splitlines()[-1][:120] if _tail else ""
        else:
            tr = subprocess.run([sys.executable,
                                 os.path.join(GUARD_ROOT, "lib", "test_runner.py"), wt],
                                capture_output=True, text=True, timeout=1800)
            try:
                tres = json.loads(tr.stdout or "{}")
            except json.JSONDecodeError:
                tres = {}
            passed, total = tres.get("passed", -1), tres.get("total", -1)
            tests_ok = tr.returncode == 0 and tres.get("status") == "pass"
            hermetic_note = ""

        # 计数不可得（test_cmd 输出尾行无 passed/total JSON，如 tongtu pnpm 链）时
        # 以 exit code 口径诚实标注 "exit0"，不再显示误导性的 -1/-1
        count_txt = fmt_hermetic(passed, total)

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
        rows.append((tests_ok, f"④hermetic {count_txt}" + (f" | {hermetic_note}" if hermetic_note else "")))
        fail = fail or ("" if tests_ok else f"hermetic {count_txt}")
        ok, why = (check_criteria(ears, passed, total, tests_ok)
                   if ears_rows else (False, "PR 内无清单验收行"))
        rows.append((ok, f"⑤判据机械化 {why}"))
        fail = fail or ("" if ok else why)
        bad_reviews = [r["state"] for r in meta.get("reviews", [])
                       if r.get("state") == "CHANGES_REQUESTED"]
        ok6, why6, is_conflict = _judge_human_signal(bad_reviews, meta.get("mergeable"))
        rows.append((ok6, f"⑥人类信号 reviews={bad_reviews or '无'} mergeable={meta.get('mergeable')}"))
        fail = fail or ("" if ok6 else why6)
        verdict = {
            "repo": repo, "pr": number, "author": meta["author"]["login"],
            "size": size, "passed": passed, "total": total,
            "count_txt": count_txt, "conflict": is_conflict,
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
        if tmp.startswith(os.path.join(tempfile.gettempdir(), "prgate-")):
            shutil.rmtree(tmp, ignore_errors=True)  # 只清自建前缀目录


def _close_linked_issues(repo, number, body):
    for m in set(re.findall(r"[Ii]ssue\s*#(\d+)", body or "") +
                 re.findall(r"/issues/(\d+)", body or "")):
        _gh(["issue", "close", m, "-R", repo, "--comment",
             f"PR#{number} 已通过机械评审自动合并——工单闭环。"])


def _review_state():
    """sweep 去重态：PR head sha 不变且已有终态判定则跳过重评（重仓防 3 分钟全量重跑）。"""
    p = os.path.expanduser("~/.zcode/workspace/default/.regress/pr-gate-state.json")
    try:
        return json.load(open(p, encoding="utf-8")), p
    except Exception:
        return {}, p


def _comment_best_effort(repo, number, body):
    """批218（FP1）：置评 best-effort——置评失败不让 sweep 崩（journal 已落账
    兜底，WeCom 摘要仍带"自崩"）。PR#159 教训的信号面主信道，主信道坏时
    其余信道照常。"""
    try:
        _gh(["pr", "comment", str(number), "-R", repo, "--body", body])
    except Exception:
        pass


def _save_review(state, path, repo, number, head, verdict, streak=None,
                 streak_key="unknown_streak", fail_reason=None):
    """批207：streak=同 head 的 UNKNOWN 连续轮数（defer 态记账；其余 verdict
    整记录覆写即自然清零）。批218：streak_key 参数化——crash 态同机制记账
    （crash_streak），复评成功整记录覆写即自愈清零。批220（Ref 90d0f8d）：
    fail_reason 随 escalate 态入账——评论幂等闸的比对基。"""
    rec = {"head": head, "verdict": verdict,
           "at": __import__("time").strftime("%F %T")}
    if streak is not None:
        rec[streak_key] = streak
    if fail_reason is not None:
        rec["fail_reason"] = fail_reason
    state[f"{repo}#{number}"] = rec
    try:
        json.dump(state, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def sweep():
    """扫描注册表内各仓的开放 agent PR，按 pr_review.mode 分档执行。"""
    with open(REGISTRY, encoding="utf-8") as f:
        repos = json.load(f)
    merged, escalated, unknown_deferred = [], [], []
    state, state_path = _review_state()
    for entry in repos:
        repo, agent = entry["repo"], entry["agent_login"]
        try:
            # 批196：headRefOid/mergeable 随 list 一次带回——settled PR
            # 零额外调用（原每 PR 至多两次 pr view，90s 轮询下是无谓 gh 脉冲源）
            open_prs = json.loads(_gh(["pr", "list", "-R", repo,
                "--author", agent, "--state", "open",
                "--json", "number,headRefOid,mergeable"]))
        except Exception as e:
            escalated.append(f"{repo}: 枚举失败 {e}")
            continue
        for pr in open_prs:
            n = pr["number"]
            # 去重：同 head sha 且已有终态判定（escalate 类滞留 PR 不重评；新推送=新 sha 自动复评）
            head = pr.get("headRefOid") or ""
            prev = state.get(f"{repo}#{n}") or {}
            mb = pr.get("mergeable") or "MERGEABLE"  # 批196 字段缺失乐观缺省
            # 批184 例外：CONFLICTING 随 dev 移动可自愈必须重估；
            # 批207：UNKNOWN 且已 escalate——GitHub 侧卡死等人类，封口不再重评
            # （原「非 MERGEABLE 一律重评」使 UNKNOWN 每轮重跑 hermetic+重发指令）
            # 批218：recommend（human-merge 建议合）入封口集——原每轮重评+重发
            # "建议合并"评论（90s 刷评潜伏面）；新推送=新 head 自动复评不变
            if prev.get("head") == head and prev.get("verdict") in (
                    "merged", "escalate", "recommend"):
                if mb in ("MERGEABLE", "UNKNOWN"):
                    continue
            # 批207：UNKNOWN 三态化——瞬态不判冲突/不发指令/不跑 hermetic；
            # 同 head 连续 UNKNOWN_MAX_STREAK 轮仍未知才升级（明示非冲突）
            if mb == "UNKNOWN":
                streak = (prev.get("unknown_streak", 0) + 1
                          if prev.get("head") == head else 1)
                if streak < UNKNOWN_MAX_STREAK:
                    _save_review(state, state_path, repo, n, head,
                                 "defer-unknown", streak)
                    unknown_deferred.append(f"{repo}#{n}({streak})")
                    continue
            try:
                v = review_pr(repo, n, {})
            except Exception as e:
                # 批218：自崩≠终态裁定——评审器侧异常应可重试可自愈，与"PR 真
                # 有问题"的 escalate 分家。三缺口补齐：置评（PR 侧 actor 可见）
                # +journal 落账（考古断链根治）+crash 态不封口（根因修复后下轮
                # 自动复评）。有界：连续 CRASH_MAX_STREAK 仍崩才封口 escalate
                # 终评（防全量崩无限重试）。置评节律=首轮+封口轮，中继轮静默。
                streak = (prev.get("crash_streak", 0) + 1
                          if prev.get("head") == head else 1)
                err = f"自崩 {str(e)[:100]}"
                sealed = streak >= CRASH_MAX_STREAK
                if streak == 1 or sealed:
                    _comment_best_effort(repo, n, (
                        f"机械评审自崩：{err}\n"
                        + ("——评审器自身异常，非本 PR 问题；根因修复后下轮自动复评"
                           "（无需重推）。" if not sealed else
                           f"——连续 {streak} 轮自崩，封口留人类/LLM 裁决"
                           "（评审器侧待修，与本 PR 内容无关）。")))
                _journal({"repo": repo, "pr": n, "mode": "machine",
                          "decision": "escalate" if sealed else "crash",
                          "tier": "sweep",
                          "fail_reason": f"{err}（第 {streak} 轮）"})
                if sealed:
                    _save_review(state, state_path, repo, n, head, "escalate")
                else:
                    _save_review(state, state_path, repo, n, head, "crash",
                                 streak=streak, streak_key="crash_streak")
                escalated.append(f"{repo}#{n}: {err}")
                continue
            mode = v["mode"]  # 权威源=仓内 .regress（hermetic clone 读得）
            fields = {"repo": repo, "pr": n, "mode": "machine",
                      "decision": "merged" if v["mechanical_pass"] and mode == "auto-merge" else
                                  ("recommend" if v["mechanical_pass"] else "escalate"),
                      "fail_reason": v["fail_reason"], "tier": mode}
            _journal(fields)
            if not v["mechanical_pass"]:
                if v.get("conflict") and mode == "auto-merge":
                    # 批184：冲突独走（人类零参与）——单槽串行+解法指令+熔断接力
                    _conflict_engine(repo, n, state, state_path, head, agent)
                    _save_review(state, state_path, repo, n, head, "escalate")
                    continue
                escalated.append(f"{repo}#{n}: {v['fail_reason']}")
                # 批220（Ref 90d0f8d 批211 复活）：escalate 评论幂等闸——
                # CONFLICTING 态滞留 PR 每轮重估是批184 设计（dev 移动可自愈），
                # 但同 head 同因重评每轮重发同文评论=噪音风暴（PR94 标本：head
                # 未变 1 commit 收 14 条同文评论，~30min 节拍=mergeable 抖动穿透
                # 批207 UNKNOWN 封口）。首报/变化才发；同因重评静默——可见性由
                # pr_review 承担、沉底由哨兵日报承担（顾问三轮裁决完全静默）。
                same_as_prev = (prev.get("head") == head
                                and prev.get("verdict") == "escalate"
                                and prev.get("fail_reason") == v["fail_reason"])
                _save_review(state, state_path, repo, n, head, "escalate",
                             fail_reason=v["fail_reason"])
                if same_as_prev:
                    escalated.append(f"{repo}#{n}: 同因重评静默（评论幂等闸）")
                else:
                    _gh(["pr", "comment", str(n), "-R", repo, "--body",
                         f"机械评审升级：{v['fail_reason']}（判据逐项见 journal pr_review）——留人类/LLM 裁决。"
                         + escalation_hint(v["fail_reason"])])
                continue
            if mode == "auto-merge":
                count = v.get("count_txt") or f"{v['passed']}/{v['total']}"
                _gh(["pr", "merge", str(n), "-R", repo, "--merge", "--subject",
                     f"auto-review: passed (机械判据全绿·hermetic {count})"])
                merged.append(f"{repo}#{n}（{v.get('count_txt', v['passed'])}）")
                _save_review(state, state_path, repo, n, head, "merged")
                # 批184：冲突轮次态自愈清零（合并=冲突终局）
                state.get("conflict_rounds", {}).pop(f"{repo}#{n}", None)
                # 关联 issue 闭环：body 里的 Issue #N
                meta_body = json.loads(_gh(["pr", "view", str(n), "-R", repo,
                    "--json", "body"]))["body"]
                _close_linked_issues(repo, n, meta_body)
            elif mode == "human-merge":
                _gh(["pr", "comment", str(n), "-R", repo, "--body",
                     "机械评审全过——建议合并（human-merge 档，等人类执行）。"])
                merged.append(f"{repo}#{n} 建议合（human-merge 档）")
                _save_review(state, state_path, repo, n, head, "recommend")
            # review-only 档：仅落账（不记终态——保持每轮可见性由 journal 承担）
    # ⑦ 拒绝面：superagent 24h 内 ignore 决定未处置 → 提行
    ignored = []
    if os.path.exists(SUPERAGENT_DB):
        try:
            r = subprocess.run(["sqlite3", SUPERAGENT_DB,
                "select at || '|' || value from decision "
                "where at >= datetime('now','-1 day')"],
                capture_output=True, text=True, timeout=15)
            # kind=ignore 精确判定：行内过滤（见下），不在此预筛
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
          + (f", {len(unknown_deferred)} unknown-deferred"
             + (f" [{'; '.join(unknown_deferred)}]" if len(unknown_deferred) <= 4 else "")
             if unknown_deferred else "")
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
