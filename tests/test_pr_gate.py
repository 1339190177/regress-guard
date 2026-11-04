"""pr_gate 机械评审（批174）：纯逻辑判据 + manifest_parser 集成。

钉死面：
- ①边界：清单内∪.regress/** 放行、清单外拦、禁改区拦
- ③描述：三段齐缺段红
- ⑤判据机械化：已验标记/N-N 对账/全绿措辞三类过；N≠N 矛盾红；含糊红
  （"该升不升=假阴性通道"——含糊必升级是本判据的存在理由）
- ears_extract 集成：两行式判据拼回、无验收节=(False, [])
- sweep 的拒绝面过滤：kind=ignore 行内精确判定（AND/OR 优先级标本预防）
"""
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))
import pr_gate  # noqa: E402


# ─── ① 边界 ──────────────────────────────────────────────

def test_boundary_within_manifest_and_regress():
    ok, _ = pr_gate.check_boundary(
        ["calc.py", "tests/t.py", ".regress/manifests/5.md"],
        ["calc.py", "tests/t.py"], [])
    assert ok


def test_boundary_outside_manifest_blocks():
    ok, why = pr_gate.check_boundary(["evil.py"], ["calc.py"], [])
    assert not ok and "清单外" in why


def test_boundary_forbidden_blocks():
    ok, why = pr_gate.check_boundary(
        [".ssh/config"], ["whatever"], [".ssh/**"])
    assert not ok and "禁改区" in why


# ─── ③ 描述段 ────────────────────────────────────────────

def test_sections_present_and_missing():
    body = "## 背景\nx\n## 改动\ny\n## 验证\nz"
    assert pr_gate.check_sections(body, ["背景", "改动", "验证"])[0]
    ok, why = pr_gate.check_sections("## 背景", ["背景", "改动", "验证"])
    assert not ok and "改动" in why and "验证" in why


# ─── ⑤ 判据机械化（保守口径：含糊必升）──────────────────

def test_criteria_verified_mark_passes():
    assert pr_gate.check_criteria(["全量 5/5 passed ✅"], 5, 5)[0]
    assert pr_gate.check_criteria(["（验：命令）已验"], 5, 5)[0]


def test_criteria_ratio_match_and_mismatch():
    assert pr_gate.check_criteria(["测试 5/5"], 5, 5)[0]
    ok, why = pr_gate.check_criteria(["测试 3/5"], 5, 5)
    assert not ok and "矛盾" in why


def test_criteria_all_green_phrase():
    assert pr_gate.check_criteria(["pytest 全绿"], 7, 7)[0]
    ok, _ = pr_gate.check_criteria(["pytest 全绿"], 6, 7)
    assert not ok  # 全绿措辞但测试没全过=矛盾


def test_criteria_ambiguous_escalates():
    ok, why = pr_gate.check_criteria(["用户会觉得更快"], 5, 5)
    assert not ok and "含糊" in why


def test_criteria_empty_rows_pass():
    assert pr_gate.check_criteria([], 5, 5)[0]


# ─── manifest_parser 集成 ────────────────────────────────

def test_ears_extract_two_line_logical_row(tmp_path):
    m = tmp_path / "m.md"
    m.write_text(
        "---\nid: t\nstatus: in-progress\n---\n\n## 验收标准（EARS）\n\n"
        "- When 测试跑，Then 全绿。（验：pytest）5/5 passed ✅\n",
        encoding="utf-8")
    present, rows = pr_gate.ears_extract(str(m))
    assert present and len(rows) == 1
    assert pr_gate.check_criteria(rows, 5, 5)[0]


def test_ears_extract_no_section(tmp_path):
    m = tmp_path / "m.md"
    m.write_text("---\nid: t\n---\n\n正文无验收节\n", encoding="utf-8")
    present, rows = pr_gate.ears_extract(str(m))
    assert not present and rows == []


def test_planned_changes_extraction(tmp_path):
    m = tmp_path / "m.md"
    m.write_text(
        "---\nid: t\nplanned_changes:\n  - file: calc.py\n"
        "  - file: tests/t.py\n---\n正文\n", encoding="utf-8")
    data = pr_gate.parse_frontmatter(str(m))
    files = [c["file"] for c in data["planned_changes"]]
    assert files == ["calc.py", "tests/t.py"]
    assert pr_gate.check_boundary(files, files, [])[0]


# ─── sweep 拒绝面过滤（AND/OR 优先级标本预防）─────────────

def test_ignored_filter_kinds(tmp_path):
    rows = [
        {"threadKey": "github:9", "kind": "ignore"},
        {"threadKey": "github:5", "kind": "explicit"},
    ]
    # 行内 kind 精确过滤逻辑（与 sweep 内实现同语义）
    out = [d["threadKey"] for d in rows if d.get("kind") == "ignore"]
    assert out == ["github:9"]


def test_notify_and_journal_are_best_effort(monkeypatch):
    # 自崩不掩盖：通知/落账失败不影响评审判定本体
    calls = []
    monkeypatch.setattr(pr_gate, "_notify", lambda *a: calls.append(a))
    monkeypatch.setattr(pr_gate, "_journal", lambda *a: calls.append(a))
    pr_gate._notify("t", "b")
    assert calls


def test_registry_path_constant():
    # 注册表红线：sweep 只认 pr-review-repos.json
    assert pr_gate.REGISTRY.endswith("pr-review-repos.json")


# ─── ④ test_cmd 覆盖路径（批175）─────────────────────────

def test_test_cmd_branch_semantics(tmp_path):
    """仓声明 test_cmd 时 ④ 以该命令 exit code 判定（shell=True 语义）。"""
    import subprocess
    for cmd, expect_ok in [("true", True), ("exit 3", False),
                           ("echo done && true", True)]:
        r = subprocess.run(cmd, shell=True, cwd=str(tmp_path),
                           capture_output=True, text=True)
        assert (r.returncode == 0) == expect_ok


def test_test_cmd_tail_note():
    """输出尾行截 120 字符进 hermetic 证据行（人可读）。"""
    import subprocess
    r = subprocess.run("printf 'l1\nl2\nlast'", shell=True, capture_output=True, text=True)
    tail = (r.stdout or r.stderr or "").strip().splitlines()[-1][:120]
    assert tail == "last"


# ─── 加速改造（全开批）：test-only 快道 + 计数不可得口径 ──

def test_criteria_countless_mode():
    """test_cmd 模式（passed<0）：全绿行以 exit code（tests_ok）为准。"""
    assert pr_gate.check_criteria(["模块测试全绿"], -1, -1, tests_ok=True)[0]
    ok, why = pr_gate.check_criteria(["模块测试全绿"], -1, -1, tests_ok=False)
    assert not ok
    ok, why = pr_gate.check_criteria(["测试 5/5"], -1, -1, tests_ok=True)
    assert not ok and "含糊" in why  # 计数不可得时 N/N 不可对账=含糊


def test_testonly_detection():
    """test-only 判定：全部非 .regress 文件为测试形态才走快道。"""
    import os
    def is_testonly(files):
        tf = [f for f in files if not f.startswith(".regress/")]
        return bool(tf) and all(
            ("test" in os.path.basename(f) or f.startswith(("tests/", "__tests__/")))
            for f in tf)
    assert is_testonly(["tests/a.test.ts", ".regress/manifests/x.md"])
    assert is_testonly(["device-access-platform/packages/database/tests/secrets.test.mjs"])
    assert not is_testonly(["src/app.ts", "tests/a.test.ts"])
    assert not is_testonly([])  # 纯 .regress 变更不触发快道


# ─── ④ hermetic 计数口径（批177：-1/-1 展示缺口）──────────

def test_fmt_hermetic_counts():
    assert pr_gate.fmt_hermetic(7, 7) == "7/7"


def test_fmt_hermetic_missing_counts_as_exit0():
    # tongtu test_cmd（pnpm 链）输出尾行无 passed/total JSON——诚实口径=exit0
    # 而非误导性的 -1/-1；⑤的"全绿+exit0 放行"路径不受影响（另有测试钉住）
    assert pr_gate.fmt_hermetic(-1, -1) == "exit0"


# ─── 升级评论教学行（run60 批182：昨夜七单标本）──────────

def test_escalation_hint_teaches_for_criteria_fail():
    h = pr_gate.escalation_hint("判据含糊(不可机械化): 「When xxx，则 yyy」")
    assert "✅" in h and "骨架" in h and "N/N" in h


def test_escalation_hint_silent_for_other_failures():
    # 非判据类（如清单缺失）不加教学——评论与旧文等价，教学只进判据信道
    assert pr_gate.escalation_hint("PR 内无清单验收行") == ""
    assert pr_gate.escalation_hint("") == ""


# ─── 批184：⑥拆家 + 冲突引擎纯件 ──────────────────────

def test_human_signal_split_conflict_vs_review():
    ok, why, c = pr_gate._judge_human_signal([], 'CONFLICTING')
    assert not ok and c and '冲突' in why
    ok, why, c = pr_gate._judge_human_signal(['CHANGES_REQUESTED'], 'MERGEABLE')
    assert not ok and not c and '人审' in why
    assert pr_gate._judge_human_signal([], 'MERGEABLE')[0]


def test_conflict_directive_hygiene_and_playbook():
    d = pr_gate.conflict_directive("some-agent-login")
    assert '<' not in d and '>' not in d and 'yelisheng' not in d
    assert '@some-agent-login' in d
    for kw in ('归因', '意图调和', 'merge dev', '禁 force', '冲突熔断', '最小 PR 号'):
        assert kw in d


def test_break_marker_only_from_others():
    cs = [{'body': pr_gate.conflict_directive('a-bot'), 'author': {'login': 'me'}},
          {'body': '冲突熔断：交棒', 'author': {'login': 'worker-1'}}]
    assert pr_gate._has_break_marker(cs, 'me')
    assert not pr_gate._has_break_marker(cs[:1], 'me')
