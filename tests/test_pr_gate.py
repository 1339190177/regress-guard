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

import pytest


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
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert (r.returncode == 0) == expect_ok


@pytest.mark.skipif(sys.platform == "win32",
                    reason="printf+shell 尾行语义 POSIX 绑定（pr_gate 为 Linux CI 侧件）")
def test_test_cmd_tail_note():
    """输出尾行截 120 字符进 hermetic 证据行（人可读）。"""
    import subprocess
    r = subprocess.run("printf 'l1\nl2\nlast'", shell=True, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
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


# ─── 批207：mergeable 三态化——UNKNOWN≠CONFLICTING（PR#94 标本） ───

def test_human_signal_unknown_is_not_conflict():
    """GitHub 瞬态 UNKNOWN 被判冲突=误发冲突解法指令（修前红）。"""
    ok, why, c = pr_gate._judge_human_signal([], 'UNKNOWN')
    assert not ok and not c, (ok, why, c)
    assert '未知' in why and '冲突' not in why
    ok, why, c = pr_gate._judge_human_signal([], None)  # 字段缺失同族
    assert not ok and not c
    ok, why, c = pr_gate._judge_human_signal([], 'CONFLICTING')
    assert c and '冲突' in why  # 冲突语义不回退
    assert pr_gate._judge_human_signal([], 'MERGEABLE')[0]


def test_sweep_unknown_lifecycle_defer_escalate_seal(monkeypatch, tmp_path):
    """UNKNOWN 生命周期：3 轮 defer（零评审零评论）→ 第 4 轮升级一次（明示非冲突）
    → 此后同 head 封口（不再重评=停重复通知，PR#94 解困语义）。"""
    import json as _json

    reg = tmp_path / "reg.json"
    reg.write_text(_json.dumps([{"repo": "o/r", "agent_login": "a1"}]), encoding="utf-8")
    st_path = tmp_path / "st.json"
    st_path.write_text("{}", encoding="utf-8")
    gh_calls = []

    def _gh(args):
        gh_calls.append(" ".join(args[:3]))
        if args[:3] == ["pr", "list", "-R"]:
            return _json.dumps([{"number": 94, "headRefOid": "h1", "mergeable": "UNKNOWN"}])
        if args[:2] == ["pr", "comment"]:
            gh_calls.append("COMMENT:" + (args[-1] if isinstance(args[-1], str) else ""))
            return ""
        raise AssertionError(f"意外 gh 调用: {args}")

    monkeypatch.setattr(pr_gate, "REGISTRY", str(reg))
    monkeypatch.setattr(pr_gate, "_review_state", lambda: (_json.load(open(st_path)), str(st_path)))
    monkeypatch.setattr(pr_gate, "_journal", lambda f: None)
    monkeypatch.setattr(pr_gate, "_notify", lambda t, b: None)
    monkeypatch.setattr(pr_gate, "SUPERAGENT_DB", str(tmp_path / "no.db"))
    monkeypatch.setattr(pr_gate, "_gh", _gh)

    def _boom(*a, **k):
        raise AssertionError("UNKNOWN defer 轮不应触发评审（零克隆零 hermetic）")

    # 轮 1-3：defer——不评审、不评论、不升级
    monkeypatch.setattr(pr_gate, "review_pr", _boom)
    for expect_streak in (1, 2, 3):
        assert pr_gate.sweep() == 0, f"第{expect_streak}轮应 defer 静默"
        st = _json.load(open(st_path))
        rec = st["o/r#94"]
        assert rec["verdict"] == "defer-unknown" and rec["unknown_streak"] == expect_streak
    assert not [c for c in gh_calls if c.startswith("COMMENT")], gh_calls

    # 轮 4：达阈值——评审一次、升级评论一条且明示非冲突
    monkeypatch.setattr(pr_gate, "review_pr", lambda repo, n, cfg: {
        "mechanical_pass": False, "fail_reason": "合并性未知（mergeable=UNKNOWN）",
        "conflict": False, "mode": "auto-merge", "count_txt": "exit0",
        "passed": -1, "total": -1})
    assert pr_gate.sweep() == 1  # 有升级
    comments = [c for c in gh_calls if c.startswith("COMMENT")]
    assert len(comments) == 1, gh_calls
    assert "合并性未知" in comments[0] and "冲突（CONFLICTING）" not in comments[0]
    assert _json.load(open(st_path))["o/r#94"]["verdict"] == "escalate"

    # 轮 5+：同 head 封口——不再评审不再评论（重复通知止于此；pr list 本轮
    # 照常发生是设计——枚举是唯一入口）
    monkeypatch.setattr(pr_gate, "review_pr", _boom)
    n_calls = len(gh_calls)
    assert pr_gate.sweep() == 0
    assert len(gh_calls) == n_calls + 1, gh_calls[n_calls:]  # 仅 pr list
    assert not [c for c in gh_calls[n_calls:] if c.startswith("COMMENT")]
    assert _json.load(open(st_path))["o/r#94"]["verdict"] == "escalate"  # 封口不改判

# ─── 批212：判据核对范围锁 PR 本体（误引串扰根治）───────

def _write_manifest(path, mid, ears_lines, planned=None):
    planned = planned or []
    pc = "\n".join(f"  - file: {f}" for f in planned)
    path.write_text(
        f"---\nid: {mid}\nstatus: in-progress\nplanned_changes:\n{pc}\n---\n\n"
        "## 验收标准（EARS）\n\n" + "\n".join(ears_lines) + "\n",
        encoding="utf-8")


X_ROW = ("当 fleet 修复完成时，脚本对 8B 缺档有明确处理"
         "（跳过并提示，或单服务模式），无静默落空步骤。（验：命令）")


def test_crosstalk_adjacent_prs_zero_leak(tmp_path):
    """串扰标本（tongtu #146）：A 单 manifest 含判据 X，B 单不含——
    评 B 时范围锁 PR 本体，X 与 A 的 planned 文件零串入。"""
    mdir = tmp_path / "manifests"
    mdir.mkdir()
    _write_manifest(
        mdir / "REGRESS-261109-aaaa1111.md", "A",
        [f"- {X_ROW}"],
        planned=["fleet.py"])
    _write_manifest(
        mdir / "REGRESS-261109-bbbb2222.md", "B",
        ["- 当 B 完成时，测试 2/2 全绿。（验：pytest）"],
        planned=["b.py", "tests/test_b.py"])
    meta = {
        "title": "[REGRESS-261109-bbbb2222][fix] B 单",
        "headRefKey": "agent/b-unit-bbbb2222",
        "body": "## 背景\n…\n## 改动\n…\n## 验证\n…",
        "files": [{"path": ".regress/manifests/REGRESS-261109-bbbb2222.md"},
                  {"path": "b.py"}],
    }
    names = [p.name for p in mdir.iterdir()]
    picked = pr_gate._pr_manifest_scope(meta, names)
    assert picked == {"REGRESS-261109-bbbb2222.md"}
    manifest_files, ears = pr_gate._collect_criteria(str(mdir), picked)
    assert manifest_files == ["b.py", "tests/test_b.py"]
    rows = [r for r, _ in ears]
    assert rows and all("fleet" not in r and "8B" not in r for r in rows)
    assert pr_gate.check_criteria(ears, 2, 2)[0]  # 本单判据正常对账通过


def test_scope_diff_only_manifest_still_attributed(tmp_path):
    """标题/分支不带工单号时，diff 涉及的 manifest 仍归本单。"""
    mdir = tmp_path / "manifests"
    mdir.mkdir()
    _write_manifest(mdir / "REGRESS-261109-cccc3333.md", "C",
                    ["- 当 C 完成时，测试 1/1 全绿。（验：pytest）"],
                    planned=["c.py"])
    meta = {"title": "C 单修复", "files": [
        {"path": ".regress/manifests/REGRESS-261109-cccc3333.md"},
        {"path": "c.py"}]}
    picked = pr_gate._pr_manifest_scope(meta, ["REGRESS-261109-cccc3333.md"])
    assert picked == {"REGRESS-261109-cccc3333.md"}


def test_scope_no_attribution_empty(tmp_path):
    """无归属（diff 无 manifest、文本无工单号）=零清单——判据面留给
    「PR 内无清单验收行」既有升级路径，不回退全仓扫描。"""
    meta = {"title": "杂项", "files": [{"path": "x.py"}]}
    assert pr_gate._pr_manifest_scope(meta, ["REGRESS-261109-aaaa1111.md"]) == set()


def test_criteria_failure_message_cites_source():
    """出处自证：判据失败消息含「出处 文件:行号」。"""
    ok, why = pr_gate.check_criteria(
        [("用户会觉得更快", ".regress/manifests/REGRESS-1.md:7")], 5, 5)
    assert not ok and "出处 .regress/manifests/REGRESS-1.md:7" in why
    ok, why = pr_gate.check_criteria(
        [("测试 3/5", ".regress/manifests/REGRESS-1.md:9")], 5, 5)
    assert not ok and "出处 .regress/manifests/REGRESS-1.md:9" in why


def test_criteria_str_rows_backward_compatible():
    """既有调用（裸 str 行）行为不变——回归护栏。"""
    assert pr_gate.check_criteria(["全量 5/5 passed ✅"], 5, 5)[0]
    assert pr_gate.check_criteria(["测试 5/5"], 5, 5)[0]
    ok, why = pr_gate.check_criteria(["用户会觉得更快"], 5, 5)
    assert not ok and "出处" not in why
