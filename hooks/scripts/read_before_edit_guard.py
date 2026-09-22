#!/usr/bin/env python3
"""read_before_edit_guard.py — "先读后改"门禁。

通过命令行参数区分模式：
  python3 read_before_edit_guard.py post   → PostToolUse 模式（记录 Read）
  python3 read_before_edit_guard.py pre    → PreToolUse 模式（拦截 Edit/Write）

PostToolUse(Read)  → 每次读文件，计数 +1
PreToolUse(Edit/Write) → 检查本轮 Read 次数是否足够

状态文件：系统临时目录 regress-guard-read-counter.json（按 sessionId 隔离）

规则（v1.92.0 判据链，野外报告#1 F1 重构）：
  - per-file 正门：改 X 前须读过 X（公理对齐）
  - 会话头防盲潜地板：首改前至少 min(ratio,3) 次读（旧 read_before_edit_ratio
    键向后兼容映射为地板值；旧全局累计比已废——39 改后要 80 读的死亡螺旋
    在野外被迫置 0，实证失效）
  - 地板满足后改未读文件：放行 + 软提示（广度退为提示不设硬比例）
  - 指纹哨兵不动：读后被外部改过仍硬拦
  - ratio=0 关闭，但降级 journal 留痕（每会话一次）
  - 新文件创建（Write 不存在的文件）豁免；.regress/ 与配置文件修改豁免

退出码：0=放行，2=阻断
"""
import sys
import os
import json
import tempfile

DEFAULT_RATIO = 3
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 指纹哨兵：本会话自己刚改过的文件（改后到下次 Read 之间挂起指纹校验）
SELF_EDITED = -1


def _fingerprint(fp):
    """文件指纹 [mtime_ns, size]——"每一粒灰尘都必须对得上"（公理二）。

    Read 时采集，Edit/Write 前复核；不一致 = 读后被外部修改（另一会话、
    git checkout、格式化进程……），盲改会基于过期认知，必须强制重读。
    """
    try:
        st = os.stat(fp)
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def get_state_path():
    # P2#17：按会话分文件——全会话共享单文件在并行钩子/两会话下互相丢计数
    # （既有误锁也有漏拦），旧全局文件留给兼容读取
    sid = (os.environ.get("CLAUDE_SESSION_ID")
           or os.environ.get("ZCODE_SESSION_ID") or "default")
    import hashlib as _h
    key = _h.md5(sid.encode()).hexdigest()[:8]
    return os.path.join(tempfile.gettempdir(),
                        f"regress-guard-read-counter-{key}.json")


def load_state():
    try:
        with open(get_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}


def save_state(state):
    try:
        with open(get_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except (IOError, OSError):
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"

    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", data) if isinstance(data, dict) else {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    session_id = (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("ZCODE_SESSION_ID")
        or "default"
    )

    # 读配置（支持 monorepo：从多个位置查找 .regress/）
    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("ZCODE_PROJECT_DIR")
        or os.getcwd()
    )
    # 向上查找 .regress/config.json
    config_path = None
    search_dir = project_dir
    for _ in range(10):  # 最多向上 10 级
        candidate = os.path.join(search_dir, ".regress", "config.json")
        if os.path.exists(candidate):
            config_path = candidate
            break
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

    ratio = DEFAULT_RATIO  # P2#25：单一常量（旧代码无 config 缺省 2、有 config 缺省 3、docstring 写 3——三处打架）
    if config_path:
        try:
            with open(config_path, encoding="utf-8") as f:
                ratio = json.load(f).get("read_before_edit_ratio", DEFAULT_RATIO)
        except (IOError, json.JSONDecodeError):
            pass

    # ratio=0 → 关闭此门禁（v1.92.0 起降级必须留痕——一行配置整体禁用
    # 太容易，野外标本：置 0 后门禁静默消失无人知道）
    if ratio <= 0:
        state = load_state()
        sess0 = state.get(session_id, {})
        if not sess0.get("disabled_noted"):
            try:
                sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))
                from journal import journal_append
                journal_append("note", start_dir=project_dir,
                               note="read_guard_disabled",
                               session=session_id[:16])
            except Exception:
                pass  # 地层是增强不是依赖
            state[session_id] = {**sess0, "disabled_noted": True}
            save_state(state)
        sys.exit(0)

    state = load_state()
    sess = state.get(session_id, {
        "read_count": 0, "edit_count": 0,
        "read_files": [], "last_reset": datetime.now().isoformat()
    })

    # ─── Post 模式：记录 Read ─────────────────────────
    if mode == "post" and tool_name == "Read":
        fp = tool_input.get("file_path", "")
        if fp:
            if fp not in sess["read_files"]:
                sess["read_files"].append(fp)
            fps = sess.get("read_fps") or {}
            fp_val = _fingerprint(fp)
            if fp_val:
                fps[fp] = fp_val
            sess["read_fps"] = fps
        sess["read_count"] += 1
        state[session_id] = sess
        save_state(state)
        sys.exit(0)

    # ─── Pre 模式：拦截 Edit/Write ────────────────────
    if mode == "pre" and tool_name in ("Edit", "Write", "ApplyPatch"):
        fp = tool_input.get("file_path", "")

        # 指纹复核（公理二）：读后文件被外部改过 → 禁止盲改，强制重读
        fps = sess.get("read_fps") or {}
        recorded = fps.get(fp)
        if recorded not in (None, SELF_EDITED):
            current = _fingerprint(fp)
            if current is not None and current != recorded:
                print(
                    f"REGRESS-GUARD: 🪞 文件指纹不匹配\n"
                    f"  {fp}\n"
                    f"  最后一次读取后文件被外部修改（另一会话/git/格式化进程）。\n"
                    f"  你记忆里的内容已过期，禁止基于过期认知盲改。\n"
                    f"  → 先重新 Read 该文件，确认现状后再改。",
                    file=sys.stderr
                )
                sys.exit(2)

        # 豁免：新文件创建
        if tool_name == "Write" and fp and not os.path.exists(fp):
            sess["edit_count"] += 1
            state[session_id] = sess
            save_state(state)
            sys.exit(0)

        # 豁免：框架自身文件
        if ".regress/" in fp or fp.endswith("AGENTS.md") or "regress-guard" in fp:
            sys.exit(0)

        def _allow_edit():
            sess["edit_count"] += 1
            if fp:
                # 自己改的：挂起指纹校验直到下次 Read（改后 mtime 必然变化）
                sess.setdefault("read_fps", {})[fp] = SELF_EDITED
            state[session_id] = sess
            save_state(state)
            sys.exit(0)

        # ─── v1.92.0（111，野外报告#1 F1）判据链重排 ───
        # 公理是 per-file（改 X 前读过 X），旧实现的全局累计比
        # required=(edit_count+1)*ratio 把重复编辑计入惩罚——39 改后要 80 读，
        # 长会话数学必死（野外被迫置 0 实证）。新链：
        #   ①目标 ∈ read_files → 放（per-file 正门）
        #   ②开局盲潜 → 拦（bootstrap 地板 N=min(ratio,3)，旧配置键兼容映射）
        #   ③中间带（读了别的、改这个未读的）→ 放 + 软提示
        #   ④指纹哨兵链不动（读后被外部改过仍硬拦——盲改的主体防线）
        BOOTSTRAP = min(int(ratio), 3)
        if fp and fp in sess.get("read_files", []):
            _allow_edit()

        if sess["read_count"] < BOOTSTRAP:
            print(
                f"REGRESS-GUARD: ⚠️ 先读后改门禁（开局盲潜）\n"
                f"  本轮已读 {sess['read_count']} 个文件（防盲潜地板 {BOOTSTRAP}）。\n"
                f"  目标文件 {fp} 本轮尚未读取——请先 Read 再改。\n"
                f"  （per-file 为正门：改过的文件读过即放；关闭：config 设 "
                f"read_before_edit_ratio: 0，降级会留痕）",
                file=sys.stderr
            )
            sys.exit(2)

        print(
            f"REGRESS-GUARD (hint): {fp} 本轮未读过即改——盲改风险，"
            f"建议先 Read（per-file 地板已满足故放行）。",
            file=sys.stderr
        )
        _allow_edit()

    sys.exit(0)


if __name__ == "__main__":
    main()
