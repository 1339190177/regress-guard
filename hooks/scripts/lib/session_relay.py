#!/usr/bin/env python3
"""session_relay — 会话身份中继（v1.34 清单会话作用域）。

事实基础：PreToolUse/UserPromptSubmit 钩子进程带 CLAUDE_SESSION_ID /
ZCODE_SESSION_ID（活体证据：/tmp/regress-guard-fails-sess_*.jsonl 按会话
分文件），而 Bash 工具进程不带——agent 侧经 Bash 跑的脚本（plan_approve
盖章）无法自证会话身份，只能靠钩子侧中继。

写入点：UserPromptSubmit 每轮（含 / 命令轮——命令轮也是本会话的轮）。
读取点：plan_approve 批准/临行/受阻时给清单盖 session 戳。

last-writer-wins：两会话同项目并发时盖章可能错归属一拍——错向是
「自己的清单被当他人的」（拦截可见可修），不是静默放行（顾问预审认可）。
原子写：临时文件 + rename，防并发写半行（顾问补强点）。
"""
import datetime
import hashlib
import json
import os
import tempfile


def sid_from_env():
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("ZCODE_SESSION_ID")
        or ""
    )


def relay_path(project_dir):
    key = hashlib.md5(os.path.abspath(project_dir).encode()).hexdigest()[:8]
    return os.path.join(tempfile.gettempdir(), f"regress-guard-session-{key}.json")


def write_relay(project_dir, sid=None):
    """钩子侧每轮写：当前在该项目说话的会话号。"""
    sid = sid if sid is not None else sid_from_env()
    if not sid:
        return False
    p = relay_path(project_dir)
    try:
        tmp = p + f".tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sid": sid, "ts": datetime.datetime.now().isoformat(
                timespec="seconds")}, f, ensure_ascii=False)
        os.replace(tmp, p)  # 原子：并发 last-writer-wins，不出现半行
        return True
    except (IOError, OSError):
        return False


def read_relay(project_dir):
    """agent 侧读：最近一轮在本项目说话的会话号（缺省空 dict=无中继）。"""
    try:
        with open(relay_path(project_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (IOError, OSError, json.JSONDecodeError):
        return {}


def relay_fresh_sid(project_dir, max_age_minutes=5):
    """新鲜窗内的 relay sid（窗外/缺失/坏 ts → 空串）。

    relay 仅在新鲜窗内有效（UserPromptSubmit 每轮写，活跃会话恒新鲜；
    窗外=陈旧中继不得再代言——会话切换后旧号失效语义保留）。
    """
    d = read_relay(project_dir) if project_dir else {}
    sid, ts = str(d.get("sid") or ""), str(d.get("ts") or "")
    if not sid:
        return ""
    try:
        age = (datetime.datetime.now()
               - datetime.datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return ""
    return sid if 0 <= age <= max_age_minutes * 60 else ""


def my_sids(project_dir, max_age_minutes=5, payload_sid=None):
    """批225（issue#8）：守卫侧身份集——payload 锚定优先，冲突不弃 env。

    语义真源=docs/会话身份语义.md。三级：
    ① payload_sid 在场（钩子进程 stdin 载荷真号，两宿主皆然）→
      {payload} ∪ {env 若在}——payload=当前真身锚点；env 保留兜 ZCode
      续接旧戳清单（env 是自有谱系旧号，从不是他会话号——弃 env=双 id
      自拦回归）。**relay 不进集**：其「无载荷语境下猜真身」的使命已被
      payload 取代，且 DSH 同项目多 agent 会话共享 relay 被 last-writer-wins
      踩踏（issue#8 实测 2-5 分钟/次）——带他会话噪音。
    ② 无 payload（agent 侧 CLI 等）→ env ∪ 新鲜 relay 并集，冲突不弃 env
      ——批218 根治档「冲突以 relay 真身为准 env 即弃」的前提（env 恒陈旧）
      是 ZCode 续接特例；DSH 每钩子/工具进程 env 皆真身，弃 env=弃真身
      →自己拦自己（issue#8 主诉）。
    ③ 单源 → 该源即身份。
    只读判等专用：不写回不继承（防中继回翻污染持久化戳）。
    残留已知面：无 payload 路径的并集含他会话新鲜 relay=误放窗口（有界
    5min，批218 前既有语义；写者指纹/单调序号=定稿 backlog 不变）。
    """
    env_sid = sid_from_env()
    if payload_sid:
        ids = {payload_sid}
        if env_sid:
            ids.add(env_sid)
        return ids
    relay_sid = relay_fresh_sid(project_dir, max_age_minutes)
    ids = set()
    if env_sid:
        ids.add(env_sid)
    if relay_sid:
        ids.add(relay_sid)
    return ids
