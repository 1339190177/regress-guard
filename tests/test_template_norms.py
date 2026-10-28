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


def test_init_hook_self_upgrade_branch():
    """批147：老自装观测钩子缺 source 字段须能自升级（gated 误计带外标本）。"""
    t = open(os.path.join(ROOT, "commands", "regress:init.md"),
             encoding="utf-8").read()
    assert "自升级" in t, "init.md 缺自升级分支说明"
    # 升级判据三件套：事件名识别（commit_observed）+ 缺口检测（"source"）
    # + 版本标记（source-aware v2）
    assert "grep -q 'commit_observed'" in t
    assert "grep -q '\"source\"'" in t
    assert "source-aware" in t


def _hook_block():
    import re
    t = open(os.path.join(ROOT, "commands", "regress:init.md"),
             encoding="utf-8").read()
    m = re.search(r"```bash\n(if git rev-parse.*?)\n```", t, re.S)
    assert m, "init.md 钩子安装块丢失"
    return m.group(1)


def _run_block(tmp_path, hook_body=None):
    import subprocess
    (tmp_path / ".regress").mkdir()
    if hook_body is not None:
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        (tmp_path / ".git" / "hooks" / "post-commit").write_text(hook_body)
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path,
                   check=True, timeout=30)
    # git init 可能生成样例钩子（非默认；样例带 .sample 后缀不算已存在）
    r = subprocess.run(["sh", "-c", _hook_block()], cwd=tmp_path,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return (tmp_path / ".git" / "hooks" / "post-commit").read_text()


def test_init_hook_installs_when_absent(tmp_path):
    body = _run_block(tmp_path)
    assert "source-aware" in body and '"source"' in body, "新装钩子缺 v2 特征"


def test_init_hook_upgrades_legacy_own_hook(tmp_path):
    """老自装钩子（有 commit_observed 无 source）→ 覆写为 v2。"""
    legacy = ("#!/bin/sh\nD=\"$(git rev-parse --show-toplevel)\"\n"
              "printf '{\"event\":\"commit_observed\"}' >> \"$D/.regress/history.jsonl\"\n")
    body = _run_block(tmp_path, hook_body=legacy)
    assert "source-aware" in body and '"source"' in body, "老钩子未被自升级"


def test_init_hook_leaves_foreign_hook_alone(tmp_path):
    """husky 等外来钩子（无 commit_observed）→ 不碰。"""
    foreign = "#!/bin/sh\nnpx husky\n"
    body = _run_block(tmp_path, hook_body=foreign)
    assert body == foreign, "外来钩子被误覆写"


def test_template_has_impact_scope_field():
    """批148：blast-radius 触发时清单须能声明影响面（模板字段在场锁）。"""
    t = open(os.path.join(ROOT, "templates", "regress-manifest.md"),
             encoding="utf-8").read()
    assert "impact_scope" in t, "模板 impact_scope 字段丢失"
    assert "覆盖门禁检出单元" in t, "impact_scope 注释的覆盖语义丢失"


def test_workflow_write_discipline():
    """批154：.regress 写入防丢纪律在场（四次实证教训的纪律位锁定）。"""
    t = open(os.path.join(ROOT, "docs", "WORKFLOW.md"), encoding="utf-8").read()
    assert "写入防丢纪律" in t, "WORKFLOW 缺防丢纪律节"
    assert "独立读回验证" in t
