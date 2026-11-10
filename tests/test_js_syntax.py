"""JS 语法 ratchet（批216，公网 issue#6）。

标本：批215 在 index.js 块注释内写了「CLAUDE_*/ZCODE_*」——星号+斜杠相邻
二字符序列把注释提前闭合 → SyntaxError → dsh 插件 100% 拒载（外部用户发布
后 25 分钟抓回）。三道防线全漏：pytest 无 JS 语法面、安装器只验在位不验可载、
childEnv 探针用源码文本抽取恰好绕过整模块 import。

本 ratchet=node --check 全仓 .js（零依赖零配置恰够——缺陷类是纯语法；引
linter 换来依赖面与配置漂移，宁缺毋滥）。批206 Python subprocess 编码
ratchet 的 JS 等价物：新增 .js 语法坏当场红，不等人肉审计。"""
import glob
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node 不在 PATH")

# 仓内全部 JS 面：dsh 原生适配层 + ZCode launcher（发布/装机双通道都在册）
JS_GLOBS = ("deploy/dsh-native/**/*.js", "hooks/scripts/*.js")


def _repo_js_files():
    out = []
    for pat in JS_GLOBS:
        out += glob.glob(os.path.join(ROOT, pat), recursive=True)
    return sorted(out)


def test_repo_has_js_files():
    """守卫面非空——glob 路径漂移（目录改名/移动）当场红，防 ratchet 空转。"""
    files = _repo_js_files()
    assert len(files) >= 3, f"JS 面意外缩水：{files}"


def test_all_repo_js_parse():
    """全仓 .js 过 node --check——块注释提前闭合/括号失衡等当场红。

    注：--check 只验语法不验 import 解析（依赖缺失是安装器职责，
    见 test_install_dsh 装后自验与巡检 import 探针）。"""
    bad = []
    for f in _repo_js_files():
        r = subprocess.run([NODE, "--check", f], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            bad.append(f"{os.path.relpath(f, ROOT)}: {r.stderr.strip().splitlines()[0][:100]}")
    assert not bad, "JS 语法崩（issue#6 同族——块注释内禁星号斜杠相邻序列）：\n  " + "\n  ".join(bad)
