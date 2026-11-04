"""launcher.js 泛化契约（批191，v2.8.0 Windows 兼容）。

钩子全路由 node launcher.js <script> [args] 后，launcher 承担三契：
  1. 参数分发：argv[2]=目标脚本，余参透传；无参默认 pre_commit_guard.py
  2. 布局自愈：__dirname/<s> 不存在回退 __dirname/lib/<s>（摊平态/self_heal）
  3. env 双策略：门禁白名单原样；其余脚本清洗 PYTHON* + 注入 PYTHONUTF8=1
     （等价原 python3 -E 防投毒 + cp936 根治）
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCHER = os.path.join(ROOT, "hooks", "scripts", "launcher.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="本机无 node")

TARGET_BODY = (
    "import sys, json, os\n"
    "print(json.dumps({'argv': sys.argv[1:],\n"
    "                  'utf8': os.environ.get('PYTHONUTF8'),\n"
    "                  'pypath': os.environ.get('PYTHONPATH'),\n"
    "                  'zproj': os.environ.get('ZCODE_PROJECT_DIR'),\n"
    "                  'journal': os.environ.get('REGRESS_JOURNAL')}))\n"
)


def _mk_layout(tmp_path, target_name="target.py", in_lib=False):
    d = tmp_path / "lay"
    d.mkdir()
    shutil.copy2(LAUNCHER, d / "launcher.js")
    tgt_dir = d / "lib" if in_lib else d
    if in_lib:
        tgt_dir.mkdir()
    (tgt_dir / target_name).write_text(TARGET_BODY, encoding="utf-8")
    return d


def _run(d, *args, extra_env=None):
    env = {**os.environ, "ZCODE_PROJECT_DIR": "/tmp/proj",
           "REGRESS_JOURNAL": "on", "PYTHONPATH": "/poison",
           **(extra_env or {})}
    return subprocess.run([NODE, str(d / "launcher.js"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=env)


def test_dispatch_args_passthrough(tmp_path):
    """argv[2]=脚本名，余参原样透传给目标。"""
    d = _mk_layout(tmp_path)
    r = _run(d, "target.py", "hello", "world")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["argv"] == ["hello", "world"]


def test_layout_selfheal_lib_fallback(tmp_path):
    """摊平态特例：目标只在 lib/ 下也能解析（self_heal 布局）。"""
    d = _mk_layout(tmp_path, in_lib=True)
    r = _run(d, "target.py")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["argv"] == []


def test_default_target_is_commit_guard(tmp_path):
    """无参默认 pre_commit_guard.py（向后兼容既有已装配置/dsh 桥）。

    布局里没有该文件 → 子进程 python 打不开文件退出 2（fail-closed 方向），
    且不无限重试解释器。"""
    d = _mk_layout(tmp_path)  # 只有 target.py
    (d / "target.py").unlink()
    r = _run(d)
    assert r.returncode == 2, f"缺目标应 exit 2，得 {r.returncode}: {r.stderr}"


def test_env_policy_non_guard_scrubs_python_and_sets_utf8(tmp_path):
    """非门禁脚本：PYTHON* 清洗（=原 -E 防投毒）+ PYTHONUTF8=1（cp936 根治）。"""
    d = _mk_layout(tmp_path)
    r = _run(d, "target.py")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["pypath"] is None, "PYTHONPATH 投毒未清洗（-E 语义回归）"
    assert out["utf8"] == "1", "PYTHONUTF8 未注入"
    assert out["zproj"] == "/tmp/proj", "宿主契约变量被误清洗"


def test_env_policy_guard_whitelist_unchanged(tmp_path):
    """门禁脚本：ENV_KEEP 白名单原样——REGRESS_* 不透传（v1.69 契约），
    PYTHONUTF8 不注入（白名单策略与批191 前逐字节等价）。"""
    d = _mk_layout(tmp_path, target_name="pre_commit_guard.py")
    r = _run(d, "pre_commit_guard.py")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["journal"] is None, "白名单失效：REGRESS_JOURNAL 透传给了门禁"
    assert out["zproj"] == "/tmp/proj", "白名单漏放宿主契约变量"
    assert out["utf8"] is None, "门禁白名单被擅改（应逐字节等价）"
