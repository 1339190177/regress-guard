#!/usr/bin/env python3
"""pre_commit_guard.py — regress-guard PreToolUse hook（跨平台纯 Python 版）。

取代 pre_commit_guard.sh。用 type:"process" 的 hook 直接调用，无需 shell。

校验顺序（短路）：
  1. stdin 解析：是否 git commit？否则 exit 0
  2. 有 .regress/？否则 exit 0
  3. bypass 有效？记日志 + exit 0
  4. staged 文件都在清单内？否则 exit 2
  5. 自己跑测试：pass→exit0+标done / fail→exit2 / skip→降级检查status

退出码：0=放行，2=阻断
"""
import sys
import os
import re
import json
import getpass
import traceback
from datetime import datetime

# ─── 定位 lib 目录（兼容被 process hook 调用时的各种 CWD）─────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from manifest_parser import find_active_manifest, get_all_changed_files, get_manifest_status, update_frontmatter, get_fragile_points  # noqa: E402
from git_diff_analyzer import get_staged_files, filter_files, find_untracked_changes  # noqa: E402
from test_runner import run_tests  # noqa: E402
from history import record  # noqa: E402


def emit_pass():
    sys.exit(0)

def emit_block(msg):
    print(f"REGRESS-GUARD: {msg}", file=sys.stderr)
    sys.exit(2)

def emit_warn(msg):
    print(f"REGRESS-GUARD (warning): {msg}", file=sys.stderr)
    sys.exit(0)


def is_git_commit(tool_input_str):
    """从 hook 的 stdin JSON 判断是否提交类命令。

    覆盖：git commit, git ci, npm version（会触发 commit）,
          pnpm/pnpm publish, yarn version, cz (commitizen),
          husky pre-commit 执行链。
    """
    if not tool_input_str:
        return False
    try:
        data = json.loads(tool_input_str)
        ti = data.get("tool_input", data) if isinstance(data, dict) else {}
        cmd = ti.get("command", "") if isinstance(ti, dict) else ""
        # git commit / git ci
        if re.search(r'\bgit\s+commit\b|\bgit\s+ci\b', cmd):
            return True
        # npm version / npm publish（npm version 会自动 commit）
        if re.search(r'\bnpm\s+(version|publish)\b', cmd):
            return True
        # pnpm publish / yarn version
        if re.search(r'\b(pnpm|yarn)\s+(publish|version)\b', cmd):
            return True
        # commitizen (cz)
        if re.search(r'\bcz\b|\bgit-cz\b', cmd):
            return True
        # husky run hook
        if re.search(r'\bhusky\s+run\b', cmd):
            return True
        return False
    except Exception:
        return False


def find_regress_dir():
    """从多个来源查找 .regress/ 目录。

    查找顺序：
    1. CLAUDE_PROJECT_DIR / ZCODE_PROJECT_DIR（ZCode 传入的工作目录）
    2. git rev-parse --show-toplevel（当前 git 仓库根）→ 看它有没有 .regress/
    3. 从 git root 向上逐级查找（支持 monorepo：.regress/ 在父目录）
    4. 当前工作目录
    """
    # 收集候选目录
    candidates = []
    env_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("ZCODE_PROJECT_DIR")
    )
    if env_dir:
        candidates.append(env_dir)
    candidates.append(os.getcwd())

    # 从 git 获取仓库根
    try:
        import subprocess
        git_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if git_root:
            candidates.append(git_root)
            # 向上查找（monorepo 场景：.regress/ 在父目录）
            parent = os.path.dirname(git_root)
            while parent and parent != "/":
                candidates.append(parent)
                parent = os.path.dirname(parent)
    except Exception:
        pass

    # 找第一个有 .regress/ 的
    for d in candidates:
        regress_dir = os.path.join(d, ".regress")
        if os.path.isdir(regress_dir):
            return d, regress_dir

    return None, None


def _mark_expected(regress_dir, kind):
    """放行前写标记，供 git 观测钩子区分提交来源（gated/bypass vs 外部直提）。

    观测钩子消费新鲜标记（<5min）后删除；过期标记视为残留，忽略。
    """
    try:
        with open(os.path.join(regress_dir, ".expect-commit"), "w", encoding="utf-8") as f:
            f.write(f"kind={kind}\n")
    except OSError:
        pass


def _git_head_sha():
    """获取当前 HEAD sha（证据链的产出锚点：本次 commit 基于哪个提交）。"""
    try:
        import subprocess
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()[:12]
    except Exception:
        return ""


def main():
    # ─── 1. 是否 git commit？──────────────────────────
    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not is_git_commit(raw_input):
        emit_pass()

    # ─── 2. 定位项目 + .regress/ ──────────────────────
    project_dir, regress_dir = find_regress_dir()
    if not regress_dir:
        emit_pass()  # 未接入的项目（找不到 .regress/）

    # 读配置 — fail-safe：config 损坏时用最严格默认（阻断）
    config = {}
    config_file = os.path.join(regress_dir, "config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # 配置文件损坏 → 不能猜配置，fail-safe 阻断
            record(regress_dir, "error", error=f"config.json parse failed: {e}")
            emit_block(
                f".regress/config.json 解析失败：{e}\n\n"
                "配置文件损坏，无法确定 strict/bypass 状态。\n"
                "fail-safe 原则：阻断 commit。请修复 config.json 后重试。"
            )
    strict = config.get("strict", True)
    bypass_until = config.get("bypass_until", "")

    # ─── 3. 检查 bypass ───────────────────────────────
    if bypass_until:
        try:
            expired = datetime.now() >= datetime.fromisoformat(bypass_until)
        except (ValueError, TypeError):
            expired = True  # 格式坏 = 过期

        if not expired:
            # bypass 有效 → 记审计日志 + 放行
            log_path = os.path.join(regress_dir, "bypass.log")
            user = getpass.getuser() if hasattr(getpass, "getuser") else os.environ.get("USER", "unknown")
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat()} | bypass commit by {user}\n")
            except OSError:
                pass  # 日志写失败不影响放行（bypass 日志是审计辅助，非关键路径）
            record(regress_dir, "bypass_used", "", expires=bypass_until, user=user)
            _mark_expected(regress_dir, "bypass")
            emit_warn(f"bypass 模式生效（到期: {bypass_until}），已记审计日志。事后请补回归。")
        else:
            # 过期 → 清除 bypass_until
            config.pop("bypass_until", None)
            try:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
            except OSError:
                pass  # 清除失败不阻断（下次会再试清除）

    # ─── 4. 查找活跃清单 ──────────────────────────────
    # fail-safe：如果 manifest 文件存在但解析失败 → 阻断（而非放行）
    manifests_dir = os.path.join(regress_dir, "manifests")
    manifest_files_on_disk = sorted(
        __import__("glob").glob(os.path.join(manifests_dir, "*.md")), reverse=True
    ) if os.path.isdir(manifests_dir) else []

    manifest = None
    manifest_id = ""
    for mf_path in manifest_files_on_disk:
        mdata = get_all_changed_files(mf_path)  # 触发解析
        # 如果文件能解析（即使返回空列表），parse_frontmatter 不为 None
        from manifest_parser import parse_frontmatter
        parsed = parse_frontmatter(mf_path)
        if parsed is None:
            # 文件存在但无法解析 frontmatter → 格式损坏
            record(regress_dir, "error", error=f"manifest parse failed: {mf_path}")
            emit_block(
                f"回归清单解析失败：{mf_path}\n\n"
                "该文件不是合法的 YAML frontmatter 格式（缺少 --- 包裹或 YAML 语法错误）。\n"
                "fail-safe 原则：阻断 commit。请修复清单格式后重试。"
            )
        # 语义反转：只有明确活跃 status 才算（开放词表下自造词≠活跃）
        if parsed.get("status") in ("planning", "in-progress", "verifying", "blocked"):
            manifest = mf_path
            manifest_id = parsed.get("id", "")
            break

    if not manifest:
        # 没有活跃清单 → 放行，但要记录（否则 history 永远空）
        record(regress_dir, "commit_passed", "",
               runner="none", passed=0, total=0,
               note="no_active_manifest")
        _mark_expected(regress_dir, "gated")
        emit_pass()

    # ─── 5. staged 文件在清单内？──────────────────────
    try:
        manifest_files = get_all_changed_files(manifest)
        # .regress/ 是治理数据（清单/历史/考古地层），不是业务改动，不参与 F3 检查
        staged = [s for s in filter_files(get_staged_files(project_dir))
                  if not s.replace(os.sep, "/").startswith(".regress/")]
        untracked = find_untracked_changes(staged, manifest_files)
    except Exception as e:
        record(regress_dir, "error", manifest_id, error=f"diff analysis failed: {e}")
        emit_block(
            f"git diff 分析失败：{e}\n\n"
            "fail-safe 原则：阻断 commit。请检查 git 状态后重试。"
        )

    if untracked:
        files_str = "\n  ".join(untracked)
        msg = f"commit 被阻断。以下 staged 文件不在回归清单中：\n  {files_str}\n\n请先运行 /regress:track 回写，或 git reset 撤销。\n清单：{manifest}"
        record(regress_dir, "commit_blocked", manifest_id,
               reason="untracked_files", untracked_files=untracked)
        if strict:
            emit_block(msg)
        else:
            emit_warn(msg)

    # ─── 5.5 脆弱点挂牌检查（公理一：未挂牌的脆弱点才是真正的未知风险）──
    fps = get_fragile_points(manifest)
    open_fps = [fp for fp in fps if str(fp.get("status", "open")).lower() == "open"]
    flagged_fps = [fp for fp in fps if str(fp.get("status", "")).lower() == "flagged"]
    if open_fps:
        lines = "\n  ".join(
            f"{fp.get('id', '?')} [{fp.get('kind', '?')}] {fp.get('description', '')}"
            for fp in open_fps
        )
        msg = (
            f"commit 被阻断。清单有 {len(open_fps)} 个脆弱点未挂牌（status: open）：\n"
            f"  {lines}\n\n"
            "公理一：成功不是跑通，而是所有已知脆弱点被锁死或显式挂牌。\n"
            "每个脆弱点二选一后回写清单：\n"
            "  - locked：verify 命令实测通过（跑 /regress:verify 或手动执行后回写）\n"
            "  - flagged：显式带病挂牌（description 里写明知悉的原因）"
        )
        record(regress_dir, "commit_blocked", manifest_id,
               reason="fragile_point_open",
               fragile_ids=[fp.get("id", "?") for fp in open_fps])
        if strict:
            emit_block(msg)
        else:
            emit_warn(msg)
    elif flagged_fps:
        # 带病挂牌 = 显式知情，放行但留痕（不刷屏，stderr 一行）
        print(
            f"REGRESS-GUARD: ⚠️ {len(flagged_fps)} 个脆弱点带病挂牌（flagged）随本提交入库："
            + ", ".join(fp.get("id", "?") for fp in flagged_fps),
            file=sys.stderr,
        )

    # ─── 5.6 证据律复验（公理一：locked = verify 现在能过，不是曾经能过）──
    #      locked 是唯一宣称"已锁死"的状态——门禁处机器复跑 verify 命令，
    #      AI 自封的 locked 不算数。无 verify 命令的 locked = 证据链缺环（警告）。
    #      感官分支（v1.19 AVS 公理三）：verify 以 human_check: 开头的 locked 条目，
    #      机器验证"人确认过"这个事实的化石存在——不复跑感官（人只是传感器，
    #      传感器读数入档即证据）。
    import subprocess as _sp
    locked_no_verify = [
        fp for fp in fps
        if str(fp.get("status", "")).lower() == "locked" and not str(fp.get("verify") or "").strip().strip('"')
    ]
    for fp in locked_no_verify:
        print(
            f"REGRESS-GUARD: ⚠️ {fp.get('id', '?')} 自称 locked 但无 verify 命令——"
            f"证据链缺环，建议补命令（/regress:verify 拿证据）或改 flagged 显式挂牌",
            file=sys.stderr,
        )
    verify_failed = []

    # 感官分支：human_check 化石存在性检查
    human_fps = [f for f in fps
                 if str(f.get("status", "")).lower() == "locked"
                 and str(f.get("verify") or "").strip().startswith("human_check")]
    if human_fps:
        jevents = []
        try:
            with open(os.path.join(regress_dir, "journal", "events.jsonl"),
                      encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            jevents.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except (IOError, OSError):
            pass
        for fp in human_fps:
            vid = fp.get("id", "?")
            has = any(e.get("kind") == "human_check"
                      and e.get("manifest_id") == manifest_id
                      and e.get("vid") == vid for e in jevents)
            record(regress_dir, "fragile_verify", manifest_id, vid=vid, ok=has)
            if not has:
                verify_failed.append(
                    (vid, "human_check", "无 human_check 化石（人工确认未落产物）："
                     f'journal.py . add human_check \'{{"manifest_id":"{manifest_id}","vid":"{vid}","result":"pass"}}\''))

    for fp in [f for f in fps
               if str(f.get("status", "")).lower() == "locked"
               and str(f.get("verify") or "").strip().strip('"')
               and not str(f.get("verify") or "").strip().startswith("human_check")][:5]:  # 上限5条防门禁拖延
        vcmd = str(fp["verify"]).strip()
        try:
            r = _sp.run(["bash", "-c", vcmd], capture_output=True, text=True,
                        timeout=15, cwd=project_dir)
            ok = r.returncode == 0
            tail = (r.stderr or r.stdout or "")[-150:].strip()
        except Exception as e:
            ok, tail = False, str(e)[:150]
        record(regress_dir, "fragile_verify", manifest_id,
               vid=fp.get("id", "?"), ok=ok)
        if not ok:
            verify_failed.append((fp.get("id", "?"), vcmd[:60], tail))
    if verify_failed:
        lines = "\n  ".join(
            f"{vid}: `{cmd}` → {tail or 'exit≠0（无输出）'}"
            for vid, cmd, tail in verify_failed
        )
        msg = (
            f"commit 被阻断。{len(verify_failed)} 个 locked 脆弱点门禁复验失败"
            f"（证据律：locked 意为 verify 此刻能过）：\n  {lines}\n\n"
            "修复后重试，或降级为 flagged 显式带病挂牌（写明知悉原因）。"
        )
        record(regress_dir, "commit_blocked", manifest_id,
               reason="fragile_verify_failed",
               failed_ids=[vid for vid, _, _ in verify_failed])
        if strict:
            emit_block(msg)
        else:
            emit_warn(msg)

    # ─── 6. hook 自己跑测试 ───────────────────────────
    print("REGRESS-GUARD: 正在运行测试...", file=sys.stderr)
    try:
        result = run_tests(project_dir)
    except Exception as e:
        record(regress_dir, "error", manifest_id, error=f"test_runner crashed: {e}")
        emit_block(
            f"测试运行器异常崩溃：{e}\n\n"
            "fail-safe 原则：阻断 commit。请检查测试运行器配置。\n"
            f"Traceback:\n{traceback.format_exc()[-500:]}"
        )
    status = result.get("status", "fail")
    runner = result.get("runner", "unknown")

    if status == "pass":
        passed = f"{result['passed']}/{result['total']}"
        try:
            update_frontmatter(manifest, {
                "status": "done",
                "test_verified_by": "hook",
                "test_result": f"{passed} passed",
            })
        except Exception as e:
            # 写清单失败不阻断（测试已通过，清单写入是辅助记录）
            print(f"REGRESS-GUARD: ⚠️ 清单更新失败（不影响放行）: {e}", file=sys.stderr)
        record(regress_dir, "commit_passed", manifest_id,
               runner=runner, passed=result.get("passed"), total=result.get("total"),
               base_head=_git_head_sha(), coverage_pct=result.get("coverage_pct"))
        cov_note = f"，覆盖率 {result['coverage_pct']}%" if result.get("coverage_pct") is not None else ""
        print(f"REGRESS-GUARD: ✅ 测试通过 ({passed}){cov_note}，清单已标记 done", file=sys.stderr)
        _mark_expected(regress_dir, "gated")
        emit_pass()

    elif status == "skip":
        # 无测试运行器 → 活跃清单存在但缺 runner：这仍需人工确认，阻断
        mstatus = get_manifest_status(manifest)
        # 注：能走到这里说明清单是明确活跃的（planning/in-progress/verifying），
        # 否则 main() 早就以 no_active_manifest 放行了
        record(regress_dir, "commit_blocked", manifest_id,
               reason="no_test_runner", runner=runner, manifest_status=mstatus)
        # 非终态 → 记录阻断事件 + 提示
        record(regress_dir, "commit_blocked", manifest_id,
               reason="no_test_runner", runner=runner, manifest_status=mstatus)
        msg = (
            f"未检测到测试运行器（{runner}），无法自动验证测试。\n"
            f"清单状态为 {mstatus}（需改为 done/completed 才能放行）。\n\n"
            "解决方法：\n"
            "  - Java 项目：确保 mvn 在 PATH（brew install maven / apt install maven）\n"
            "  - Node 项目：npm i -D jest\n"
            "  - Python 项目：pip install pytest\n"
            "  - 或在清单中标记 status: done（手动确认无需测试）"
        )
        if strict:
            emit_block(msg)
        else:
            emit_warn(msg)

    else:
        # 测试失败 → 阻断
        failures = result.get("failures", [])[:5]
        lines = []
        for f in failures:
            lines.append(f"  ❌ {f.get('test', '?')}")
            if f.get("message"):
                lines.append(f"     {f['message'][:120]}")
        lines.append(f"\n  共 {result.get('failed', 0)} 个失败 / {result.get('passed', 0)} 个通过")
        fail_str = "\n".join(lines) if lines else "  (详情见测试输出)"
        # 记录每个失败用例
        for f in failures:
            record(regress_dir, "test_failed", manifest_id,
                   runner=runner, test_name=f.get("test", "?"))
        record(regress_dir, "commit_blocked", manifest_id,
               reason="test_failed", runner=runner,
               failed=result.get("failed", 0), passed=result.get("passed", 0))
        emit_block(
            f"commit 被阻断。测试未通过（runner: {runner}）：\n\n{fail_str}\n\n"
            "请修复失败用例后重新 commit。测试通过后 hook 会自动放行。"
        )

    emit_pass()


if __name__ == "__main__":
    main()
