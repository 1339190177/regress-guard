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
import shlex
import shutil
import subprocess
import sys

EVENTS = ("plan_approval", "blocked", "sensory", "finish_open", "done", "test")

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


def load_conf(project_dir):
    try:
        with open(os.path.join(project_dir, ".regress", "config.json"),
                  encoding="utf-8") as f:
            cfg = json.load(f).get("notify", {})
    except (IOError, OSError, json.JSONDecodeError):
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def notify(project_dir, event, title, body=""):
    """发通知（best-effort）。返回实际执行的通道数。"""
    cfg = load_conf(project_dir)
    if cfg.get("enabled", True) is False:
        return 0
    events = cfg.get("events", {})
    if event != "test" and events and not events.get(event, True):
        return 0
    channels = list(cfg.get("channels") or _default_channels())
    wc = cfg.get("wecom") or {}
    if wc.get("corpid") and wc.get("secret") and wc.get("agentid"):
        # 企业微信自动第一通道（体验最优：手机先响，机内声音/桌面次之）
        lib = os.path.dirname(os.path.abspath(__file__))
        channels.insert(0, 'python3 "%s" "%s" {title} {body}'
                        % (os.path.join(lib, "wecom_notify.py"), project_dir))
    ran = 0
    for tpl in channels:
        cmd = tpl.format(title=shlex.quote(title), body=shlex.quote(body)) \
            if ("{title}" in tpl or "{body}" in tpl) else tpl
        try:
            r = subprocess.run(cmd, shell=True, timeout=5,
                               capture_output=True, text=True)
            if r.returncode == 0:
                ran += 1
            else:
                print(f"notify: 通道失败 rc={r.returncode}（忽略）: {cmd.split()[0]}",
                      file=sys.stderr)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"notify: 通道失败（忽略）: {cmd.split()[0]}: {e}",
                  file=sys.stderr)
    return ran


def main(argv=None):
    ap = argparse.ArgumentParser(description="人类介入通知")
    ap.add_argument("project_dir", help="项目目录（. 通常够用）")
    ap.add_argument("event", choices=EVENTS)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from journal import _find_project_dir  # 项目定位单一来源
    project_dir = _find_project_dir(args.project_dir)
    if not project_dir:
        return 0  # 未接入项目：静默（通知是增强不是依赖）
    notify(project_dir, args.event, args.title, args.body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
