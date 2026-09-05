#!/usr/bin/env python3
"""记录和查询 regress-guard 的运行历史（越用越聪明的数据层）。

历史格式：.regress/history.jsonl（每行一个 JSON 事件）

事件类型：
  - commit_blocked: commit 被阻断（原因：untracked_files / test_failed / no_test_runner）
  - commit_passed: commit 放行
  - bypass_used: bypass 模式使用
  - f3_discovered: track 发现计划外文件
  - test_failed: 测试失败（记录失败用例）

每条事件含：
  timestamp, event, manifest_id, session_id, details{}, files[]
"""
import os
import json
from datetime import datetime


def _current_session_id():
    """从环境变量推断当前 ZCode 会话 ID（证据链的过程锚点）。"""
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("ZCODE_SESSION_ID")
        or ""
    )


def record(regress_dir, event, manifest_id="", **details):
    """记录一条历史事件。

    证据链设计（借鉴 Harness Inspector 的 Intent→Process→Output）：
      manifest_id  = 意图锚点（哪个需求）
      session_id   = 过程锚点（哪次会话）
      commit_sha   = 产出锚点（哪个提交，commit 事件才有）

    Args:
        regress_dir: .regress/ 目录路径
        event: 事件类型（commit_blocked/commit_passed/bypass_used/f3_discovered/test_failed）
        manifest_id: 关联的清单 ID
        **details: 额外字段（如 files, reason, test_name, runner 等）
    """
    history_path = os.path.join(regress_dir, "history.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event,
        "manifest_id": manifest_id,
        # 证据链锚点：自动从环境推断（不依赖调用方传）
        "session_id": _current_session_id(),
    }
    entry.update(details)

    try:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 历史记录不阻断主流程

    # 遗忘机制（Ch9）：超过阈值时自动归档旧事件
    _maybe_archive(regress_dir, history_path)


def _maybe_archive(regress_dir, history_path, max_events=500):
    """history 超过 max_events 时，把旧事件移到 archive 文件。

    保留最近 max_events 条在 history.jsonl（热数据），
    旧的追加到 history-archive.jsonl（冷数据）。
    """
    try:
        with open(history_path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_events:
            return
        # 保留最近 max_events 条，旧的归档
        keep = lines[-max_events:]
        archive = lines[:-max_events]
        archive_path = os.path.join(regress_dir, "history-archive.jsonl")
        with open(archive_path, "a", encoding="utf-8") as f:
            f.writelines(archive)
        with open(history_path, "w", encoding="utf-8") as f:
            f.writelines(keep)
    except Exception:
        pass  # 归档失败不阻断


def load_history(regress_dir):
    """加载所有历史事件，返回 list[dict]。"""
    history_path = os.path.join(regress_dir, "history.jsonl")
    events = []
    if not os.path.exists(history_path):
        return events
    try:
        with open(history_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return events


def summarize(regress_dir):
    """分析历史，输出项目级洞察（供 /regress:learn 使用）。

    Returns:
        {
            "total_commits": int,
            "blocked_count": int,
            "bypass_count": int,
            "top_f3_files": [(file, count)],   # 最常被遗漏的文件
            "top_f3_patterns": [(pattern, count)],  # 最常被遗漏的目录/模式
            "frequent_failures": [(test_name, count)],  # 最常失败的测试
            "test_runner": str,  # 项目主要用的测试运行器
            "bypass_rate": float,  # bypass 使用率
            "block_rate": float,  # 阻断率
        }
    """
    events = load_history(regress_dir)

    total_commits = sum(1 for e in events if e.get("event") in ("commit_passed", "commit_blocked"))
    blocked = [e for e in events if e.get("event") == "commit_blocked"]
    bypassed = [e for e in events if e.get("event") == "bypass_used"]

    # F3 统计（含噪声过滤，借鉴 Harness Inspector：频次≠经验）
    # 同一 session 内的重复 F3 = 重试噪声（AI 反复尝试同一提交）
    # 跨 session 的重复 F3 = 稳定经验（真正值得沉淀的规律）
    f3_all = {}       # 原始计数
    f3_sessions = {}  # 每个 F3 文件出现在几个不同 session
    for e in events:
        if e.get("event") in ("f3_discovered", "commit_blocked") and e.get("untracked_files"):
            sid = e.get("session_id", "")
            for f in e["untracked_files"]:
                f3_all[f] = f3_all.get(f, 0) + 1
                f3_sessions.setdefault(f, set()).add(sid)

    # 只保留跨 session 出现 ≥2 次的（单 session 的高频是噪声）
    f3_files = {}
    f3_noise = {}
    for f, count in f3_all.items():
        session_count = len(f3_sessions.get(f, {""}))
        if session_count >= 2:
            f3_files[f] = session_count  # 用跨session次数作为稳定度
        else:
            f3_noise[f] = count  # 记为噪声（不进经验）

    # 按目录模式聚合
    f3_patterns = {}
    for fpath, count in f3_files.items():
        parts = fpath.split("/")
        if len(parts) > 1:
            pattern = parts[0] + "/**"
            f3_patterns[pattern] = f3_patterns.get(pattern, 0) + count

    # 测试失败统计
    test_failures = {}
    runners = {}
    for e in events:
        if e.get("event") == "test_failed" and e.get("test_name"):
            name = e["test_name"]
            test_failures[name] = test_failures.get(name, 0) + 1
        if e.get("runner"):
            runners[e["runner"]] = runners.get(e["runner"], 0) + 1

    top_f3 = sorted(f3_files.items(), key=lambda x: -x[1])[:10]
    top_patterns = sorted(f3_patterns.items(), key=lambda x: -x[1])[:5]
    top_failures = sorted(test_failures.items(), key=lambda x: -x[1])[:10]

    bypass_rate = (len(bypassed) / total_commits) if total_commits else 0
    block_rate = (len(blocked) / total_commits) if total_commits else 0
    main_runner = max(runners, key=runners.get) if runners else "unknown"

    # 债务追踪：bypass 后是否有对应的 verify（还债）
    # 简单逻辑：每次 bypass_used = 欠 1 笔债；之后每次 commit_passed（测试通过）= 还 1 笔
    debt = 0
    for e in events:
        if e.get("event") == "bypass_used":
            debt += 1
        elif e.get("event") == "commit_passed" and debt > 0:
            debt -= 1  # 测试通过的提交 = 还了一笔债

    # Ch24 生产指标：质量 / 安全 / 效率 / 成本
    passed_commits = sum(1 for e in events if e.get("event") == "commit_passed")
    quality_score = round(passed_commits / total_commits, 2) if total_commits else 0  # 质量：通过率
    f3_discoveries = sum(1 for e in events if e.get("event") == "commit_blocked"
                         and e.get("reason") == "untracked_files")
    f3_rate = round(f3_discoveries / total_commits, 2) if total_commits else 0  # F3 发现率

    # 效率：一次通过率
    test_interactions = sum(1 for e in events if e.get("event") in ("commit_passed", "test_failed"))
    efficiency = round(total_commits / max(test_interactions, 1), 2)

    # 覆盖率信号：历次放行提交的平均行覆盖率（有 jest coverage 时才有值）
    covs = [e.get("coverage_pct") for e in events
            if e.get("event") == "commit_passed" and e.get("coverage_pct") is not None]
    avg_coverage = round(sum(covs) / len(covs)) if covs else None

    # 门禁外提交：外部直提 + 历史回填（zcode-gate/zcode-bypass 是门禁放行的，不算）
    outside_commits = sum(1 for e in events
                          if e.get("event") == "commit_observed"
                          and e.get("source") in ("git-hook", "git-backfill"))

    # Ch21 阻断原因分布
    block_reasons = {}
    for e in blocked:
        r = e.get("reason", "unknown")
        block_reasons[r] = block_reasons.get(r, 0) + 1

    return {
        "total_commits": total_commits,
        "blocked_count": len(blocked),
        "bypass_count": len(bypassed),
        "top_f3_files": top_f3,
        "top_f3_patterns": top_patterns,
        "top_f3_noise": sorted(f3_noise.items(), key=lambda x: -x[1])[:5],  # 已过滤的噪声
        "avg_coverage_pct": avg_coverage,  # 平均行覆盖率（None=无覆盖率数据）
        "outside_gate_commits": outside_commits,  # 未走门禁的提交数（IDE/终端直提）
        "frequent_failures": top_failures,
        "test_runner": main_runner,
        "bypass_rate": round(bypass_rate, 2),
        "block_rate": round(block_rate, 2),
        "tech_debt": debt,
        # Ch24 四维指标
        "quality_score": quality_score,    # 质量：commit 通过率（越高越好）
        "f3_rate": f3_rate,                # 安全：计划外改动发现率
        "efficiency": efficiency,          # 效率：一次通过率
        "bypass_rate_pct": round(bypass_rate * 100),  # 安全：绕过百分比
        # Ch21 阻断原因分布
        "block_reasons": block_reasons,
    }


def build_trace(regress_dir):
    """构建交付链视图（借鉴 Harness Inspector 的 Intent→Process→Output）。

    把 history.jsonl 按 意图(manifest) → 过程(session) → 产出(commit) 组织。
    输出人类可读的文本交付链，供 /regress:trace 展示。
    """
    events = load_history(regress_dir)

    # 按 manifest 分组（意图锚点）
    by_manifest = {}
    for e in events:
        mid = e.get("manifest_id") or "(无清单)"
        by_manifest.setdefault(mid, []).append(e)

    lines = []
    for mid, evts in sorted(by_manifest.items()):
        evts.sort(key=lambda x: x.get("timestamp", ""))

        # 意图
        first = evts[0]
        lines.append(f"📌 {mid}  ({first.get('timestamp', '?')[:19]})")

        # git 观测的提交（非本清单会话产生）单列
        observed = [e for e in evts if e.get("event") == "commit_observed"]
        worked = [e for e in evts if e.get("event") != "commit_observed"]
        if observed:
            lines.append(f"   └─ 外部提交（IDE/终端，{len(observed)} 次，未走门禁测试）")
            for e in observed[:5]:
                ts = e.get("timestamp", "")[5:16]
                lines.append(f"       📤 {ts} {e.get('commit_sha','')} {e.get('subject','')[:40]}")
            if len(observed) > 5:
                lines.append(f"       … 共 {len(observed)} 次")

        # 按 session 分组（过程锚点）
        by_session = {}
        for e in worked:
            sid = e.get("session_id") or "?"
            by_session.setdefault(sid, []).append(e)

        for sid, sevts in by_session.items():
            sid_label = sid[:12] if sid and sid != "?" else "未知会话"
            lines.append(f"   └─ 会话 {sid_label}")

            for e in sevts:
                ev = e.get("event", "?")
                ts = e.get("timestamp", "")[11:19]
                icon = {"commit_passed": "✅", "commit_blocked": "🚫",
                        "bypass_used": "⚡", "test_failed": "❌",
                        "f3_discovered": "🔍", "error": "⚠️"}.get(ev, "·")
                detail = ""
                if ev == "commit_blocked":
                    reason = e.get("reason", "?")
                    files = e.get("untracked_files", [])
                    detail = f" {reason}" + (f" → {files[0]}" if files else "")
                elif ev == "commit_passed":
                    runner = e.get("runner", "?")
                    head = e.get("base_head", "")
                    detail = f" ({runner})" + (f" @{head}" if head else "")
                elif ev == "bypass_used":
                    detail = f" 到期 {e.get('expires', '?')[:19]}"
                lines.append(f"       {icon} {ts} {ev}{detail}")

        # 产出锚点
        passed = [e for e in evts if e.get("event") == "commit_passed"]
        if passed:
            lines.append(f"   📦 产出: {len(passed)} 次放行提交")
        lines.append("")

    return "\n".join(lines) if lines else "（暂无历史事件）"


if __name__ == "__main__":
    import sys
    regress_dir = sys.argv[1] if len(sys.argv) > 1 else ".regress"
    cmd = sys.argv[2] if len(sys.argv) > 2 else "summary"
    if cmd == "summary":
        s = summarize(regress_dir)
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif cmd == "raw":
        for e in load_history(regress_dir):
            print(json.dumps(e, ensure_ascii=False))
    elif cmd == "trace":
        print(build_trace(regress_dir))
