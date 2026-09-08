"""test_runner 的单元测试。

覆盖：detect_runner（项目探测）和各 _parse_* 函数。
不测 run_tests（依赖真实测试运行器，在 E2E 测）。
"""
import sys
import os
import json

LIB = os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib")
sys.path.insert(0, LIB)

from test_runner import detect_runner, _parse_jest, _parse_pytest


# ─── detect_runner 测试 ───────────────────────────────

def test_detect_jest(tmp_path):
    """有 package.json + jest 依赖 → 检测到 jest。"""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "devDependencies": {"jest": "^29.0.0"}
    }))
    runner, cmd = detect_runner(str(tmp_path))
    assert runner == "jest"
    assert "jest" in cmd


def test_detect_vitest(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "devDependencies": {"vitest": "^1.0.0"}
    }))
    runner, _ = detect_runner(str(tmp_path))
    assert runner == "vitest"


def test_detect_pytest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]")
    runner, cmd = detect_runner(str(tmp_path))
    assert runner == "pytest"
    assert "pytest" in cmd


def test_detect_pytest_conftest(tmp_path):
    (tmp_path / "conftest.py").write_text("")
    runner, _ = detect_runner(str(tmp_path))
    assert runner == "pytest"


def test_detect_maven(tmp_path):
    (tmp_path / "pom.xml").write_text("<project></project>")
    runner, _ = detect_runner(str(tmp_path))
    assert runner == "maven"


def test_detect_go(tmp_path):
    (tmp_path / "go.mod").write_text("module test")
    runner, _ = detect_runner(str(tmp_path))
    assert runner == "go"


def test_detect_none(tmp_path):
    """无任何标记文件 → 返回 (None, None)。"""
    runner, cmd = detect_runner(str(tmp_path))
    assert runner is None
    assert cmd is None


def test_detect_broken_package_json(tmp_path):
    """package.json 损坏 → 跳过 Node.js 探测，不崩溃。"""
    (tmp_path / "package.json").write_text("not json")
    runner, _ = detect_runner(str(tmp_path))
    # 损坏的 package.json 不应导致崩溃
    assert runner is None


# ─── _parse_jest 测试 ─────────────────────────────────

def test_parse_jest_pass():
    """jest 全通过的结果正确解析。"""
    jest_output = json.dumps({
        "testResults": [{
            "assertionResults": [
                {"status": "passed", "fullName": "test A"},
                {"status": "passed", "fullName": "test B"},
            ],
            "startTime": 1000,
            "endTime": 2000,
        }]
    })
    result = _parse_jest(jest_output, 0)
    assert result["status"] == "pass"
    assert result["total"] == 2
    assert result["passed"] == 2
    assert result["failed"] == 0


def test_parse_jest_fail():
    """jest 有失败的结果正确解析。"""
    jest_output = json.dumps({
        "testResults": [{
            "assertionResults": [
                {"status": "passed", "fullName": "test A"},
                {"status": "failed", "fullName": "test B",
                 "failureMessages": ["Expected 3, got 2"]},
            ]
        }]
    })
    result = _parse_jest(jest_output, 1)
    assert result["status"] == "fail"
    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["test"] == "test B"


def test_parse_jest_empty():
    """jest 空输出靠 exit code 判断。"""
    result = _parse_jest("no json here", 0)
    assert result["status"] == "pass"  # exit 0


def test_parse_jest_empty_fail():
    result = _parse_jest("no json here", 1)
    assert result["status"] == "fail"


# ─── _parse_pytest 测试 ───────────────────────────────

def test_parse_pytest_pass():
    output = "===== 3 passed in 0.12s ====="
    result = _parse_pytest(output, 0)
    assert result["status"] == "pass"
    assert result["passed"] == 3


def test_parse_pytest_fail():
    output = "FAILED test_one\n===== 2 passed, 1 failed in 0.5s ====="
    result = _parse_pytest(output, 1)
    assert result["status"] == "fail"
    assert result["passed"] == 2
    assert result["failed"] == 1


def test_parse_pytest_errors():
    output = "===== 1 passed, 2 errors in 1.0s ====="
    result = _parse_pytest(output, 1)
    assert result["status"] == "fail"


def test_parse_jest_with_coverage(tmp_path):
    """jest 结果带覆盖率汇总时正确读取。"""
    import json as _json
    cov_dir = tmp_path / ".regress" / ".coverage"
    cov_dir.mkdir(parents=True)
    (cov_dir / "coverage-summary.json").write_text(_json.dumps(
        {"total": {"lines": {"pct": 87.5}}}
    ))
    result = _parse_jest("", 0, project_dir=str(tmp_path))
    assert result.get("coverage_pct") == 88


def test_parse_jest_coverage_missing(tmp_path):
    """无覆盖率文件时 coverage_pct 为 None，不崩溃。"""
    result = _parse_jest("", 0, project_dir=str(tmp_path))
    assert result.get("coverage_pct") is None


# ─── P0-4：嵌套仓探测（评审批次一） ─────────────────────

def test_detect_nested_subrepo(tmp_path):
    """.regress 在根、pytest.ini+tests/ 在子仓 → 探测到 pytest 且 cwd 指子仓。

    治"17 份清单 0 份 hook 标 done"：嵌套布局下旧探测永远 none。"""
    from test_runner import _detect
    root = tmp_path / "workspace"
    sub = root / "regress-guard"
    (root / ".regress").mkdir(parents=True)
    sub.mkdir(parents=True)
    (sub / "pytest.ini").write_text("[pytest]\n")
    (sub / "tests").mkdir()
    (sub / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    runner, cmd, cwd = _detect(str(root))
    assert runner == "pytest"
    assert cwd == str(sub)


def test_detect_skips_dependency_dirs(tmp_path):
    """marker 与测试文件不同在的子目录（纯依赖/样例）不误判（顾问补强）。"""
    from test_runner import _detect
    root = tmp_path / "workspace"
    (root / ".regress").mkdir(parents=True)
    vend = root / "vendor-sample"
    vend.mkdir()
    (vend / "pytest.ini").write_text("[pytest]\n")  # 只有 marker，无测试文件
    (vend / "raw.py").write_text("x = 1\n")
    runner, cmd, cwd = _detect(str(root))
    assert runner is None


def test_hermetic_env_strips_host_identity(monkeypatch):
    """门禁跑测试剥宿主身份变量（三连标本源头收口），其余继承。"""
    from test_runner import hermetic_env
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-x")
    monkeypatch.setenv("ZCODE_PROJECT_DIR", "/host/proj")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    env = hermetic_env()
    assert "CLAUDE_SESSION_ID" not in env and "ZCODE_PROJECT_DIR" not in env
    assert "PATH" in env
