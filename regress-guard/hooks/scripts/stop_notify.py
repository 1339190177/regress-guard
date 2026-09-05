#!/usr/bin/env python3
"""stop_notify — 轮末推送（v1.32.2：正常对话也推，用户令）。

病：done 事件只接在 /regress:finish（清单任务收尾），问答/分析/长自主轮不经过
任何推送点——用户离场等待时三度沉默（通道本身健康，双证据复验）。
v1.32.2：018 的"正常对话静音"设计被用户推翻——离场人类的任何轮次结束都是
"回来收货"信号。活跃对话的密集轮次由 90s 冷却天然吸收（隔 >90s 才再响）。

设计：UserPromptSubmit 已把最后一条用户输入存入状态文件
（prompt_intercept.load_last_prompt），Stop 时读它：
- 含授权词（自决策|自决|你决定|自主决|自动做|直接做|放手做）→
  done「🏁 阶段完成：<指令摘要>」
- 不含 → done「💬 回复完成：<指令摘要>」
- 90s 冷却（标记文件）防 finish 仪式推送后立即双响

Stop 钩子无 matcher（v1.27.1 空 matcher 掀翻整机的教训）。stdin 未用但保持读空。
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_HERE, "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from notify import notify  # noqa: E402

AUTONOMY_RE = re.compile(r"自决策|自决|你决定|自主决|自动做|直接做|放手做")
COOLDOWN_S = 90


def _project_dir():
    return (os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("ZCODE_PROJECT_DIR")
            or os.getcwd())


def _last_prompt():
    sys.path.insert(0, _HERE)
    from prompt_intercept import load_last_prompt
    return load_last_prompt()


def _marker_path():
    import hashlib
    key = hashlib.md5(_project_dir().encode()).hexdigest()[:8]
    return os.path.join(os.environ.get("TMPDIR", "/tmp"),
                        f"regress-guard-stop-notify-{key}.ts")


def _cooled():
    try:
        age = time.time() - os.path.getmtime(_marker_path())
        return age > COOLDOWN_S
    except OSError:
        return True


def _mark():
    try:
        with open(_marker_path(), "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def should_notify(last_prompt, cooled=True):
    """v1.32.2：任意轮末都推（用户令），冷却是唯一节流。"""
    return bool(last_prompt and cooled)


def main():
    try:
        _ = sys.stdin.read()
    except Exception:
        pass
    lp = _last_prompt()
    if not should_notify(lp, _cooled()):
        sys.exit(0)
    pd = _project_dir()
    excerpt = (lp or "")[:24]
    if AUTONOMY_RE.search(lp or ""):
        title, body = f"🏁 阶段完成：{excerpt}", "授权轮已收尾，可下发下一步或回来验收"
    else:
        title, body = f"💬 回复完成：{excerpt}", "本轮对话已收尾，可继续追问或离场"
    try:
        notify(pd, "done", title, body)
        _mark()
    except Exception as e:  # 推送是增强不是依赖
        print(f"stop_notify: 推送失败（忽略）: {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())
