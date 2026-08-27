"""pytest 配置：自动把 hooks/scripts/lib 加入 sys.path。"""
import sys
import os

import pytest

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
LIB = os.path.abspath(LIB)
if LIB not in sys.path:
    sys.path.insert(0, LIB)


@pytest.fixture(autouse=True)
def _no_auto_consult(monkeypatch):
    """单测默认关闭钩子自动咨询（不打真实 dsh 端点）；专项测试自行覆写。"""
    monkeypatch.setenv("REGRESS_AUTO_CONSULT", "off")


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch):
    """单测默认关闭考古地层写入（journal 专项测试在子进程 env 里显式开启）。"""
    monkeypatch.setenv("REGRESS_JOURNAL", "off")
