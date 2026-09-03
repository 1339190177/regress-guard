#!/usr/bin/env python3
"""boundary_guard — 开发边界守卫（PreToolUse Edit|Write|ApplyPatch 拦截）。

思想（2026-08-22 用户对话启示）：检测≠拦截——Stop 钩子的方向漂移提醒是
"事后追认"，token 已烧、熵已生；边界必须在动作发生前物理拦截。
实证：无边界的 agent 一天 6B 消耗半个月完不成任务、复检几十轮；
加边界后 <1B/天、多任务/天、自动复检即达标。约束不是拖慢，是提速。

拦截顺序（短路）：
  0. 赦免：config.bypass_until 未过期 → 全放行（与 commit 门禁同源的唯一逃生口）
  1. 项目级禁改区：config.boundary.forbidden 通配，任何任务状态都拦（冻结区/遗留区）
  2. 任务边界：活跃清单（planning/in-progress/verifying/blocked）取并集
     planning=待批准拦编辑；approved.at 非空=人类产物直通视同已批准；
     blocked=受阻拦编辑（合法停止不是绕过理由）
  3. 无边界信息 → 放行（fail-open，不误锁）
豁免：.regress/**、AGENTS.md、regress-guard 自身文件。
越界的合法出口：/regress:track 回写 actual_changes（扩界留痕）；
禁改区的合法出口：/regress:bypass <分钟>（赦后记债）或改 config。
关闭：.regress/config.json 设 "boundary_enforced": false。

v1.20：字段读取与可编辑性判定收敛到 lib/manifest_fields.py（单一来源）。

退出码：0=放行，2=阻断
"""
import sys
import os
import json
import re
import fnmatch
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from manifest_fields import (  # noqa: E402
    ACTIVE_STATUS_RE, block_value, editable, parse_core,
)
from manifest_parser import read_frontmatter  # noqa: E402  长寿扫描：只读 frontmatter

# 自定位绝对路径（源/安装两种布局同构）——拦截消息不留给读者猜的相对引用
APPROVE_SCRIPT = os.path.join(LIB_DIR, "plan_approve.py")


def _load_config(project_dir):
    cfg = os.path.join(project_dir, ".regress", "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, json.JSONDecodeError):
        return {}


def find_project_dir():
    d = (
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


def config_disables_boundary(project_dir):
    return _load_config(project_dir).get("boundary_enforced") is False


def bypass_active(project_dir):
    """限时赦免（v1.20 赦免权普适化）：与 pre_commit_guard 同源读 bypass_until。"""
    until = str(_load_config(project_dir).get("bypass_until") or "").strip()
    if not until:
        return False
    try:
        return datetime.now() < datetime.fromisoformat(until)
    except (ValueError, TypeError):
        return False  # 格式坏 = 过期


def forbidden_globs(project_dir):
    """项目级禁改区（v1.20）：boundary.forbidden 通配列表。

    形状错误 fail-loud：stderr 警告但不砖（返回 [] 放行——禁改区是增强不是依赖）。
    """
    v = (_load_config(project_dir).get("boundary") or {}).get("forbidden")
    if v is None:
        return []
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    print("REGRESS-GUARD: ⚠️ config boundary.forbidden 形状错误（应为字符串数组），"
          "禁改区未生效", file=sys.stderr)
    return []


def parse_boundary(manifest_path):
    """从清单 frontmatter 提取边界：显式 include 通配 或 精确文件集。

    返回 (patterns, exact_files, manifest_id, status, approved_at)；
    patterns 与 exact 皆空 = 无边界信息。
    """
    try:
        with open(manifest_path, encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError):
        return [], [], "", "", ""
    core = parse_core(content)
    if not core:
        return [], [], "", "", ""
    fm_text = content.split("---", 2)[1] if content.startswith("---") else ""

    patterns = []
    # 显式 boundary: include: 列表（支持 "- glob" 行与行内 [a, b]）
    bm = re.search(r"^boundary:\s*\n((?:[ \t]+.*\n?)+)", fm_text, re.M)
    if bm:
        block = bm.group(1)
        im = re.search(r"^[ \t]+include:\s*(.*)$", block, re.M)
        if im:
            inline = im.group(1).strip()
            if inline.startswith("[") and inline.endswith("]"):
                patterns = [p.strip().strip('"\'') for p in inline[1:-1].split(",") if p.strip()]
            else:
                for ln in block.splitlines():
                    s = ln.strip()
                    if s.startswith("- "):
                        patterns.append(s[2:].strip().strip('"\''))

    exact = set()
    # 精确集（planned+actual）永远算边界的一部分——track 回写 actual_changes
    # 即扩界（逃逸出口）；显式 include 通配只是在精确集之上加宽。
    for fm_file in re.finditer(r"file:\s*[\"']?([^\"'\n#]+)", fm_text):
        exact.add(fm_file.group(1).strip().strip("/"))
    return patterns, sorted(exact), core["id"], core["status"], core["approved_at"]


def active_manifests(project_dir):
    import glob
    out = []
    mdir = os.path.join(project_dir, ".regress", "manifests")
    if os.path.isdir(mdir):
        for f in sorted(glob.glob(os.path.join(mdir, "*.md")), reverse=True):
            # v1.23.2 长寿扫描：只搜 frontmatter——done 堆积后仍是 O(frontmatter)，
            # 且正文引用状态词不再让 done 清单诈尸（旧实现两头的坑）
            try:
                if ACTIVE_STATUS_RE.search(read_frontmatter(f)):
                    out.append(f)
            except (IOError, OSError):
                pass
    return out


def extract_write_targets(cmd):
    """Bash 高置信度写目标（v1.29 旁路收口；病例：rm 删边界内文件零拦截）。

    只认高置信形态，不确定一律漏过——fail-open 防误拦测试命令（2> 重定向不收：
    stderr 日志类误拦代价高于漏拦；/dev/null 豁免）。
    """
    targets = set()
    for m in re.finditer(r'(?<![0-9])>{1,2}\s*([^\s;|&]+)', cmd):
        targets.add(m.group(1))
    for m in re.finditer(r'&>{1,2}\s*([^\s;|&]+)', cmd):
        targets.add(m.group(1))
    for m in re.finditer(
            r'(?:^|[;|&\s])(rm|rmdir|mv|cp|tee|truncate|touch|install|shred)\s+([^;|&\n]+)',
            cmd):
        name, rest = m.group(1), m.group(2)
        toks = [t for t in rest.split() if not t.startswith("-")]
        if not toks:
            continue
        if name in ("mv", "cp", "install"):
            if len(toks) >= 2:
                targets.add(toks[-1])
        else:
            targets.update(toks)
    for m in re.finditer(r'(?:^|[;|&\s])sed\s+(?:-[^\s]*i[^\s]*\s+)?(?:-[^\s]*\s+)*([^;|&\n]+)', cmd):
        toks = [t for t in m.group(1).split() if not t.startswith("-")]
        if toks:
            targets.add(toks[-1])
    for m in re.finditer(r'\bof=([^\s;|&]+)', cmd):
        targets.add(m.group(1))
    out = set()
    for t in targets:
        t = t.strip('\'""')
        if (not t or t.startswith("$") or t in ("/dev/null", "/dev/stdout", "/dev/stderr")
                or t.isdigit()):
            continue
        out.add(t)
    return out


def path_matches(path_rel, patterns, exact_files):
    p = path_rel.strip("/")
    for e in exact_files:
        e = e.strip().strip('"').strip("/")
        if not e:
            continue
        if p == e or p.endswith("/" + e) or e.endswith("/" + p):
            return True
    for pat in patterns:
        pat = pat.strip().strip("/")
        if not pat:
            continue
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat + "/*"):
            return True
        # src/** 也直接匹配 src 自身路径前缀下的所有深度
        if pat.endswith("/**") and (p == pat[:-3] or p.startswith(pat[:-3] + "/")):
            return True
    return False


def is_exempt(fp_rel, fp_abs):
    if ".regress/" in fp_rel or fp_rel.startswith(".regress"):
        return True
    if fp_rel.endswith("AGENTS.md") or "regress-guard" in fp_abs:
        return True
    return False


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw:
        sys.exit(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write", "ApplyPatch", "Bash"):
        sys.exit(0)
    ti = data.get("tool_input", {})
    if not isinstance(ti, dict):
        sys.exit(0)
    if tool == "Bash":
        # v1.29 旁路收口：Bash 写目标走与 Edit 相同的边界判定（病例：rm 删边界内文件零拦截）
        fps = sorted(extract_write_targets(str(ti.get("command") or "")))
        if not fps:
            sys.exit(0)
    else:
        fp = str(ti.get("file_path") or ti.get("path") or "")
        if not fp:
            sys.exit(0)
        fps = [fp]
    via = "（Bash 写目标）" if tool == "Bash" else ""

    project_dir = find_project_dir()
    if project_dir is None:
        sys.exit(0)
    if config_disables_boundary(project_dir):
        sys.exit(0)

    # ─── 0. 赦免权（统一逃生口）：bypass 有效期内放行一切编辑 ───
    if bypass_active(project_dir):
        sys.exit(0)

    forb = forbidden_globs(project_dir)
    manifests = active_manifests(project_dir)
    boundaries = []
    for mf in manifests:
        patterns, exact, mid, status, approved_at = parse_boundary(mf)
        if (patterns or exact) and status not in ("done", "completed", "cancelled"):
            boundaries.append((mf, patterns, exact, mid, status, approved_at))
    if not boundaries and not forb:
        sys.exit(0)  # 无边界信息，fail-open（含无活跃清单——设计语义）

    for fp in fps:
        fp_abs = os.path.abspath(
            fp if os.path.isabs(fp) else os.path.join(project_dir, fp))
        try:
            fp_rel = os.path.relpath(fp_abs, project_dir).replace(os.sep, "/")
        except ValueError:
            fp_rel = fp_abs.replace(os.sep, "/")
        if fp_rel.startswith("../"):
            # 项目目录之外的文件：一律视为边界外（除非豁免路径）
            fp_rel = os.path.normpath(fp_abs).replace(os.sep, "/")
        if is_exempt(fp_rel, fp_abs):
            continue

        # ─── 1. 项目级禁改区：与任务无关，任何状态都拦 ───
        if forb and path_matches(fp_rel, forb, []):
            print(
                f"REGRESS-GUARD: ⛔ 项目禁改区\n"
                f"  {fp_rel}{via}\n"
                f"  命中 .regress/config.json 的 boundary.forbidden（冻结区/遗留区）。\n\n"
                f"  禁改区与任务边界无关——它保护的是「不该再被碰」的代码。\n"
                f"  · 确有必要 → /regress:bypass <分钟>（限时赦免，赦后记债）\n"
                f"  · 冻结已解除 → 从 config 的 forbidden 列表移除（留痕于 git）",
                file=sys.stderr,
            )
            sys.exit(2)

        matched = [(mf, mid, status, appr)
                   for mf, patterns, exact, mid, status, appr in boundaries
                   if path_matches(fp_rel, patterns, exact)]
        if any(editable(status, appr) for _, _, status, appr in matched):
            continue  # 已批准（status 翻转 或 approved.at 产物直通）
        if matched:
            blocked_hits = [(mf, mid) for mf, mid, status, _ in matched
                            if status == "blocked"]
            if blocked_hits:
                # 命中受阻清单：受阻是合法的停止状态，编辑被拦直到解阻
                mf0, mid0 = blocked_hits[0]
                with open(mf0, encoding="utf-8") as f:
                    content = f.read()
                reason = block_value(content, "blocked", "reason") if "---" in content else ""
                need = block_value(content, "blocked", "need") if "---" in content else ""
                ids = ", ".join(mid or os.path.basename(mf) for mf, mid in blocked_hits[:3])
                extra = ""
                planning_ids = [mid or os.path.basename(mf)
                                for mf, mid, status, _ in matched if status == "planning"]
                if planning_ids:
                    extra = f"\n  （另有待批准清单：{', '.join(planning_ids[:3])}）"
                print(
                    f"REGRESS-GUARD: 🛑 任务受阻\n"
                    f"  {fp_rel}{via}\n"
                    f"  在受阻清单（{ids}）的边界内——受阻是合法停止，不是绕过的理由。\n\n"
                    f"  阻塞：{reason or '（读清单 blocked 块）'}\n"
                    f"  需要人类：{need or '（读清单 blocked.need）'}\n\n"
                    f"  · 把 need 转达给人类——这是受阻的出口，不是继续硬磨\n"
                    f"  · 阻塞解除 → python3 {APPROVE_SCRIPT} <清单> --unblock 后恢复编辑\n"
                    f"  · 认为不该受阻 → 在回复中说明理由，经人类同意后解阻"
                    f"{extra}",
                    file=sys.stderr,
                )
                sys.exit(2)
            # 只命中待批准（planning）清单：计划审批的机器强制——批准前拦编辑
            ids = ", ".join(mid or os.path.basename(mf) for mf, mid, _, _ in matched[:3])
            print(
                f"REGRESS-GUARD: ⏸ 计划待批准\n"
                f"  {fp_rel}{via}\n"
                f"  在清单（{ids}）的边界内，但该计划尚未获得人类批准（status: planning）。\n\n"
                f"  批准前只读探索，不动手——这是方向错误的最后低价纠偏点。\n"
                f"  · 人类回复「批准/开始/ok」→ python3 {APPROVE_SCRIPT} <清单> 完成转写\n"
                f"    （status→in-progress + approved 落产物 + 漂移检查 + 入地层）\n"
                f"  · 人类也可直接编辑清单填 approved.at（产物直通），守卫视同已批准\n"
                f"  · 计划需修改 → /regress:plan 继续对话完善（保持 planning）\n"
                f"  · 你认为不该等批准 → 在回复中说明理由，请人类显式批准",
                file=sys.stderr,
            )
            sys.exit(2)

        ids = ", ".join(b[3] or os.path.basename(b[0]) for b in boundaries[:3])
        print(
            f"REGRESS-GUARD: 🚧 开发边界拦截\n"
            f"  {fp_rel}{via}\n"
            f"  不在任何活跃清单（{ids}）的边界内。\n\n"
            f"  边界 = 计划的物理化：越界动作在发生前被拦截，而不是烧完 token 后被提醒。\n"
            f"  三条路（选一）：\n"
            f"  1. 这确实是本任务需要的 → /regress:track 把它回写 actual_changes"
            f"（边界随之扩展，扩界留痕）\n"
            f"  2. 这属于另一个任务 → 先收尾当前清单（status: done 解除边界），再开新清单\n"
            f"  3. 误锁 → .regress/config.json 设 \"boundary_enforced\": false 项目级关闭\n\n"
            f"  需要临时绕过：/regress:bypass <分钟>",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
