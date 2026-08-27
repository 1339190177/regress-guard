#!/usr/bin/env python3
"""journal — 考古地层（公理三：时间熵 → 地质资产）。

/tmp 状态是易挥发的认知介质（重启即失）；地层把失败/风险/纠正事件
append-only 地埋进项目 .regress/journal/events.jsonl，随 git 入库。

与 history.py 的分工：
  history.jsonl = 门禁决策史（commit 放行/阻断，由 pre_commit_guard 写）
  journal/events.jsonl = 执行现场化石（工具失败/风险动作/用户纠正，由探测器写）

未来维护者不靠回忆，像考古学家一样挖地层：
  /regress:learn 聚类跨会话重复失败 → 回写为规则。
"""
import os
import json
from datetime import datetime

# 单字段截断上限（防一条超大报错撑爆地层）
_FIELD_CAP = 400


def _find_project_dir(start_dir=None):
    """从 start_dir（默认 env 或 cwd）向上找含 .regress/ 的目录。"""
    d = start_dir or (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("ZCODE_PROJECT_DIR")
        or os.getcwd()
    )
    d = os.path.abspath(d)
    for _ in range(10):
        if os.path.isdir(os.path.join(d, ".regress")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def journal_path(project_dir):
    return os.path.join(project_dir, ".regress", "journal", "events.jsonl")


def journal_append(kind, start_dir=None, **fields):
    """埋一条化石。无 .regress/（未接入）或被关闭时静默跳过——地层是增强，不是依赖。

    kind: tool_fail / risk_action / user_correction / decision 等
    """
    if os.environ.get("REGRESS_JOURNAL", "").lower() in ("off", "0", "false"):
        return False
    project_dir = _find_project_dir(start_dir)
    if not project_dir:
        return False
    event = {
        "ts": datetime.now().isoformat(),
        "kind": kind,
        "session": (
            os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("ZCODE_SESSION_ID")
            or "default"
        ),
    }
    for k, v in fields.items():
        if isinstance(v, str):
            v = v[:_FIELD_CAP]
        event[k] = v
    try:
        os.makedirs(os.path.dirname(journal_path(project_dir)), exist_ok=True)
        with open(journal_path(project_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except (IOError, OSError):
        return False
    return True


def load_journal(project_dir):
    """读取全部地层事件（供 /regress:learn 考古挖掘）。"""
    path = journal_path(project_dir)
    events = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass
    return events


def journal_digest(project_dir, top=8):
    """简单聚合（顾问降级建议：不做聚类算法，按签名计数 + 跨会话过滤）。

    返回跨会话出现 ≥2 次的重复签名——单会话高频是重试噪声，
    跨会话重复才是稳定经验（与 history.py 的噪声过滤哲学一致）。
    """
    from collections import Counter

    events = [e for e in load_journal(project_dir) if e.get("kind") == "tool_fail"]
    sig_sessions = {}
    for e in events:
        sig = e.get("sig") or "?"
        sig_sessions.setdefault(sig, set()).add(e.get("session", "?"))
    stable = {s: len(sess) for s, sess in sig_sessions.items() if len(sess) >= 2}
    total = Counter(e.get("sig") or "?" for e in events)
    return [
        {"sig": sig, "sessions": n, "total": total.get(sig, 0)}
        for sig, n in sorted(stable.items(), key=lambda x: -x[1])[:top]
    ]


if __name__ == "__main__":
    import sys
    _d = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    _cmd = sys.argv[2] if len(sys.argv) > 2 else "digest"
    if _cmd == "raw":
        for _e in load_journal(_d):
            print(json.dumps(_e, ensure_ascii=False))
    elif _cmd == "add":
        # journal.py <dir> add <kind> '<json字段>' —— 命令层埋化石的统一出口
        # 例：journal.py . add assumption_broken '{"manifest_id":"R1","vid":"V5","was":"..."}'
        if len(sys.argv) < 4:
            print("用法: journal.py <dir> add <kind> '<json>'", file=sys.stderr)
            sys.exit(2)
        try:
            _fields = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        except json.JSONDecodeError as _e:
            print(f"json 字段解析失败: {_e}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps({"ok": journal_append(sys.argv[3], start_dir=_d, **_fields)},
                         ensure_ascii=False))
    else:
        print(json.dumps(journal_digest(_d), ensure_ascii=False, indent=2))
