#!/usr/bin/env python3
"""wecom_notify — 企业微信自建应用消息推送（v1.30 人类介入通知·体验最优通道）。

为什么是企业微信（用户令：体验最优）：Android 上腾讯系推送不被厂商电池策略
虐待；自建应用免费无限量；不占用业务服务号（运维流量与业务资产隔离）。
若"微信插件"路线可用，消息可直达微信主 APP（配置后实测即知）。

配置（.regress/config.json）：
  "notify": { "wecom": { "corpid": "ww...", "secret": "...",
                          "agentid": 1000002, "touser": "@all",
                          "proxy": "http://user:pass@ip:port" } }
  ——有 wecom 凭据时 notify() 自动把它插为第一通道（手机优先，机内声音/桌面次之）。
  proxy 可选：出口走固定 IP 中转（企业可信IP 白名单的机器，家宽动态 IP 场景）。

机制：access_token 缓存 $WECOM_TOKEN_DIR（默认 /tmp，key=cropid+secret 哈希），
过期前 300s 刷新；markdown 消息。best-effort：失败只 stderr、exit 0/1，不抛异常
（通知是增强不是依赖）。可测性：WECOM_API_BASE 指向桩服务器。

用法：wecom_notify.py <project_dir> <title> <body>
"""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def _conf(project_dir):
    try:
        with open(os.path.join(project_dir, ".regress", "config.json"),
                  encoding="utf-8") as f:
            cfg = json.load(f)
        return (cfg.get("notify") or {}).get("wecom") or {}
    except (IOError, OSError, json.JSONDecodeError):
        return {}


def _token_path(c):
    h = hashlib.sha1((str(c.get("corpid", "")) + str(c.get("secret", ""))).encode()).hexdigest()[:10]
    return os.path.join(os.environ.get("WECOM_TOKEN_DIR", "/tmp"), f"wecom_token_{h}.json")


def _opener(c):
    """有 proxy 配置时走固定 IP 中转（可信 IP 白名单），否则直连。"""
    proxy = c.get("proxy")
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def get_token(c, api):
    p = _token_path(c)
    now = time.time()
    try:
        with open(p, encoding="utf-8") as f:
            t = json.load(f)
        if t.get("expires_at", 0) > now + 300:
            return t["access_token"]
    except (IOError, OSError, json.JSONDecodeError):
        pass
    q = urllib.parse.urlencode({"corpid": c["corpid"], "corpsecret": c["secret"]})
    with _opener(c).open(f"{api}/gettoken?{q}", timeout=10) as r:
        d = json.load(r)
    if d.get("errcode"):
        raise RuntimeError(f"gettoken {d.get('errcode')}: {d.get('errmsg')}")
    tok = d["access_token"]
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"access_token": tok,
                       "expires_at": now + int(d.get("expires_in", 7200))}, f)
    except (IOError, OSError):
        pass
    return tok


def push(c, title, body, api):
    tok = get_token(c, api)
    payload = {"touser": c.get("touser", "@all"), "msgtype": "markdown",
               "agentid": int(c["agentid"]),
               "markdown": {"content": f"**{title}**\n{body}"}}
    req = urllib.request.Request(
        f"{api}/message/send?access_token={tok}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with _opener(c).open(req, timeout=10) as r:
        d = json.load(r)
    if d.get("errcode"):
        raise RuntimeError(f"send {d.get('errcode')}: {d.get('errmsg')}")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        print("用法: wecom_notify.py <project_dir> <title> <body>", file=sys.stderr)
        return 1
    project_dir, title, body = args[0], args[1], args[2]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from journal import _find_project_dir
    pd = _find_project_dir(project_dir) or project_dir
    c = _conf(pd)
    if not (c.get("corpid") and c.get("secret") and c.get("agentid")):
        print("wecom_notify: notify.wecom 未配置（corpid/secret/agentid）", file=sys.stderr)
        return 1
    api = os.environ.get("WECOM_API_BASE", "https://qyapi.weixin.qq.com/cgi-bin")
    try:
        push(c, title, body, api)
    except Exception as e:  # best-effort：不炸调用方
        print(f"wecom_notify: 推送失败（忽略）: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
