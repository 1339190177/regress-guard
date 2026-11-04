"""install_dogfood（批138）：陌生用户装机路径的机器合同。

狗粮全链子进程真跑（~30-60s）标 slow——缺省跳（顾问：拖慢套件=无人爱跑），
哨兵轮显式 bash scripts/install_dogfood.sh 是日跑位。preflight 拒绝路径用
stub python 注入（快，缺省跑）。
"""
import os
import stat
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOGFOOD = os.path.join(ROOT, "scripts", "install_dogfood.sh")
INSTALL = os.path.join(ROOT, "install.sh")


@pytest.mark.skipif(os.environ.get("REGRESS_DOGFOOD") != "1",
                    reason="狗粮全链 ~60s——哨兵轮显式跑（REGRESS_DOGFOOD=1 开）")
def test_dogfood_full_chain_green():
    """fresh HOME 安装→四查→边界拦→阀拦→门禁过，exit 0+摩擦清单。"""
    r = subprocess.run(["bash", DOGFOOD], capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]
    assert "狗粮全链绿（6/6）" in r.stdout
    assert "摩擦清单" in r.stdout


def test_preflight_rejects_missing_python(tmp_path):
    """python3 缺失：明白话退出（批191 后 install.sh 是薄委托——exec 找不到
    python3 时 bash 报 command not found 非零退出，同语义成立）。"""
    import shutil
    py = shutil.which("python3")
    if not py:
        pytest.skip("本机无 python3（测试前提不成立）")
    py_dir = os.path.dirname(py)
    # 剔除 python3 所在目录的 PATH（bash 等仍可达；若他处还有 python3 则跳过）
    path = os.pathsep.join(d for d in os.environ["PATH"].split(os.pathsep)
                           if d and os.path.abspath(d) != os.path.abspath(py_dir))
    probe = shutil.which("python3", path=path)
    if probe:
        pytest.skip(f"python3 另在 {probe}——PATH 剔除法不成立")
    zh = tmp_path / "zh"
    zh.mkdir()
    r = subprocess.run(["bash", INSTALL], capture_output=True, text=True,
                       timeout=60, env={"PATH": path, "HOME": str(tmp_path),
                                        "REGRESS_ZCODE_HOME": str(zh)})
    assert r.returncode != 0, "python3 缺失必须退出非零"
    assert "python3" in (r.stderr + r.stdout)


def test_preflight_rejects_old_python(tmp_path, monkeypatch, capsys):
    """低于 3.10：版本门硬拦（README 契约），报错含升级路径。

    批191 安装器 Python 化：版本门查的是运行 install.py 的解释器自身——
    PATH 注入假 python 的老测法对原生安装器不成立（假 python 跑不了
    install.py），改为进程内钉 preflight 契约。"""
    # 批193：env 必须先于模块加载——install.py 的 ZCODE_HOME 在 import 期
    # 定型（模块级读 env），CI 无 ~/.zcode 会死在 isdir 检查而非版本门
    # （本机有 ~/.zcode 掩盖了时序）。
    zh = tmp_path / "zh"
    zh.mkdir()
    monkeypatch.setenv("REGRESS_ZCODE_HOME", str(zh))
    # CI runner 无 node——前置 node 检查先于版本门退出；stub 掉 which
    import shutil as _sh
    _real = _sh.which
    monkeypatch.setattr(_sh, "which", lambda n, path=None: "/fake/node" if n == "node" else _real(n, path=path))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "install_py_under_test", os.path.join(ROOT, "install.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 模块级只算路径（env 已就位）
    monkeypatch.setattr(sys, "version_info", (3, 9, 2))
    with pytest.raises(SystemExit):
        mod.preflight()
    out = capsys.readouterr().out
    assert "3.10" in out, "版本门报错须点名 3.10 契约"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="win32: 执行位概念不存在（狗粮脚本是 POSIX bash 件）")
def test_dogfood_script_executable_bit():
    """狗粮脚本须带执行位（install.sh 不拷它——手工/哨兵直跑入口）。"""
    assert os.stat(DOGFOOD).st_mode & stat.S_IXUSR
