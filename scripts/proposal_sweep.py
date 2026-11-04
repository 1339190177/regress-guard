#!/usr/bin/env python3
"""proposal_sweep.py —— agent 提案轮次（批185，P1：翻转需求方向）。

pero 哲学（README:53）：Agents propose work; people approve consequential
actions。扫描仓内规划文档「差距总表」的本版项（✅/部分）→ 对照已有
issue/PR 标题去重 → 未覆盖项起草提案 issue——pero 式标题（scope 前缀+
优先级+执行序+人日），正文=文档行原文+机器判据骨架——**不带 @ 提及**
（Router 只观察不派工）→ 人类批准=评论「@+agent 登录名 开工」→
进入正常工单流。从此人类只裁决不执笔（昨夜连写七单瓶颈的本体解法）。

提案质量边界（诚实宣称）：v1 为机械提取，判据骨架的通用行已填、特性行
留给批准前人工补或 worker 开工转写（AGENTS 第 11 条）；去重靠标题关键词
匹配，误漏/误提由人类批准环节过滤（proposal 的设计本意）。

退出码：0=无新提案；1=有新提案（已建）；2=自崩。
状态：~/.zcode/workspace/default/.regress/proposal-state.json
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

GUARD_ROOT = os.path.expanduser("~/.zcode/workspace/default/regress-guard")
WORKSPACE = os.path.expanduser("~/.zcode/workspace/default")
STATE = os.path.join(WORKSPACE, ".regress", "proposal-state.json")
REPO = "1339190177/tongtu-anquan-ai-workspace"


def _agent_login():
    """批准话术的 @ 对象取自评审注册表（权威源；发版卫生禁用户名字面量）。"""
    try:
        reg = json.load(open(os.path.join(
            WORKSPACE, ".regress", "pr-review-repos.json"), encoding="utf-8"))
        for e in reg:
            if e.get("repo") == REPO:
                return e["agent_login"]
    except Exception:
        pass
    return "the-agent"
SEED = os.path.expanduser("~/src/tongtu-anquan-ai-workspace")
DOC = "device-access-platform/docs/项目管理/设备接入端v0.1工作计划.md"
# 阶段一/二窗口内=本版死线项（P0）；三阶段外/12月+ 不提（表内 ❌ 12月+ 已滤）
P0_SEQ = {1, 2, 5, 6, 14, 15, 19, 28, 29}


def _run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _gh(args, timeout=60):
    r = _run(["gh", *args], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"gh {args[:2]}… 失败: {r.stderr.strip()[:120]}")
    return r.stdout


def _doc_text():
    _run(["git", "-C", SEED, "fetch", "-q", "origin", "dev"], timeout=120)
    r = _run(["git", "-C", SEED, "show", f"origin/dev:{DOC}"])
    if r.returncode != 0:
        raise RuntimeError(f"规划文档读取失败: {r.stderr[:100]}")
    return r.stdout


def parse_gap_table(md):
    """差距总表 → [(原型页, B项, 现状, 差距, 本版)]。只认表格行（| 分隔五列+）。"""
    rows = []
    for line in md.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("原型页",) or set(cells[0]) <= set("-— "):
            continue
        rows.append(tuple(cells[:5]))
    return rows


def is_proposable(benban):
    """本版列含 ✅ 或 部分（本版要做的）；❌ 12月+ 不提。"""
    return ("✅" in benban or "部分" in benban) and "12 月+" not in benban


def seq_of(benban):
    m = re.search(r"执行序\s*(\d+)", benban)
    return int(m.group(1)) if m else None


def kw_of(page, bitem):
    """覆盖匹配关键词：原型页首词（英文优先，剥 markdown 强调符）+ B 项码。"""
    first = re.split(r"[\s/（(]", page.strip())[0] if page.strip() else ""
    first = first.strip("*_`")
    return [k for k in (first, bitem.split("/")[0] if bitem else "") if k]


def code_evidence(row):
    """代码证据核对（批186 修补：首批 5 案全误标本）——差距列中文关键词
    （≥3 字连续段）在 origin/dev 里 git grep，命中即「疑似已实现」不建案。
    文档现状列会过时，代码不会说谎；宁可漏提（下轮文档刷新后再提），
    不可误提（浪费人类裁决注意力）。"""
    gap = row[3]
    kws = []
    for kw in re.findall(r"[\u4e00-\u9fff]{3,8}", gap):
        if kw not in kws and not any(kw in k or k in kw for k in kws):
            kws.append(kw)
    hits = []
    for kw in kws[:4]:
        r = _run(["git", "-C", SEED, "grep", "-l", kw, "origin/dev", "--",
                  "device-access-platform"], timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            hits.append((kw, r.stdout.strip().splitlines()[0][:80]))
    return hits


def already_covered(titles, row):
    page, bitem = row[0], row[1]
    for kw in kw_of(page, bitem):
        for t in titles:
            if kw.lower() in t.lower():
                return kw
    return None


def draft_issue(row):
    page, bitem, now_, gap, benban = row
    seq = seq_of(benban)
    prio = "P0" if seq in P0_SEQ else "P1"
    head = (re.split(r"[\s/（(]", page.strip())[0] or "").strip("*_`")
    if not head:  # 无英文首词（如加粗中文行）——剥装饰后取前五字
        head = re.sub(r"[*_`（）：:]", "", page)[:5] or "misc"
    gap_txt = gap.strip()
    if len(gap_txt) > 40:
        gap_txt = gap_txt[:40].rstrip("（(+/；;，,") + "…"
    title = f"[proposal][feat][dap·{head}][{prio}] {gap_txt}（{bitem.strip()}）"
    body = (
        f"## 背景（提取自《设备接入端 v0.1 工作计划》差距总表）\n\n"
        f"| 原型页 | B 项 | 现状 | 差距 | 本版 |\n|---|---|---|---|---|\n"
        f"| {page} | {bitem} | {now_} | {gap} | {benban} |\n\n"
        "## 验收标准（机器可对账·批准前请补齐特性行）\n\n"
        "- 相关测试套件全绿 N/N（验：pnpm --filter 相关包 test）✅\n"
        "- typecheck 零错误（验：pnpm --filter 相关包 typecheck）✅\n"
        "- （特性判据行——行尾 ✅ 或 N/N 或「全绿」，模板见 .github/ISSUE_TEMPLATE）\n\n"
        f"**提案（proposal）**：本单由 agent 起草，未派工。批准=评论「@{_agent_login()} 开工」；"
        "否决=直接关闭。开工后按 AGENTS 机器通道执行（含第 11 条判据转写、第 12 条 fitness 记录）。")
    return title, body


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"proposed": {}}


def main():
    dry = "--dry-run" in sys.argv
    st = load_state()
    md = _doc_text()
    rows = [r for r in parse_gap_table(md) if is_proposable(r[4])]
    titles = []
    try:
        titles += [d["title"] for d in json.loads(_gh(["issue", "list", "-R", REPO,
            "--state", "all", "--limit", "300", "--json", "title"]))]
        titles += [d["title"] for d in json.loads(_gh(["pr", "list", "-R", REPO,
            "--state", "all", "--limit", "200", "--json", "title"]))]
    except Exception as e:
        print(f"标题面读取失败（不建单）: {e}", file=sys.stderr)
        return 2
    created = []
    for row in rows:
        key = hashlib.md5((row[0] + row[1]).encode()).hexdigest()[:12]
        if key in st["proposed"]:
            continue
        hit = already_covered(titles, row)
        if hit:
            st["proposed"][key] = {"title": row[0], "at": "", "covered_by": hit}
            continue
        ev = code_evidence(row)
        if ev:
            st["proposed"][key] = {"title": row[0], "at": "",
                                   "suspect_done": ev[:2],
                                   "note": "文档现状列疑似过时——请人刷新"}
            print(f"[跳过·疑似已实现] {row[0]}：{ev[0][0]} → {ev[0][1]}")
            continue
        title, body = draft_issue(row)
        if dry:
            print(f"[dry] {title}")
            created.append(title)
            continue
        _gh(["issue", "create", "-R", REPO, "--title", title, "--body", body])
        st["proposed"][key] = {"title": title,
                               "at": datetime.datetime.now().isoformat(timespec="seconds")}
        created.append(title)
    if not dry:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if created:
            try:
                _run([sys.executable, os.path.join(GUARD_ROOT, "lib", "notify.py"),
                      ".", "chat", "--title", f"提案轮次：{len(created)} 项待裁决",
                      "--body", "\n".join(created[:6]) +
                      f"\n批准=对应 issue 评论 @{_agent_login()} 开工；否决=关闭。"],
                     cwd=WORKSPACE, timeout=30)
            except Exception:
                pass
    print(f"提案轮次：候选 {len(rows)}，新建 {len(created)}" +
          ("（dry-run）" if dry else ""))
    for t in created:
        print("  +", t)
    return 1 if created else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"proposal_sweep 自崩: {e}", file=sys.stderr)
        sys.exit(2)
