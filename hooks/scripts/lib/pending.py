#!/usr/bin/env python3
"""pending — 决策推送待决台账（v1.34 推送闭环）。

告警三段位的第二三段：可达（不沉默）已打赢，本层补「可度量+可校准」——
决策型推送（plan_approval/blocked/sensory/finish_open）送出即落一条待决
记录，人类的 outcome（useful/fp/ignored）回流后形成误报率——推送策略的
校准指标（防 alert fatigue：噪音推送腐蚀信任；「推送了但没用」与「该推没推」
是对称的病，都要可见）。

账本：~/.zcode/regress-pending.jsonl（机器级 append-only：add/resolve 各一行，
重放重建状态；RG_PENDING_LEDGER 可注入测试）。**台账记决策不记送达**——
决策点真实存在（计划在等批准、任务在受阻），推送失败也留账。

用法：
  pending.py add --project X --event blocked --title "🛑 受阻 REGRESS-x"
  pending.py list [--pending]
  pending.py resolve 3 useful      # useful=有用 fp=误报 ignored=忽略
  pending.py stats
"""
import argparse
import datetime
import json
import os
import sys

OUTCOMES = ("useful", "fp", "ignored")


def _path():
    return os.environ.get("RG_PENDING_LEDGER") or os.path.join(
        os.path.expanduser("~/.zcode"), "regress-pending.jsonl")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(rec):
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load():
    """重放账本：返回 (待决 dict, 已决 dict)。坏行跳过（台账是增强不是依赖）。"""
    adds, resolves = {}, {}
    try:
        with open(_path(), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "resolve_id" in e:
                    resolves[int(e["resolve_id"])] = e
                elif "id" in e:
                    adds[int(e["id"])] = e
    except (IOError, OSError):
        pass
    return adds, resolves


def add(project, event, title, ref=""):
    """落一条待决记录，返回分配的 id（notify 层预分配进推送正文〔待决#N〕）。

    ref（P0-3 回流接线，评审批次一）：结构化来源标识（清单 id）——
    plan_approve 批准/取消时按它精确 resolve，不靠标题猜。"""
    adds = _load()[0]
    nid = (max(adds) if adds else 0) + 1
    _append({"id": nid, "ts": _now(), "project": str(project)[:60],
             "event": str(event)[:20], "title": str(title)[:80],
             "ref": str(ref)[:60]})
    return nid


def resolve(pid, outcome):
    """回流人类裁决。outcome ∈ useful/fp/ignored；重复 resolve 以最后为准。"""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome 必须是 {'/'.join(OUTCOMES)}")
    _append({"resolve_id": int(pid), "ts": _now(), "outcome": outcome})
    return True


def resolve_by_ref(ref, outcome="useful"):
    """按结构化 ref 精确回流（P0-3）：resolve 该 ref 的全部未决记录，
    返回条数。兜底：无 ref 字段的旧记录按标题词边界唯一命中才处理
    （顾问补强：标题匹配只作唯一命中兜底，防误匹配）。"""
    import re as _re
    if not ref:
        return 0
    adds, resolves = _load()
    open_ids = [k for k in sorted(adds) if k not in resolves]
    hit_ref = [k for k in open_ids if adds[k].get("ref") == ref]
    legacy = [k for k in open_ids if not adds[k].get("ref")]
    pat = _re.compile(r"(?<![A-Za-z0-9-])" + _re.escape(ref) + r"(?![A-Za-z0-9-])")
    title_hits = [k for k in legacy if pat.search(adds[k].get("title", ""))]
    if len(title_hits) == 1:  # 唯一命中才兜底，多义不动
        hit_ref.append(title_hits[0])
    for k in hit_ref:
        _append({"resolve_id": int(k), "ts": _now(), "outcome": outcome,
                 "via": "auto(ref)"})
    return len(hit_ref)


def pending_records():
    adds, resolves = _load()
    return {k: v for k, v in adds.items() if k not in resolves}


def stats():
    adds, resolves = _load()
    open_p = [e for k, e in sorted(adds.items()) if k not in resolves]
    res = list(resolves.values())
    by = {o: sum(1 for e in res if e.get("outcome") == o) for o in OUTCOMES}
    oldest = ""
    if open_p:
        ages = [(datetime.datetime.now() - datetime.datetime.fromisoformat(
                    e["ts"])).total_seconds() / 86400 for e in open_p]
        oldest = f"{max(ages):.1f}天"
    decided = by["useful"] + by["fp"] + by["ignored"]
    return {"total": len(adds), "pending": len(open_p), "oldest_pending": oldest,
            "resolved": by, "fp_rate": (by["fp"] / decided) if decided else None,
            "open": open_p}


def main(argv=None):
    ap = argparse.ArgumentParser(description="决策推送待决台账")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="落待决（通常由 notify 层自动调用）")
    a.add_argument("--project", required=True)
    a.add_argument("--event", required=True)
    a.add_argument("--title", required=True)
    l = sub.add_parser("list", help="列出记录")
    l.add_argument("--pending", action="store_true", help="只看未决")
    r = sub.add_parser("resolve", help="回流人类裁决")
    r.add_argument("pid", type=int)
    r.add_argument("outcome", choices=OUTCOMES)
    sub.add_parser("stats", help="聚合：未决/裁决分布/误报率")
    args = ap.parse_args(argv)

    if args.cmd == "add":
        print(f"〔待决#{add(args.project, args.event, args.title)}〕")
    elif args.cmd == "list":
        recs = pending_records() if args.pending else _load()[0]
        for k in sorted(recs):
            e = recs[k]
            mark = "⏳" if "resolve_id" not in e else "✔"
            print(f"  #{e['id']} {mark} {e['ts'][:16]} [{e['event']}] "
                  f"{e['title'][:50]}")
        if not recs:
            print("  （空）")
    elif args.cmd == "resolve":
        resolve(args.pid, args.outcome)
        print(f"✔ #{args.pid} → {args.outcome}")
    else:
        s = stats()
        fp = "—" if s["fp_rate"] is None else f"{s['fp_rate']:.0%}"
        print(f"待决台账：共 {s['total']} 条｜未决 {s['pending']}"
              f"（最老 {s['oldest_pending'] or '—'}）｜"
              f"裁决 有用{s['resolved']['useful']}/误报{s['resolved']['fp']}/"
              f"忽略{s['resolved']['ignored']}｜误报率 {fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
