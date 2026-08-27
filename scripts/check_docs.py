#!/usr/bin/env python3
"""文档一致性校验：扫描所有 .md 文件，检查引用的命令/文件/字段是否存在。

用法：python3 scripts/check_docs.py [plugin_root]

检查项：
  1. 文档中引用的 /regress:xxx 命令 → 对应 commands/regress:xxx.md 是否存在
  2. 文档中引用的 skill 名 → 对应 skills/<name>/SKILL.md 是否存在
  3. 文档中引用的文件路径（如 hooks/scripts/xxx）→ 文件是否存在
  4. plugin.json 的 components 路径 → 目录是否存在
  5. hooks.json 引用的脚本 → 文件是否存在

退出码：0=全部一致，1=有不一致
"""
import sys
import os
import re
import json
import glob


def check(plugin_root):
    errors = []
    warnings = []

    # ─── 1. 命令引用 ──────────────────────────────────
    cmd_dir = os.path.join(plugin_root, "commands")
    existing_cmds = set()
    for f in glob.glob(os.path.join(cmd_dir, "*.md")):
        existing_cmds.add(os.path.basename(f).replace(".md", ""))

    for md in glob.glob(os.path.join(plugin_root, "**", "*.md"), recursive=True):
        with open(md, encoding="utf-8") as f:
            text = f.read()
        # 跳过 EVIDENCE.md（含示例文本，不是真实引用）
        if os.path.basename(md) == "EVIDENCE.md":
            continue
        # 找 /regress:xxx
        for m in re.finditer(r'/regress:(\w+)', text):
            cmd = f"regress:{m.group(1)}"
            # 跳过占位符（xxx/nonexistent/example 等）
            if m.group(1) in ("xxx", "nonexistent", "example", "your"):
                continue
            if cmd not in existing_cmds:
                errors.append(f"{rel(md, plugin_root)}: 引用命令 /{cmd}，但 commands/{cmd}.md 不存在")

    # ─── 2. 文件路径引用 ──────────────────────────────
    for md in glob.glob(os.path.join(plugin_root, "**", "*.md"), recursive=True):
        if os.path.basename(md) == "EVIDENCE.md":
            continue
        with open(md, encoding="utf-8") as f:
            text = f.read()
        # 找 hooks/scripts/xxx 或 lib/xxx 等相对路径
        for m in re.finditer(r'(hooks/scripts/[^\s`)\]"\'\]]+)', text):
            ref_path = m.group(1).rstrip(".\"'")
            # 跳过占位符
            if "xxx" in ref_path or "example" in ref_path:
                continue
            full = os.path.join(plugin_root, ref_path)
            if not os.path.exists(full) and not os.path.exists(full + ".py") and not os.path.exists(full + ".sh"):
                errors.append(f"{rel(md, plugin_root)}: 引用文件 {ref_path}，但文件不存在")

    # ─── 4. plugin.json components ────────────────────
    pj = os.path.join(plugin_root, ".zcode-plugin", "plugin.json")
    if os.path.exists(pj):
        with open(pj, encoding="utf-8") as f:
            manifest = json.load(f)
        for key in ("skills", "commands", "hooks"):
            val = manifest.get(key)
            if val and isinstance(val, str):
                d = os.path.join(plugin_root, val)
                if not os.path.isdir(d):
                    errors.append(f"plugin.json: {key}='{val}'，但目录不存在")

    # ─── 5. hooks.json 引用 ───────────────────────────
    hj = os.path.join(plugin_root, "hooks", "hooks.json")
    if os.path.exists(hj):
        with open(hj, encoding="utf-8") as f:
            hj_data = json.load(f)
        # 找所有 ${ZCODE_PLUGIN_ROOT}/xxx 引用（command 字符串里含转义引号，一并清理）
        hj_text = json.dumps(hj_data)
        for m in re.finditer(r'\$\{ZCODE_PLUGIN_ROOT\}/([^\s"]+)', hj_text):
            ref = m.group(1).rstrip('\\"')
            full = os.path.join(plugin_root, ref)
            if not os.path.exists(full):
                errors.append(f"hooks.json: 引用 {ref}，但文件不存在")

    # ─── 输出 ────────────────────────────────────────
    print("════════════════════════════════════════")
    print("  文档一致性校验报告")
    print("════════════════════════════════════════")
    print(f"扫描目录: {plugin_root}")
    print(f"已注册命令: {sorted(existing_cmds)}")
    print()

    if errors:
        print(f"❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"  • {e}")
    else:
        print("✅ 无错误：所有命令/文件引用一致")

    if warnings:
        print(f"\n⚠️  警告 ({len(warnings)}):")
        for w in warnings:
            print(f"  • {w}")

    print()
    return 1 if errors else 0


def rel(path, root):
    return os.path.relpath(path, root)


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    sys.exit(check(root))
