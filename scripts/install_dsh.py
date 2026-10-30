#!/usr/bin/env python3
"""dsh 桌面版安装轨道（批166，REGRESS-2026-164：special/dsh-desktop）。

把 regress-guard 挂上 DeepSeek dsh 桌面版（DeepSeek Harness）：
  1. 生成 CC 方言钩子清单 hooks.cc.json（ZCODE→CLAUDE 变量替换）入已装根
  2. 确保 @deepseek-ai/dsh-hooks-claude-code 桥包装入目标 profile
     （dsh plugin --profile <p> add …；已在位则跳过）
  3. profile 用户层 cordis.patch.yml 幂等插入桥配置条目
     （configPath=hooks.cc.json，pluginRoot=已装根；projectDir 省略=会话
     cwd——桥文档契约，项目目录随会话走）

接线先例=本机 dsh-advisor（本地插件同走用户 patch 层）。
幂等律：重复安装=无操作；--remove=精确移除本批条目（不动他人条目）；
--check=只诊断不动刀。退出码：0=成功/已在位，1=环境缺件（DSH_HOME/桥包
安装失败），2=用法错。
"""
import argparse
import json
import os
import subprocess
import sys

BRIDGE_PKG = "@deepseek-ai/dsh-hooks-claude-code"
PROTOCOL_PKG = "@deepseek-ai/dsh-hook-protocol"  # 桥的 peerDependency——宿主侧须显式装
PATCH_ENTRY_ID = "regress-guard-hooks"  # patch 层条目 id（幂等锚）

# matcher 双方言展宽（批166 侦察实证）：桥的 matcher 匹配宿主工具名——
# dsh 注册名是小写 bash/read/write/edit 另有 pwsh（dsh-tool-bash README:
# "registers the `bash` tool"；dsh-tool-fs：read/write/edit）；CC 系是
# Bash/Read/Write/Edit。载荷字段名两家一致（dsh-tool-fs README 明示
# snake_case 对齐 Claude Code——file_path/command 均同）。
MATCHER_WIDEN = {
    "Bash": "Bash|bash|pwsh",
    "Edit|Write|ApplyPatch": "Edit|Write|ApplyPatch|edit|write",
    "Bash|Edit|Write": "Bash|bash|pwsh|Edit|Write|edit|write",
    "Read": "Read|read",  # read_image 不计读（图像不授文本认知，文档留痕）
}

# patch 层语法（dsh schema $defs.includePatch 实证）：顶层条目须 id 定向
# 覆盖既有行或带 insert 列表追加新行——裸新条目会被 warned-and-skipped
# （"entry not found"，批166 活体标本）。insert 无 id=追加到根。
PATCH_ENTRY = """- insert:
  - id: {eid}
    name: "@deepseek-ai/dsh-hooks-claude-code"
    config:
      configPath: {config}
      pluginRoot: {root}
""".format


def _installed_root():
    """已装副本根（与 install.sh 同位）——桥的 pluginRoot/configPath 锚。"""
    return os.path.expanduser("~/.zcode/regress-guard-hooks")


def _hooks_cc_source():
    """源仓 hooks/hooks.json 原文（变量替换的原材料）。"""
    src = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "hooks", "hooks.json")
    with open(src, encoding="utf-8") as f:
        return f.read()


def generate_hooks_cc(root=None):
    """生成 hooks.cc.json（CC 方言 + dsh 工具名 matcher 展宽）。

    返回写入路径。内容先过 JSON 解析校验（坏替换=坏 JSON 会当场炸，不留
    半成品给桥在运行时拒载）。"""
    root = root or _installed_root()
    text = _hooks_cc_source()
    # 两处方言替换：①变量 ZCODE→CLAUDE（桥契约）；②布局源仓→已装摊平
    # （install.sh 把 hooks/scripts/* 拷到已装根——hooks/scripts/ 前缀须剥，
    # 否则钩子进程找不到文件、桥静默含错放行=批166 e2e 活体标本）。
    # 特例：self_heal.py 被 install.sh 搬进 lib/（注册位在 lib/，:98）
    text = text.replace("${ZCODE_PLUGIN_ROOT}/hooks/scripts/self_heal.py",
                        "${CLAUDE_PLUGIN_ROOT}/lib/self_heal.py")
    text = text.replace("${ZCODE_PLUGIN_ROOT}/hooks/scripts/",
                        "${CLAUDE_PLUGIN_ROOT}/")
    text = text.replace("${ZCODE_PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}")
    data = json.loads(text)  # 校验位：替换后必须仍是合法清单
    for _event, groups in data.get("hooks", {}).items():
        for g in groups:
            m = g.get("matcher")
            if m in MATCHER_WIDEN:
                g["matcher"] = MATCHER_WIDEN[m]
    # 批167（dsh 100%）：PostToolUseFailure 无桥点——fail_watch 复挂到
    # PostToolUse 自筛失败（fail_watch.main 的 tool_response 启发式）。
    # 只搬 fail_watch（观察谁在买保险）；plan_bridge 的 ExitPlanMove 无
    # dsh 对应（宿主无计划模式）不搬。
    ptu = data["hooks"].setdefault("PostToolUse", [])
    for g in data.get("hooks", {}).get("PostToolUseFailure", []):
        for h in g.get("hooks", []):
            if "fail_watch" in h.get("command", ""):
                ptu.append({"matcher": g.get("matcher", ""),
                            "hooks": [dict(h)]})
    dest = os.path.join(root, "hooks.cc.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dest)
    return dest


def _profile_patch_path(dsh_home, profile):
    return os.path.join(dsh_home, "profiles", profile, "cordis.patch.yml")


def patch_entry_present(text, eid=PATCH_ENTRY_ID):
    return f"id: {eid}\n" in text


def install_patch_entry(dsh_home, profile, root=None, config_path=None):
    """用户 patch 层幂等插入桥条目。返回 (changed, path)。"""
    root = root or _installed_root()
    config_path = config_path or os.path.join(root, "hooks.cc.json")
    p = _profile_patch_path(dsh_home, profile)
    text = open(p, encoding="utf-8").read() if os.path.exists(p) else "[]\n"
    if patch_entry_present(text):
        return False, p
    entry = PATCH_ENTRY(eid=PATCH_ENTRY_ID, config=config_path, root=root)
    with open(p, "a", encoding="utf-8") as f:
        if not text.endswith("\n"):
            f.write("\n")
        f.write(entry)
    return True, p


def remove_patch_entry(dsh_home, profile):
    """精确移除本批 insert 条目（'- insert:' 行到下一顶格 '- ' 前，含尾）。"""
    p = _profile_patch_path(dsh_home, profile)
    if not os.path.exists(p):
        return False, p
    lines = open(p, encoding="utf-8").readlines()
    out, i, removed = [], 0, False
    while i < len(lines):
        if lines[i].startswith("- insert:") and i + 1 < len(lines) \
                and f"id: {PATCH_ENTRY_ID}" in lines[i + 1]:
            removed = True
            i += 2
            while i < len(lines) and not lines[i].startswith("- "):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if removed:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(out)
        os.replace(tmp, p)
    return removed, p


def _dsh_version(dsh_bin="dsh"):
    r = subprocess.run([dsh_bin, "-V"], capture_output=True, text=True, timeout=30)
    return (r.stdout or r.stderr).strip()


def _pkg_installed(home, profile, pkg, version=None):
    """实体在位判定：node_modules 里真有包（lock 字符串会被 peerDependency
    声明行误中=批166 假绿活体——桥 peer 声明让 lock 检查恒真）。
    批168：给 version 则须版本精确配对——存在≠正确（web 桥 0.0.1 滞留而
    检查恒过的活体：首装钉死 package.json 版本号，后续 add 同名新版本被
    存在性检查短路）。"""
    pj = os.path.join(home, "profiles", profile, "node_modules", pkg,
                      "package.json")
    if not os.path.isfile(pj):
        return False
    if version is None:
        return True
    try:
        with open(pj, encoding="utf-8") as f:
            import json as _json
            return _json.load(f).get("version") == version
    except (OSError, ValueError):
        return False


def ensure_bridge_pkg(profile, dsh_bin="dsh", home=None):
    """桥+其 peer（protocol）装入 profile workspace——**版本配对 dsh 运行时**。

    批166 e2e 活体标本三连：①裸 add 解析到旧线 0.0.1-rc（与运行时 API 错配
    ——session.events 不可迭代，所有 bash 调用恒错）；②桥把 protocol 声明
    为 peerDependency，宿主不装则桥 import 失败=静默含错放行；③rc 版须
    allow-version 显式接受。故：钉桥@dsh版本 + 先 allow 后装 + peer 同装。
    在位判定走 lock（含两包名才免装）。失败返回 (False, stderr 摘要)。"""
    home = home or os.path.expanduser("~/.dsh")
    ver = None
    try:
        ver = _dsh_version(dsh_bin)
    except Exception:
        ver = None
    if _pkg_installed(home, profile, BRIDGE_PKG, ver) and \
            _pkg_installed(home, profile, PROTOCOL_PKG, ver):
        return True, "已在位（node_modules 实体双包" + (
            f"，版本配对 {ver}" if ver else "") + "）"
    if not ver:
        return False, "无 dsh 可执行——无法确定版本配对目标"
    for act in ("allow", "add"):
        for pkg in (BRIDGE_PKG, PROTOCOL_PKG):
            if act == "add" and _pkg_installed(home, profile, pkg, ver):
                continue
            args = [dsh_bin, "plugin", "--profile", profile]
            if act == "allow":
                args += ["allow-version", f"{pkg}@{ver}",
                         "--dsh-version", ver, "--accept-risk"]
            else:
                args += ["add", f"{pkg}@{ver}"]
            r = subprocess.run(args, capture_output=True, text=True, timeout=600)
            if r.returncode != 0 and act == "add":
                return False, (r.stderr or r.stdout)[-300:]
    return True, f"已安装（版本配对 {ver}）"


def main():
    ap = argparse.ArgumentParser(
        description="regress-guard → dsh 桌面版安装轨道（批166）")
    ap.add_argument("--profile", default="web",
                    help="目标 profile（默认 web=桌面版运行形态）")
    ap.add_argument("--dsh-home", default="~/.dsh")
    ap.add_argument("--remove", action="store_true",
                    help="移除本批接线（不动他人条目）")
    ap.add_argument("--check", action="store_true",
                    help="只诊断不动刀")
    args = ap.parse_args()
    dsh_home = os.path.expanduser(args.dsh_home)

    if not os.path.isdir(dsh_home):
        print(f"install_dsh: 无 {dsh_home}——本机未装 dsh，无需接入", file=sys.stderr)
        return 1
    profile_dir = os.path.join(dsh_home, "profiles", args.profile)
    if not os.path.isdir(profile_dir):
        print(f"install_dsh: profile {args.profile} 不存在（有："
              + ", ".join(os.listdir(os.path.join(dsh_home, 'profiles')))
              + "）", file=sys.stderr)
        return 2

    if args.remove:
        removed, p = remove_patch_entry(dsh_home, args.profile)
        print(f"{'已移除' if removed else '本无'}条目：{p}")
        return 0

    root = _installed_root()
    cc = generate_hooks_cc(root)
    print(f"hooks.cc.json 已生成：{cc}")
    patch = _profile_patch_path(dsh_home, args.profile)
    present = (os.path.exists(patch)
               and patch_entry_present(open(patch, encoding="utf-8").read()))
    try:
        _ver = _dsh_version("dsh")
    except Exception:
        _ver = None
    pkg_ok = (_pkg_installed(dsh_home, args.profile, BRIDGE_PKG, _ver)
              and _pkg_installed(dsh_home, args.profile, PROTOCOL_PKG, _ver))

    if args.check:
        print(f"桥+protocol：{'在位' if pkg_ok else '缺'} | patch 条目："
              f"{'在位' if present else '缺'} | hooks.cc.json：在位")
        return 0 if (pkg_ok and present) else 1

    if not pkg_ok:
        ok, msg = ensure_bridge_pkg(args.profile, home=dsh_home)
        print(f"桥包：{msg}")
        if not ok:
            print(f"install_dsh: 桥包安装失败——{msg}", file=sys.stderr)
            return 1
    changed, p = install_patch_entry(dsh_home, args.profile, root)
    print(f"patch 条目：{'已插入' if changed else '已在位'}（{p}）")
    print("完成：dsh 桌面版下次启动会话即载 regress-guard 钩子"
          "（PreToolUse 门禁/边界/先读后改…）；卸载 --remove")
    return 0


if __name__ == "__main__":
    sys.exit(main())
