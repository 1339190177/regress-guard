#!/usr/bin/env python3
"""规律账本：沉淀 / 命中 / 衰变——带证据律的自改进的记账侧（v1.24）。

代谢链：地层是脂肪（原始病例），规律是肌肉（跨会话≥2 沉淀），skill 是骨骼
（命中≥3 经人批准固化）。账本只记账和提示，**永不自动删 AGENTS.md**（人类文件红线），
**固化建议只出卡片，批准权在人**（自动固化的错误经验会以技能的形式高速复发）。

用法：
  rules_ledger.py . record --sig "<失败签名>" --occurrences 5   # learn 沉淀/再检出时
  rules_ledger.py . health                                       # 衰变候选 + 固化候选
  rules_ledger.py . health --decay-days 180 --promote-hits 3

数据：.regress/rules-ledger.json（随 git 入库）。命中定义：learn 再检出同一签名
（真实"被咨询"无法自动探测，再检出是务实代理——诚实边界，记录在案）。
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journal import _find_project_dir  # noqa: E402  项目定位单一来源

DEFAULT_DECAY_DAYS = 180
PROMOTE_HITS = 3


def ledger_path(project_dir):
    return os.path.join(project_dir, ".regress", "rules-ledger.json")


def load(project_dir):
    try:
        with open(ledger_path(project_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, json.JSONDecodeError):
        return {}


def _save(project_dir, data):
    os.makedirs(os.path.dirname(ledger_path(project_dir)), exist_ok=True)
    with open(ledger_path(project_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def record(project_dir, sig, occurrences=0):
    """记账：首次沉淀 hits=1；同签名再检出 = 命中一次（hits+1，last_hit 刷新）。"""
    data = load(project_dir)
    key = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    today = date.today().isoformat()
    entry = data.get(key)
    if entry is None:
        data[key] = {"sig": sig, "captured_at": today, "last_hit": today,
                     "hits": 1, "occurrences": occurrences}
        action = "新沉淀"
    else:
        entry["sig"] = sig
        entry["hits"] = int(entry.get("hits", 1)) + 1
        entry["last_hit"] = today
        entry["occurrences"] = max(int(entry.get("occurrences", 0)), occurrences)
        action = f"命中（第 {entry['hits']} 次）"
    _save(project_dir, data)
    print(f"📒 {action}: 「{sig[:60]}」 occurrences={data[key]['occurrences']}")
    return data[key]


def _days_since(iso):
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except (ValueError, TypeError):
        return 0


def health(project_dir, decay_days=DEFAULT_DECAY_DAYS, promote_hits=PROMOTE_HITS):
    """规律健康：降级候选（>decay_days 零命中）+ 固化候选（hits≥promote_hits 且未腐化）。

    降级候选只提示人工修剪；固化候选只建议（人批准后经 skill-creator 固化为宿主 skill）。
    """
    data = load(project_dir)
    entries = sorted(data.values(), key=lambda e: -int(e.get("hits", 0)))
    stale = [e for e in entries if _days_since(e.get("last_hit", "")) > decay_days]
    stale_keys = {id(e) for e in stale}
    promotable = [e for e in entries
                  if id(e) not in stale_keys and int(e.get("hits", 0)) >= promote_hits]
    print(f"规律总数 {len(entries)}｜命中≥{promote_hits}（固化候选）{len(promotable)}｜"
          f">{decay_days}天零命中（降级候选）{len(stale)}")
    for e in promotable:
        print(f"  🦴 固化候选 hits={e['hits']} 「{e['sig'][:50]}」"
              f"（建议经人批准用 skill-creator 固化）")
    for e in stale:
        print(f"  🍂 降级候选 last_hit={e.get('last_hit')} 「{e['sig'][:50]}」"
              f"（提示人工修剪——本工具永不自动删）")
    if not entries:
        print("  （空账本——learn 沉淀规律时自动记账）")
    return {"total": len(entries), "promotable": promotable, "stale": stale}


def main(argv=None):
    ap = argparse.ArgumentParser(description="规律账本（代谢链记账侧）")
    ap.add_argument("project_dir", help="项目目录（. 通常够用）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="沉淀/再检出记账")
    r.add_argument("--sig", required=True, help="失败签名（规律的唯一键）")
    r.add_argument("--occurrences", type=int, default=0, help="累计出现次数（跨会话）")
    h = sub.add_parser("health", help="规律健康：降级候选 + 固化候选")
    h.add_argument("--decay-days", type=int, default=DEFAULT_DECAY_DAYS)
    h.add_argument("--promote-hits", type=int, default=PROMOTE_HITS)
    args = ap.parse_args(argv)
    project_dir = _find_project_dir(args.project_dir)
    if not project_dir:
        print("rules_ledger: 未找到 .regress/（项目未接入）", file=sys.stderr)
        return 1
    if args.cmd == "record":
        record(project_dir, args.sig, args.occurrences)
    else:
        import io as _io, contextlib as _cb
        with _cb.redirect_stdout(_io.StringIO()) as buf:
            health(project_dir, args.decay_days, args.promote_hits)
        out = buf.getvalue()
        print(out, end="")
        # 固化候选=需要人类批准的决策点（v1.33 企业级）：出现即推送，
        # 不再只躺在报表里等人跑 stats（conftest 以 RG_NO_NOTIFY 隔离测试）
        if "固化候选" in out and "固化候选）0" not in out and \
                not os.environ.get("RG_NO_NOTIFY"):
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from notify import notify as _notify
                n = out.count("🦴 固化候选")
                _notify(project_dir, "plan_approval",
                        f"🦴 固化候选 ×{n}",
                        "规律命中≥3 可固化为 skill——需要你批准（/regress:stats 查看详情）")
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
