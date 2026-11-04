#!/usr/bin/env python3
"""effect_track.py —— 智能体效果跟踪轮次（批180，协议v1）。

跟踪 2026-11-02 批177-179 修缮在真实工单流上的效果：
  ① exit0 口径生效面（合并主题不再出现 hermetic -1/-1）
  ② 收尾清理纪律生效面（REGRESS-063：dap-tmp-* 命名+无遗留）
  ③ worktree 磁盘趋势（无自动修剪的增量观察位）
  ④ worker 摩擦趋势（REGRESS-062 取证范式：新会话失败数应降）
  ⑤ 首过率（判据格式纪律传播：escalate 占比应降）
纯机械层：唯一自动修复 = docker rm dap-tmp-*（前缀+超24h+无活跃
worktree 持有，三条件齐）；其余只 journal 落账 + WeCom 反馈，根治
判断归会话层（哨兵/交互会话读账本接力）。

退出码：0=全绿静默；1=有发现（已反馈）；2=自崩（timer 不重试）。
状态：~/.zcode/workspace/default/.regress/effect-track.json
"""
import datetime
import glob
import json
import os
import subprocess
import sys

GUARD_ROOT = os.path.expanduser("~/.zcode/workspace/default/regress-guard")
WORKSPACE = os.path.expanduser("~/.zcode/workspace/default")
STATE = os.path.join(WORKSPACE, ".regress", "effect-track.json")
WORK_DIR = os.path.expanduser("~/.dsh/state/superagent-tongtu/work")
# 会话目录名是「路径转义」形态（含用户名），发版卫生禁用户名字面量——后缀匹配等价覆盖
SESSION_GLOB = os.path.join(os.path.expanduser("~/.dsh/sessions"),
                            "*superagent-tongtu*")
TONGTU_REPO = "1339190177/tongtu-anquan-ai-workspace"
# 人类长期服务容器白名单（非 agent 遗留，永不触碰）
HUMAN_PREFIXES = ("media-stack-", "dap-wvp-direct", "dap-zlm-direct",
                  "dap-redis-direct", "ai-joint-debug", "device-access-platform-")
ACTIVE_STATUS = ("planning", "in-progress", "verifying", "blocked")


def _run(cmd, timeout=60, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **kw)


def _notify(title, body):
    try:
        _run(["python3", os.path.join(GUARD_ROOT, "lib", "notify.py"),
              ".", "chat", "--title", title, "--body", body],
             cwd=WORKSPACE, timeout=30)
    except Exception:
        pass


def _journal(note):
    try:
        _run(["python3", os.path.join(GUARD_ROOT, "lib", "journal.py"),
              WORKSPACE, "add", "ops_note",
              json.dumps({"note": note}, ensure_ascii=False)], timeout=15)
    except Exception:
        pass


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        return {"since": now, "disk_history": [], "run": 0}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def check_exit0(findings):
    """① 合并主题口径：最近 10 合并里 -1/-1（未生效标本）/ exit0（生效首例）。"""
    r = _run(["gh", "pr", "list", "-R", TONGTU_REPO, "--state", "merged",
              "--limit", "10", "--json", "number,title"])
    try:
        prs = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return
    bad = [p["number"] for p in prs if "hermetic -1/-1" in p.get("title", "")]
    good = [p["number"] for p in prs if "hermetic exit0" in p.get("title", "")]
    if bad:
        findings.append(f"①exit0 未生效标本 PR{bad}（合并主题仍 -1/-1——查 pr-gate.service 加载路径）")
    return len(good)


def _worktree_holds(token):
    """token 是否被活跃 worktree 持有（有活跃清单=在工，容器不许动）。"""
    for wt in glob.glob(os.path.join(WORK_DIR, f"*{token}*")):
        for mf in glob.glob(os.path.join(wt, ".regress", "manifests", "*.md")):
            try:
                head = open(mf, encoding="utf-8", errors="ignore").read(600)
            except OSError:
                continue
            if any(f"status: {s}" in head for s in ACTIVE_STATUS):
                return True
    return False


def check_containers(findings, fixed):
    """② 收尾清理：dap-tmp-* 三条件自动清；非规范遗留只报告。"""
    r = _run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.CreatedAt}}"])
    now = datetime.datetime.now()
    for line in (r.stdout or "").splitlines():
        name, _, created = line.partition("\t")
        if not name or name.startswith(HUMAN_PREFIXES):
            continue
        if name.startswith("dap-tmp-"):
            try:
                age = now - datetime.datetime.strptime(
                    created.strip()[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            token = name[len("dap-tmp-"):]
            if age > datetime.timedelta(hours=24) and not _worktree_holds(token):
                _run(["docker", "rm", "-f", name])
                fixed.append(f"docker rm {name}（dap-tmp 三条件齐）")
        elif name.startswith("dap-"):
            findings.append(f"②非规范容器遗留：{name}（{created.strip()[:16]}）——命名纪律未生效标本")


def gc_ended_worktrees(fixed):
    """终态工单 worktree 自动回收（run61 批183，人类授权根治）：>3 天 +
    无活跃清单 → ui-evidence 先存档 evidence/<树名>/ → 删树 → 种子仓 prune。
    夜树（PR 未决、assignment running）不动——_worktree_holds 拦住。"""
    import shutil
    cutoff = datetime.datetime.now().timestamp() - 3 * 86400
    for wt in glob.glob(os.path.join(WORK_DIR, "*")):
        if os.path.getmtime(wt) > cutoff:
            continue
        name = os.path.basename(wt)
        if _worktree_holds(name[-12:]):
            continue
        ev_src = os.path.join(wt, "ui-evidence")
        if os.path.isdir(ev_src):
            ev_dst = os.path.join(os.path.dirname(WORK_DIR), "evidence", name)
            os.makedirs(ev_dst, exist_ok=True)
            for f in glob.glob(os.path.join(ev_src, "*")):
                if os.path.isfile(f):
                    shutil.copy2(f, ev_dst)
        shutil.rmtree(wt, ignore_errors=True)
        fixed.append(f"worktree 回收 {name[:44]}（>3天终态，取证已存档）")
    seed = os.path.expanduser("~/src/tongtu-anquan-ai-workspace")
    if os.path.isdir(seed):
        subprocess.run(["git", "-C", seed, "worktree", "prune"],
                       capture_output=True, timeout=30)


def check_disk(findings, st):
    """③ worktree 磁盘趋势：总量入史；超阈值列可清清单（不自动删）。"""
    r = _run(["du", "-s", WORK_DIR], timeout=300)
    try:
        gb = int(r.stdout.split()[0]) / 1024 / 1024
    except (IndexError, ValueError):
        return
    today = datetime.date.today().isoformat()
    st["disk_history"] = [d for d in st["disk_history"] if d[0] != today]
    st["disk_history"].append((today, round(gb, 2)))
    st["disk_history"] = st["disk_history"][-60:]
    df = _run(["df", "-P", "/"])
    try:
        pct = int(df.stdout.splitlines()[1].split()[4].rstrip("%"))
    except (IndexError, ValueError):
        pct = 0
    if gb > 8 or pct > 85:
        stale = []
        cutoff = datetime.datetime.now().timestamp() - 3 * 86400
        for wt in glob.glob(os.path.join(WORK_DIR, "*")):
            if os.path.getmtime(wt) < cutoff and not _worktree_holds(
                    os.path.basename(wt)[-8:]):
                s = _run(["du", "-sh", wt], timeout=120)
                stale.append(f"{os.path.basename(wt)[:40]} {s.stdout.split()[0] if s.stdout else '?'}")
        findings.append(f"③磁盘面：worktree {gb:.1f}G/df {pct}% 超阈——可清候选（终态+>3天）：{stale or '无'}")


def check_friction(findings, since):
    """④ 新 worker 会话失败数（REGRESS-062 生效则应显著低于基线 22）。"""
    counts = []
    r = _run(["find", os.path.dirname(SESSION_GLOB), "-name",
              "session.v4.jsonl.zstd", "-newermt", since, "-path",
              "*/worker-*"])
    for path in (r.stdout or "").splitlines():
        p = _run(["zstd", "-dc", path], timeout=120)
        n = p.stdout.count('"isError":true')
        counts.append((os.path.basename(os.path.dirname(path))[:40], n))
    hot = [(s, n) for s, n in counts if n > 15]
    if hot:
        findings.append(f"④高摩擦会话（>{'15'}次，基线 22，062 范式未消化？）：{hot}")
    return counts


def check_firstpass(findings, since):
    """⑤ since 后 pr_review 新增行首过率（escalate 占比）。"""
    jf = os.path.join(WORKSPACE, ".regress", "journal", "events.jsonl")
    merged = escalated = 0
    conflicts = {}
    try:
        with open(jf, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "tongtu" not in line or '"pr_review"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("ts", "") > since:
                    if d.get("decision") == "merged":
                        merged += 1
                    elif d.get("decision") == "escalate":
                        escalated += 1
                    elif d.get("decision", "").startswith("conflict_"):
                        conflicts[d.get("decision")] = conflicts.get(d.get("decision"), 0) + 1
    except OSError:
        return
    return merged, escalated, conflicts


def main():
    st = load_state()
    since, findings, fixed = st["since"], [], []
    exit0_n = check_exit0(findings)
    check_containers(findings, fixed)
    gc_ended_worktrees(fixed)
    check_disk(findings, st)
    friction = check_friction(findings, since)
    fp = check_firstpass(findings, since)
    st["run"] += 1
    st["since"] = datetime.datetime.now().isoformat(timespec="seconds")

    summary = (f"效果跟踪 run{st['run']}：exit0生效{exit0_n or 0}例 | "
               f"容器{'清' + str(len(fixed)) if fixed else '无遗留'} | "
               f"磁盘 {st['disk_history'][-1][1] if st['disk_history'] else '?'}G | "
               f"新会话摩擦 {[(s[:18], n) for s, n in (friction or [])] or '无'} | "
               f"首过 {fp[0]}/{(fp[0] or 0) + (fp[1] or 0) if fp else '-'}"
               + (f" | 冲突指令{fp[2].get('conflict_dispatch', 0)}轮"
                  f"/等槽{fp[2].get('conflict_wait', 0)}"
                  f"/接力{fp[2].get('conflict_resolver', 0)}"
                  if fp and len(fp) > 2 and fp[2] else ""))
    _journal(summary + (f" | 已修:{fixed}" if fixed else "")
             + (f" | 发现:{len(findings)}项" if findings else " | 全绿"))
    if findings:
        _notify("效果跟踪轮次：有发现", "\n".join(findings + [f"已自动处理：{f}" for f in fixed]))
    save_state(st)
    print(summary)
    for x in findings:
        print("⚠", x)
    for x in fixed:
        print("✓", x)
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 自崩不重试：静默失败才是失察（timer 语义同 pr_gate）
        print(f"effect_track 自崩: {e}", file=sys.stderr)
        sys.exit(2)
