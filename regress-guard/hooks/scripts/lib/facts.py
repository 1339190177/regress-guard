#!/usr/bin/env python3
"""facts — 机器事实卡（v1.31 跨项目地层）：追加/刷新去重 + 代谢报表。

为什么是它：机器级经验（服务器拓扑/通道/环境坑）沉在单项目地层里别的项目借不到，
人类被迫人肉跨会话转述（企微任务实证）。单卡 + skill 描述路由 = 消费无感；
finish 代谢缝调用本库 = 捕获无感。刻意不做 Stop-hook 全自动提炼——质量噪音
会腐蚀整张卡的信任（可信但过期的事实带权威性撒谎，/opt 旧端口活标本）。

铁律：每条事实带日期（=最后一次验证为真的时间）；事实只当线索，
动手前照旧取证。卡不是审计日志——同键重录以最新表述为准、刷新日期。

用法：
  facts.py record "<标题>" "<内容>" [域]     # 追加或刷新（去重键=域+标题）
  facts.py health                            # 条数/最老天数/陈旧(>180d)清单
卡路径：$RG_FACTS_CARD 或 ~/.zcode/skills/machine-facts/SKILL.md
"""
import datetime
import os
import re
import sys

STALE_DAYS = 180
_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (.+?) · (.+)$")
_FRONTMATTER = """---
name: machine-facts
description: 涉服务器(VPS/SSH/端口/隧道)、通知通道、本机环境与工具坑(zsh/Debian/浏览器自动化/frp)时先查这张机器事实卡。事实带日期=最后验证为真；只当线索，动手前取证。
---

# 机器事实卡（跨项目地层）

"""


def card_path():
    return os.environ.get("RG_FACTS_CARD") or os.path.expanduser(
        "~/.zcode/skills/machine-facts/SKILL.md")


def _load():
    try:
        with open(card_path(), encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError):
        return ""


def _save(text):
    p = card_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def record(title, body, domain="通用", when=None):
    """同键（域+标题）重录=刷新日期+以最新表述为准；返回 'appended'/'refreshed'。"""
    text = _load()
    if not text:
        text = _FRONTMATTER
    day = (when or datetime.date.today()).isoformat()
    entry = f"### {day} · {domain} · {title}\n{body.strip()}\n\n"
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if m and m.group(2).strip() == domain and m.group(3).strip() == title:
            # 找到本条结尾（下一个 ### 或文末）
            j = i + 1
            while j < len(lines) and not lines[j].startswith("### "):
                j += 1
            new_lines = lines[:i] + [f"### {day} · {domain} · {title}"] \
                + body.strip().split("\n") + [""] + lines[j:]
            _save("\n".join(new_lines).rstrip("\n") + "\n")
            return "refreshed"
    _save(text.rstrip("\n") + "\n\n" + entry)
    return "appended"


def health():
    """返回 dict(count, oldest_days, stale=[(date, domain, title)...])。"""
    today = datetime.date.today()
    entries = []
    for ln in _load().split("\n"):
        m = _HEADING.match(ln)
        if m:
            entries.append((m.group(1), m.group(2), m.group(3)))
    stale, oldest = [], 0
    for date_s, domain, title in entries:
        try:
            age = (today - datetime.date.fromisoformat(date_s)).days
        except ValueError:
            continue
        oldest = max(oldest, age)
        if age > STALE_DAYS:
            stale.append((date_s, domain, title))
    return {"count": len(entries), "oldest_days": oldest, "stale": stale}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 2 and args[0] == "record":
        title, body = args[1], args[2]
        domain = args[3] if len(args) > 3 else "通用"
        print(record(title, body, domain))
        return 0
    if args and args[0] == "health":
        h = health()
        print(f"机器事实卡：{h['count']} 条 | 最老 {h['oldest_days']} 天 | "
              f"陈旧(>{STALE_DAYS}d) {len(h['stale'])} 条")
        for date_s, domain, title in h["stale"]:
            print(f"  🍂 {date_s} · {domain} · {title}")
        return 0
    print("用法: facts.py record <标题> <内容> [域] | health", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
