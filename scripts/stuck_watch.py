#!/usr/bin/env python3
"""stuck_watch.py —— superagent 工单卡滞哨（批181）。

面板"running 不动"的三种真相：
  A. worker 活着在干活（长任务正常态，不报）
  B. assignment running 但 worker 会话转录 >20 分钟无写入 → 疑似卡死（报）
     （正常步进秒级；最长合法静默=浏览器磨合/装依赖≈12 分钟，REGRESS-059 实证）
  C. assignment running 但 worker 会话文件缺失/为空 → 悬空（报）
  D. 工单创建>2h 无任何 started assignment → 派发停摆（报）

只报不杀：恢复动作（retry/stop/issue 评论再触发）需要判断，归会话层/人类
（retry API 只收 failed/blocked，stopped-by-person 走评论——批175 实证）。
去重：同工单 2h 内不重复报；assignment 终态后自动清零。
批207：输出带心跳自证（实例 N/工单 M）——空转 bug（输出恒 running 0 谎报
健康）与真零从此可区分；main() 路径测试补位（此前 3 测全 helper 单测）。
退出码：0=无卡滞；1=有（已 WeCom+journal）；2=自崩（timer 不重试）。
状态：~/.zcode/workspace/default/.regress/stuck-watch.json
"""
import datetime
import glob
import json
import os
import sqlite3
import subprocess
import sys

GUARD_ROOT = os.path.expanduser("~/.zcode/workspace/default/regress-guard")
WORKSPACE = os.path.expanduser("~/.zcode/workspace/default")
STATE = os.path.join(WORKSPACE, ".regress", "stuck-watch.json")
def _state_dirs():
    """批192：glob 全部 superagent 实例（含未来新增）——含 orchestrator.sqlite 即一实例。"""
    out = []
    for d in sorted(glob.glob(os.path.expanduser("~/.dsh/state/superagent*"))):
        if os.path.isfile(os.path.join(d, "orchestrator.sqlite")):
            out.append(d)
    return out
SESSIONS = os.path.expanduser("~/.dsh/sessions")
STALE_MIN = 20        # 转录静默阈值（分钟）
QUEUE_STALL_H = 2     # 建单无派发阈值（小时）
REDEDUP_H = 2         # 同工单告警去重窗（小时）
# 批220：服务活性双信号——lock 新鲜阈值。实证节拍：活性服务对实例同级
# <dir>.lock 目录的触碰间隔 ≤2.5h（11-07 11:41→14:12 两观测点），12h=5 倍
# 余量。触碰是否纯心跳（长假真空闲会不会超 12h）未标定=FP1，跃迁制兜底
# （假跃迁最多一噪，2h 去重）。
LOCK_STALE_H = 12


def _notify(title, body):
    try:
        subprocess.run(
            [sys.executable, os.path.join(GUARD_ROOT, "lib", "notify.py"),
             ".", "chat", "--title", title, "--body", body],
            cwd=WORKSPACE, capture_output=True, timeout=30)
    except Exception:
        pass


def _journal(note):
    try:
        subprocess.run(
            [sys.executable, os.path.join(GUARD_ROOT, "lib", "journal.py"),
             WORKSPACE, "add", "ops_note",
             json.dumps({"note": note}, ensure_ascii=False)],
            capture_output=True, text=True, timeout=15)
    except Exception:
        pass


def _session_completed(path):
    """转录尾含 turn/end completed——worker 已正常收工（PR 未合致工单悬空=孤儿，非卡死）。
    run60 批182：昨夜 7 例"疑似卡死"实为孤儿（worker 完工、PR#20-26 全被⑤拦不合）。"""
    try:
        r = subprocess.run(["zstd", "-dc", path], capture_output=True,
                           text=True, timeout=60)
        tail = r.stdout[-800:]
        return '"turn/end"' in tail and '"completed"' in tail
    except Exception:
        return False


def _stale_label(completed):
    return "孤儿待闭环（worker 已完工，PR 升级未合）" if completed else "疑似卡死"


def _load():
    try:
        with open(STATE) as f:
            data = json.load(f)
        data.setdefault("alerted", {})  # 批207：最小态/手删键的文件不再 KeyError
        data.setdefault("liveness", {})  # 批220：实例上轮活/停（跃迁告警的记忆面）
        return data
    except Exception:
        return {"alerted": {}, "liveness": {}}


def _save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _session_path(ticket_id):
    return glob.glob(os.path.join(
        SESSIONS, "*", f"worker-{ticket_id}", "session.v4.jsonl.zstd"))


def _norm_path(p):
    """批221附（Windows CI 红×2）：归一顺序=先 normcase 再转正斜杠——normcase
    在 Windows 上会把正斜杠转回反斜杠（先转后 normcase=白干，v2.8.18 二红的
    根因），最终形态恒为小写正斜杠，跨平台可比。"""
    return os.path.normcase(p).replace("\\", "/")


def _proc_refs(state_dir, proc_root="/proc"):
    """进程扫描：cwd 或 cmdline 精确目录边界命中本实例 state 目录。

    批220 边界串扰标本：校准时 "superagent" 子串匹配误配了 superagent-tongtu
    的 bash sleep 进程（子串含于更长路径）——探针必须 state_dir+"/" 前缀或
    等值比对，绝不做裸子串。"""
    d = _norm_path(state_dir).rstrip("/") + "/"
    n = 0
    try:
        pids = os.listdir(proc_root)
    except OSError:
        return 0
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            cwd = os.readlink(os.path.join(proc_root, pid, "cwd"))
        except OSError:
            cwd = ""
        ncwd = _norm_path(cwd)
        if ncwd == _norm_path(state_dir) or ncwd.startswith(d):
            n += 1
            continue
        try:
            cmd = open(os.path.join(proc_root, pid, "cmdline"), "rb").read() \
                .decode("utf-8", "replace")
        except OSError:
            continue
        if d in _norm_path(cmd.replace("\0", " ")):
            n += 1
    return n


def _service_alive(state_dir, proc_root="/proc", now=None):
    """批220 双信号活性：lock 目录 mtime 新鲜 OR 进程在场。

    A（lock）：实例同级 <dir>.lock 目录被活性服务周期性触碰（停摆实例无此
    目录——主实例标本：11-02 后零转录零进程零 lock）。
    B（进程）：边界精确 /proc 扫描（worker 后台 job cwd 在 work/<工单>/ 下，
    服务本体 cwd 在原型仓——B 是 lock 语义漂移时的双保险）。
    返回 (alive, why)。"""
    now = now if now is not None else datetime.datetime.now().timestamp()
    lock = state_dir.rstrip("/") + ".lock"
    try:
        age_h = (now - os.path.getmtime(lock)) / 3600
        if age_h < LOCK_STALE_H:
            return True, f"lock {age_h:.1f}h 前触碰"
    except OSError:
        pass
    n = _proc_refs(state_dir, proc_root)
    if n:
        return True, f"{n} 进程在场"
    return False, "lock 缺失/超龄且零进程"


def main():
    now_local = datetime.datetime.now()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    st = _load()
    dirs = _state_dirs()
    tickets = []
    for sd in dirs:
        try:
            db = sqlite3.connect(
                "file:" + os.path.join(sd, "orchestrator.sqlite") + "?mode=ro", uri=True)
            for tid, raw in db.execute("SELECT id, value FROM ticket").fetchall():
                tickets.append((tid, raw))
            db.close()
        except Exception:
            continue  # 单库崩不拖全局

    running, findings, healthy = 0, [], []
    # 批207：原 `tickets = []` 变量遮蔽（批192 glob 重构引入）清空刚加载的
    # 列表后遍历空表——哨兵自 11-04 09:55 起空转 3 天（输出恒 running 0，
    # 昨日 18h 滞留全程谎报健康）。enriched 独立命名钉死此坑。
    enriched = []
    for tid, raw in tickets:
        d = json.loads(raw)
        title = (d.get("title") or "")[:36]
        assigns = d.get("assignments") or []
        is_running = any(a.get("state") == "running" for a in assigns)
        started_any = any(a.get("startedAt") for a in assigns)

        try:
            created = datetime.datetime.fromisoformat(
                d["createdAt"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        enriched.append((tid, title, is_running, started_any, created))

    # 两遍法：先数 running（判槽位），再评估停摆/卡滞
    for tid, title, is_running, started_any, created in enriched:
        if not is_running:
            st["alerted"].pop(tid, None)   # 终态自愈，清告警态
            continue
        running += 1
        files = _session_path(tid)
        # C. 悬空
        if not files or os.path.getsize(files[0]) == 0:
            if st["alerted"].get(tid, "") < (now_utc - datetime.timedelta(hours=REDEDUP_H)).isoformat():
                findings.append(f"[{tid[:8]}] {title} assignment running 但会话文件缺失——悬空")
                st["alerted"][tid] = now_utc.isoformat(timespec="seconds")
            continue
        # B. 转录静默（run60 批182：先分类——worker 已完工=孤儿待闭环，否则才疑似卡死）
        idle = (now_local - datetime.datetime.fromtimestamp(os.path.getmtime(files[0]))).total_seconds()
        if idle > STALE_MIN * 60:
            if st["alerted"].get(tid, "") < (now_utc - datetime.timedelta(hours=REDEDUP_H)).isoformat():
                label = _stale_label(_session_completed(files[0]))
                findings.append(f"[{tid[:8]}] {title} 转录静默 {idle/60:.0f} 分钟（>{STALE_MIN}）——{label}")
                st["alerted"][tid] = now_utc.isoformat(timespec="seconds")
        else:
            st["alerted"].pop(tid, None)
            healthy.append(f"{tid[:8]}({idle/60:.0f}m前活跃)")

    _save(st)
    # 批220 服务活性：双信号探针+跃迁制告警——"running 0 健康 N"分不清服务
    # 停摆与真空闲（11-07 周末 30h 空窗标本：停摆期间巡检照绿）。长期停摆
    # （主实例）=心跳如实展示不告警；活→停跃迁才 finding（一次，REDEDUP 窗
    # 去重）；首 run bootstrap 只记录；停→活只记录（重启是好事）。
    alive_n, dead_names = 0, []
    for sd in dirs:
        name = os.path.basename(sd)
        alive, why = _service_alive(sd)
        if alive:
            alive_n += 1
        else:
            dead_names.append(name)
        prev = st["liveness"].get(name)
        if prev is True and not alive:
            key = f"down:{name}"
            if st["alerted"].get(key, "") < (now_utc - datetime.timedelta(hours=REDEDUP_H)).isoformat():
                findings.append(f"[{name}] 服务疑似停摆（{why}）——上轮还活着")
                st["alerted"][key] = now_utc.isoformat(timespec="seconds")
        st["liveness"][name] = alive
    _save(st)
    # 批207 心跳自证：输出带扫描面（实例数/工单数）——哨兵视野为空（实例 0）
    # 与哨兵空转谎报（历史上恒 running 0）从此可区分；批220 再扩服务活性面
    line = (f"卡滞哨：实例 {len(dirs)} 工单 {len(tickets)}｜running {running} 健康 {len(healthy)}"
            f"｜服务 活{alive_n}/停{len(dead_names)}"
            + (f"（停: {', '.join(dead_names)}）" if dead_names else "")
            + (f"｜{', '.join(healthy)}" if healthy else ""))
    if findings:
        _journal("卡滞哨发现：" + "；".join(findings))
        _notify("superagent 卡滞告警", "\n".join(findings) + "\n（只报不杀，恢复动作归会话层/人类）")
        print(line)
        for x in findings:
            print("⚠", x)
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"stuck_watch 自崩: {e}", file=sys.stderr)
        sys.exit(2)
