"""模板规范在场性（批141）：两条暗知识明文化的 claims 化锁。

病例：批135 落地过程中清单 file: 带 regress-guard/ 前缀致 F3 反复拦
（清单声明空间=提交所在仓相对路径，代码注释有答案但模板从不明说）；
verify 缺 cd <仓目录> && 前缀致门禁 5.6 复验 FileNotFoundError 假红
（run2 起已知坑，批135/136 各再踩两次）。文档规范无机器位=改丢无人知。
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_template_has_path_norm():
    t = open(os.path.join(ROOT, "templates", "regress-manifest.md"),
             encoding="utf-8").read()
    assert "提交所在仓的相对路径" in t, "file 字段子仓相对路径规范注释丢失"
    assert "嵌套仓" in t


def test_template_has_verify_cwd_norm():
    t = open(os.path.join(ROOT, "templates", "regress-manifest.md"),
             encoding="utf-8").read()
    assert "cd <仓目录>" in t and "复验" in t, "verify cwd 前缀规范注释丢失"


def test_plan_command_mentions_norms():
    t = open(os.path.join(ROOT, "commands", "regress:plan.md"),
             encoding="utf-8").read()
    assert "子仓相对" in t and "cd <仓目录>" in t, "plan 命令骨架缺两规范"
