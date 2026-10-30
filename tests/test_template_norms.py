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


# ─── 批160（v1.108 §17/证据环境梯级）：三把在场/派生锁 ──────

def test_claim_discipline_has_evidence_rungs():
    """批160：证据环境梯级（R0–R3）节在场锁——纪律位，内容强制等升格
    三条件（形状连两批稳定后才议，claim-discipline 文末自己的律）。"""
    t = open(os.path.join(ROOT, "docs", "claim-discipline.md"),
             encoding="utf-8").read()
    assert "证据环境梯级" in t, "claim-discipline 缺环境梯级节"
    for rung in ("R0", "R1", "R2", "R3"):
        assert rung in t, f"梯级 {rung} 锚点丢失"
    assert "跨梯级外推" in t, "梯级外推禁令丢失"


def test_philosophy_section_numbers_consecutive():
    """批160：§ 编号连续性锁（派生优于断举——PHILOSOPHY 头部手写计数
    「十三条」是活漂移标本：写下时就与 §0–§16 不符）。尾部追加零破坏；
    跳号/重号即红；§17 幂等律与出生四问同锁。"""
    import re
    t = open(os.path.join(ROOT, "docs", "PHILOSOPHY.md"), encoding="utf-8").read()
    nums = [int(m.group(1)) for m in re.finditer(r"^## (\d+)\.", t, re.M)]
    assert nums == list(range(0, len(nums))), f"§ 编号不连续: {nums}"
    assert "幂等律" in t, "PHILOSOPHY §17 副作用幂等律丢失"
    assert "出生四问" in t and "副作用重试路径" in t, "出生四问措辞丢失"


def test_readme_no_handwritten_principle_count():
    """批160：README 双语禁手写 principles 计数——计数由上一条连续性锁
    派生，手写数字必然漂移（sixteen/十六条 与「十三条」标本同病）。"""
    en = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    cn = open(os.path.join(ROOT, "README_CN.md"), encoding="utf-8").read()
    assert "sixteen principles" not in en, "README 手写计数复活"
    assert "十六条" not in cn, "README_CN 手写计数复活"
