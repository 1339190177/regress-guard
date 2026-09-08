#!/usr/bin/env python3
"""notify — 人类介入通知（v1.30：人类的一寸的最后一段）。

决策点到、人不在屏前：计划待批准 / 受阻待输入 / 感官终验 / 收尾 open——
往配置的通道发通知（桌面通知、声音、手机推送……通道=命令，参数化到头）。

设计（用户令：可配置化、参数化先）：
- 通道 = .regress/config.json 的 notify.channels：命令字符串列表，{title}/{body}
  占位符会被 shlex.quote 后替换（模板里不要再加引号）；无占位符的命令原样跑
  （声音类）。默认自动探测：notify-send 在装则桌面通知；aplay+wav 在则提示音
  （声音出口由系统音频层决定——蓝牙耳机连着即走蓝牙）。
- 事件 = notify.events 四类开关（plan_approval/blocked/sensory/finish_open），
  默认全开；notify.enabled=false 一刀关。
- 纪律：best-effort——任一通道失败只 stderr 一行，绝不非零退出（通知是增强，
  不是依赖；不许让通知故障阻塞主流程）。

用法：
  notify.py . plan_approval --title "📋 REGRESS-x 待批准" --body "改动 3 文件"
  notify.py . blocked --title "🛑 受阻" --body "需要：开 Redis 白名单"
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

EVENTS = ("plan_approval", "blocked", "sensory", "finish_open", "done", "progress", "test")
# 决策型事件（v1.34 推送闭环）：送出即落待决台账，人类 outcome 回流成误报率——
# 广播升级为闭环（collar 启示：误报标注反过来校准告警策略本身，防 alert fatigue）
DECISION_EVENTS = ("plan_approval", "blocked", "sensory", "finish_open")

_SND_CANDIDATES = (
    "/usr/share/sounds/alsa/Front_Center.wav",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
)


def _default_channels():
    ch = []
    if shutil.which("notify-send"):
        ch.append("notify-send -a regress-guard -u critical {title} {body}")
    wav = next((p for p in _SND_CANDIDATES
                if p.endswith(".wav") and os.path.exists(p)), None)
    if wav and shutil.which("aplay"):
        ch.append(f"aplay -q {wav}")
    return ch


def _read_notify_block(path):
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        block = cfg.get("notify") if isinstance(cfg, dict) else None
        return block if isinstance(block, dict) else {}
    except (IOError, OSError, json.JSONDecodeError):
        return {}


def machine_conf_path():
    return os.environ.get("RG_MACHINE_NOTIFY") or os.path.join(
        os.path.expanduser("~/.zcode"), "regress-notify.json")


def load_conf(project_dir):
    """两层合并（v1.31.3）：机器级 ~/.zcode/regress-notify.json 为底，
    项目 .regress/config.json 按键覆盖——其他项目零配置即得手机推送。
    wecom/events 按键深合并（项目可只覆盖 agentid/单个开关），其余浅合并项目胜；
    项目级只该放差异键（name/事件微调），凭据放机器级一处改处处生效。"""
    merged = _read_notify_block(machine_conf_path())
    proj = _read_notify_block(os.path.join(project_dir, ".regress", "config.json"))
    for k, v in proj.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            sub = dict(merged[k])
            sub.update(v)
            merged[k] = sub
        else:
            merged[k] = v
    return merged


def notify(project_dir, event, title, body="", source_id=""):
    """发通知（best-effort）。返回实际执行的通道数。

    格式统一在层内注入（v1.31.2，用户令"应含项目名/任务名/时间"）：
    标题加【项目名】前缀（cfg notify.name，缺省目录名）；正文缀 🕐 本地时间。
    调用方只写任务名——五个事件的推送点分散，约定放调用方必然漏。
    source_id（P0-3 回流接线）：清单 id——入待决台账的 ref 字段，
    plan_approve 批准/取消时按它精确自动 resolve。
    """
    cfg = load_conf(project_dir)
    if cfg.get("enabled", True) is False:
        return 0
    events = cfg.get("events", {})
    if event != "test" and events and not events.get(event, True):
        return 0
    pname = cfg.get("name") or os.path.basename(os.path.abspath(project_dir))
    title = f"【{pname}】{title}"
    if event in DECISION_EVENTS:
        # 预分配待决号进正文（v1.34）：人类裁决时对着号说话，agent 记 pending。
        # 台账记决策不记送达——决策点真实存在（计划在等批准），通道失败也留账。
        try:
            from pending import add as _padd
            body += f"\n〔待决#{_padd(pname, event, title, ref=source_id)}〕处理后回「有用/误报/忽略」"
        except Exception:
            pass
    if body:
        body = f"{body}\n🕐 {time.strftime('%m-%d %H:%M')}"
    else:
        body = f"🕐 {time.strftime('%m-%d %H:%M')}"
    channels = list(cfg.get("channels") or _default_channels())
    wc = cfg.get("wecom") or {}
    env = dict(os.environ, RG_NOTIFY_EVENT=event)
    if wc.get("corpid") and wc.get("secret") and wc.get("agentid"):
        # 企业微信自动第一通道（体验最优：手机先响，机内声音/桌面次之）。
        # 合并后的 wecom 块经 env 传给子进程——wecom_notify 自己只读项目级文件，
        # 不传则机器级回退在子进程失效（2026-09-05 演示项目静默失败病例）。
        lib = os.path.dirname(os.path.abspath(__file__))
        channels.insert(0, 'python3 "%s" "%s" {title} {body}'
                        % (os.path.join(lib, "wecom_notify.py"), project_dir))
        env["RG_NOTIFY_WECOM_JSON"] = json.dumps(wc, ensure_ascii=False)
    ran = 0
    for tpl in channels:
        cmd = tpl.format(title=shlex.quote(title), body=shlex.quote(body)) \
            if ("{title}" in tpl or "{body}" in tpl) else tpl
        try:
            r = subprocess.run(cmd, shell=True, timeout=5,
                               capture_output=True, text=True, env=env)
            if r.returncode == 0:
                ran += 1
            else:
                print(f"notify: 通道失败 rc={r.returncode}（忽略）: {cmd.split()[0]}",
                      file=sys.stderr)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"notify: 通道失败（忽略）: {cmd.split()[0]}: {e}",
                  file=sys.stderr)
    if ran == 0 and channels:
        # 全通道失败兜底（v1.33 企业级）：手机不通至少本机响一声——
        # 通道故障期不再完全静默，回来的人从桌面/声音知道出过事
        for tpl in _default_channels():
            try:
                cmd = tpl.format(title=shlex.quote(title), body=shlex.quote(body)) \
                    if ("{title}" in tpl or "{body}" in tpl) else tpl
                subprocess.run(cmd, shell=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
    return ran


def _stats():
    """观察仪表盘（v1.34）：发送台账 + 待决台账聚合——观察期的数字层。
    北极星候选：送达率（可达段）、未决数与最老悬停（闭环段）、误报率（校准段）。
    台账行格式见 wecom_notify；event= 维度 v1.34 起有（旧行归"旧格式"）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print("═══ regress-guard 观察仪表盘 ═══")
    ledger = os.path.expanduser(
        os.environ.get("RG_SEND_LEDGER") or "~/.zcode/wecom-send.log")
    total = ok = 0
    by_event = {}
    try:
        with open(ledger, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2} errcode=(\d+)", line)
                if not m:
                    continue
                total += 1
                ok += m.group(1) == "0"
                ev = re.search(r" event=(\S+)", line)
                k = ev.group(1) if ev else "旧格式"
                by_event[k] = by_event.get(k, 0) + 1
    except (IOError, OSError):
        pass
    if total:
        print(f"企微发送：{total} 条｜送达 {ok}｜送达率 {ok / total:.0%}")
        for k in sorted(by_event, key=lambda x: -by_event[x]):
            print(f"  {k:<14} ×{by_event[k]}")
    else:
        print("企微发送：暂无记录（v1.32.6 起真实发送入台账）")
    from pending import stats as _pstats
    s = _pstats()
    fp = "—" if s["fp_rate"] is None else f"{s['fp_rate']:.0%}"
    print(f"待决闭环：未决 {s['pending']}（最老 {s['oldest_pending'] or '—'}）｜"
          f"裁决 有用{s['resolved']['useful']}/误报{s['resolved']['fp']}/"
          f"忽略{s['resolved']['ignored']}｜误报率 {fp}")
    for e in s["open"][-5:]:
        print(f"  ⏳ #{e['id']} {e['ts'][:16]} [{e['event']}] {e['title'][:40]}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "stats":
        _stats()
        return 0
    ap = argparse.ArgumentParser(description="人类介入通知")
    ap.add_argument("project_dir", help="项目目录（. 通常够用）")
    ap.add_argument("event", choices=EVENTS)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--ref", default="",
                    help="来源清单 id（P0-3 回流接线：批准/取消时自动 resolve 同 ref 待决）")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from journal import _find_project_dir  # 项目定位单一来源
    project_dir = _find_project_dir(args.project_dir)
    if not project_dir:
        return 0  # 未接入项目：静默（通知是增强不是依赖）
    notify(project_dir, args.event, args.title, args.body, source_id=args.ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
