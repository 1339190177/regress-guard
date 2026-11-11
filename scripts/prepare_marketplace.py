#!/usr/bin/env python3
"""官方市场提交包蒸馏（v1.88.0，099；批224 白名单制）。

生成 dist/plugins/regress-guard/——市场契约要求插件目录逐字上 CDN，故只带
点名产物面；同时产出市场条目 JSON（写入对方根 marketplace.json 用）。

批224 黑名单→白名单：黑名单对新目录默认放行——.mypy_cache/.ruff_cache
（79 件开发缓存）与 .zcode/plans（会话残留）曾静默泄入载荷，靠对方仓
gitignore 偶然拦住（2026-11-11 PR#34 同步实证）。白名单失败模式反转为
**显式少带**（缺件自检红/对方沙箱红），新目录默认不进载荷。契约基线=
旧 PR#34 已被 validate 接受的产物面 + 合法新增（install.py Python 化更名/
install_dsh.py 双宿主轨/check_docs.py 装机依赖）。
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "plugins", "regress-guard")

# ── 白名单产物面（批224）——增删件须同步契约测试 ──
WHITELIST_ROOT_FILES = (
    "LICENSE", "README.md", "README_CN.md", "install.py", "install.sh",
    "uninstall.py", "requirements-dev.txt",
)
WHITELIST_DIRS = (".zcode-plugin", "benchmarks", "commands", "docs",
                  "hooks", "templates")
WHITELIST_SCRIPTS = (
    "cache_experiment.py", "check_docs.py", "clean_env_check.sh",
    "critic_pass.py", "health_probe.py", "heldout_gate.py",
    "install_dsh.py", "install_dogfood.sh", "post_install_check.py",
    "replay_experiment.py",
)
# 白名单目录递归时的缓存修剪（子层也可能长缓存/残留）
_PRUNE_DIRS = ("__pycache__", ".git", ".pytest_cache", ".mypy_cache",
               ".ruff_cache", ".zcode")


def build():
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST, exist_ok=True)
    n = 0
    for name in WHITELIST_ROOT_FILES:
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            print(f"自检失败：白名单根件缺失 {name}", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(src, os.path.join(DIST, name))
        n += 1
    for d in WHITELIST_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, d)):
            dirnames[:] = [x for x in dirnames if x not in _PRUNE_DIRS]
            rel_dir = os.path.relpath(dirpath, ROOT)
            for fn in sorted(filenames):
                if fn.endswith(".pyc") or fn == ".DS_Store":
                    continue
                dst = os.path.join(DIST, rel_dir, fn)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(dirpath, fn), dst)
                n += 1
    for fn in WHITELIST_SCRIPTS:
        src = os.path.join(ROOT, "scripts", fn)
        if not os.path.isfile(src):
            print(f"自检失败：白名单 scripts 件缺失 {fn}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(os.path.join(DIST, "scripts"), exist_ok=True)
        shutil.copy2(src, os.path.join(DIST, "scripts", fn))
        n += 1
    print(f"dist 就绪：{n} 文件 -> {DIST}")
    return n


def build_pr_payload(out_root):
    """批137：官方市场 PR 载荷一键蒸馏——external_plugins/regress-guard 形态。

    取代手工全树拼装（run14/run49 的 134 文件 payload 混入 tests/deploy/
    publish.py 等 dev 件——官方 CONTRIBUTING 禁 caches/dev 工具外泄）。"""
    build()
    dst = os.path.join(out_root, "external_plugins", "regress-guard")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(DIST, dst)
    n = sum(len(fs) for _, _, fs in os.walk(dst))
    print(f"PR 载荷就绪：{n} 文件 -> {dst}")
    return n


def entry():
    """市场条目（写进对方根 marketplace.json 的 plugins 数组）。"""
    m = json.load(open(os.path.join(ROOT, ".zcode-plugin", "plugin.json"),
                       encoding="utf-8"))
    return {
        "name": m["name"],
        "source": "./external_plugins/regress-guard",
        "description": m["description"],
        "description_i18n": m["description_i18n"],
        "version": m["version"],
        "author": m["author"],
        "category": m.get("category", "developer-tools"),
        "keywords": m.get("keywords", []),
    }


def post_check(n):
    """批224 自检三处：缓存/dev 零容忍 + 必备子集 + 数量带（显式少带=红）。"""
    bad_dirs = [d for d in _PRUNE_DIRS + ("tests", "deploy", "dist", ".github")
                if os.path.exists(os.path.join(DIST, d))]
    bad_scripts = [s for s in ("publish.py", "gen_reference.py",
                               "prepare_marketplace.py")
                   if os.path.exists(os.path.join(DIST, "scripts", s))]
    if bad_dirs or bad_scripts:
        print(f"自检失败：缓存/开发面泄漏 dirs={bad_dirs} scripts={bad_scripts}",
              file=sys.stderr)
        sys.exit(1)
    need = ["install.py", "uninstall.py", "install.sh", "requirements-dev.txt",
            "hooks/hooks.json", ".zcode-plugin/plugin.json", "scripts/post_install_check.py",
            "scripts/install_dsh.py", "scripts/check_docs.py"]
    missing = [p for p in need if not os.path.exists(os.path.join(DIST, p))]
    ncmds = len([f for f in os.listdir(os.path.join(DIST, "commands"))
                 if f.endswith(".md")])
    ntpl = len([f for f in os.listdir(os.path.join(DIST, "templates"))])
    if missing or ncmds < 16 or ntpl < 5:
        print(f"自检失败：必备子集缺 {missing} 或命令数 {ncmds}/模板数 {ntpl} 异常",
              file=sys.stderr)
        sys.exit(1)
    if not (60 <= n <= 200):
        print(f"自检失败：文件数量带越界 {n}", file=sys.stderr)
        sys.exit(1)
    print(f"自检过：零泄漏，必备子集全在（{ncmds} 命令/{ntpl} 模板），文件数 {n}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--pr-payload":
        n = build_pr_payload(sys.argv[2])
        post_check(n)
        sys.exit(0)
    n = build()
    e = entry()
    out = os.path.join(ROOT, "dist", "marketplace-entry.json")
    json.dump(e, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(out, "a", encoding="utf-8").write("\n")
    print("市场条目：", json.dumps(e, ensure_ascii=False)[:160], "...")
    post_check(n)
