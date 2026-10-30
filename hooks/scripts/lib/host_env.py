"""host_env —— 宿主环境垫片（批166，REGRESS-2026-164：dsh 桌面版支持）。

不同宿主给钩子传会话身份的方式不同：
- ZCode / Claude Code 系：CLAUDE_SESSION_ID / ZCODE_SESSION_ID 环境变量
- dsh（经 dsh-hooks-claude-code 桥）：**不设该 env**——会话身份在 stdin
  payload 的 session_id 字段（桥契约：every agent-scoped stdin payload
  carries session_id）

无此垫片时 dsh 上全部会话落 default 键：read_before_edit 计数跨会话串味
（P2#17 病理——批159 曾因共享键在并行档翻车）、提交归因全混一桶。
错归属比无归属糟，垫片只补缺不覆盖（已有 env=宿主明示，尊重之）。
"""
import os

# dsh 工具名→CC 规范名（批166 侦察实证：dsh 注册小写 bash/read/write/edit
# 另有 pwsh；钩子内部分支按 CC 大小写匹配——不规范化则 dsh 会话全线漏判，
# 表现为"放行"实为"没认出来"的假阴性）。pwsh→Bash：同属命令执行语义
# （守卫按 Bash 形态提命令串）。read_image 不映射：matcher 层已排除
# （图像不授文本认知，docs/dsh-support.md 留痕）。
_CANON_TOOL = {"bash": "Bash", "pwsh": "Bash", "read": "Read",
               "write": "Write", "edit": "Edit"}


def canonicalize_tool_names(payload):
    """把 dsh 小写工具名规范化为 CC 形态（原地改写 tool_name，幂等）。

    仅映射已知 dsh 名；其余（CC 名/未知名）不动——未知工具交给各守卫
    既有语义（C 档让门禁自判，不在此猜测）。"""
    if isinstance(payload, dict):
        t = payload.get("tool_name")
        if isinstance(t, str) and t in _CANON_TOOL:
            payload["tool_name"] = _CANON_TOOL[t]
    return payload


def absorb_session(payload):
    """从 stdin payload 吸收 session_id 到 env（仅当 env 无会话键时）。

    payload 非 dict / 无 session_id / env 已有键 → 不动（fail-open 垫片，
    缺身份回退 default 键是既有语义）。返回最终生效的会话键（教学位）。
    """
    if not isinstance(payload, dict):
        return os.environ.get("CLAUDE_SESSION_ID") \
            or os.environ.get("ZCODE_SESSION_ID") or "default"
    sid = payload.get("session_id")
    if not sid or not isinstance(sid, str):
        return os.environ.get("CLAUDE_SESSION_ID") \
            or os.environ.get("ZCODE_SESSION_ID") or "default"
    if not (os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("ZCODE_SESSION_ID")):
        os.environ["CLAUDE_SESSION_ID"] = sid
    return os.environ.get("CLAUDE_SESSION_ID") \
        or os.environ.get("ZCODE_SESSION_ID") or "default"
