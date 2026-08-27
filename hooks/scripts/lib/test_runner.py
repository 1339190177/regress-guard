#!/usr/bin/env python3
"""检测项目类型并运行测试，返回结构化结果。

被 pre_commit_guard.sh 调用。不信任任何 AI 写的状态，hook 自己跑测试验证。

支持的测试运行器（自动探测）：
  - Node.js: jest（package.json 含 jest 依赖）
  - Python: pytest（存在 pytest.ini / conftest.py / setup.cfg [tool:pytest]）
  - Java: mvn test（存在 pom.xml）/ gradle test（存在 build.gradle）
  - Go: go test（存在 go.mod）

如果找不到测试运行器 → 返回 skip（不阻断，因为可能纯前端/文档项目）。
"""
import sys
import os
import json
import subprocess
import re


def detect_runner(project_dir):
    """探测项目的测试运行器。返回 (runner_name, test_cmd) 或 (None, None)。"""
    # Node.js / Jest
    pkg = os.path.join(project_dir, "package.json")
    if os.path.exists(pkg):
        try:
            with open(pkg) as f:
                data = json.load(f)
            deps = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))
            if "jest" in deps:
                return ("jest", ["npx", "jest", "--json",
                                 "--outputFile=.regress/.jest-result.json",
                                 "--coverage", "--coverageReporters=json-summary",
                                 "--coverageDirectory=.regress/.coverage",
                                 "--silent", "--passWithNoTests"])
            if "vitest" in deps:
                return ("vitest", ["npx", "vitest", "run", "--reporter=json"])
        except (json.JSONDecodeError, OSError):
            pass  # package.json 损坏 → 跳过 Node.js 探测
        # 有 package.json 但没 jest/vitest → 看 test script
        try:
            with open(pkg) as f:
                data = json.load(f)
            test_script = data.get("scripts", {}).get("test", "")
            if test_script and "no test" not in test_script.lower():
                return ("npm-test", ["npm", "test", "--", "--passWithNoTests"])
        except (json.JSONDecodeError, OSError):
            pass

    # Python / pytest
    for marker in ("pytest.ini", "conftest.py", "setup.cfg", "pyproject.toml"):
        if os.path.exists(os.path.join(project_dir, marker)):
            return ("pytest", ["python3", "-m", "pytest", "-q", "--tb=line"])

    # Java / Maven
    if os.path.exists(os.path.join(project_dir, "pom.xml")):
        return ("maven", ["mvn", "test", "-q"])

    # Java / Gradle
    if os.path.exists(os.path.join(project_dir, "build.gradle")) or \
       os.path.exists(os.path.join(project_dir, "build.gradle.kts")):
        return ("gradle", ["./gradlew", "test", "--quiet"])

    # Go
    if os.path.exists(os.path.join(project_dir, "go.mod")):
        return ("go", ["go", "test", "./..."])

    return (None, None)


def run_tests(project_dir, timeout=120):
    """运行测试，返回结果 dict。

    Returns:
        {
            "runner": "jest" | "pytest" | ... | "none",
            "status": "pass" | "fail" | "skip",
            "total": int, "passed": int, "failed": int,
            "duration_ms": int,
            "failures": [{"test": str, "message": str}],
            "raw_snippet": str  # 失败时的输出片段
        }
    """
    runner, cmd = detect_runner(project_dir)

    if runner is None:
        return {
            "runner": "none",
            "status": "skip",
            "total": 0, "passed": 0, "failed": 0,
            "duration_ms": 0,
            "failures": [],
            "raw_snippet": "No test runner detected (no jest/pytest/maven/go.mod found)"
        }

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=project_dir, timeout=timeout
        )
        output = proc.stdout + proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "runner": runner, "status": "fail",
            "total": 0, "passed": 0, "failed": 0,
            "duration_ms": timeout * 1000,
            "failures": [{"test": "(timeout)", "message": f"Tests timed out after {timeout}s"}],
            "raw_snippet": ""
        }
    except FileNotFoundError:
        return {
            "runner": runner, "status": "skip",
            "total": 0, "passed": 0, "failed": 0,
            "duration_ms": 0,
            "failures": [],
            "raw_snippet": f"{cmd[0]} not found in PATH"
        }

    # 解析结果
    if runner == "jest":
        return _parse_jest(output, exit_code, project_dir)
    elif runner == "pytest":
        return _parse_pytest(output, exit_code)
    else:
        # mvn/gradle/go：靠 exit code 判断，不精细解析
        return {
            "runner": runner,
            "status": "pass" if exit_code == 0 else "fail",
            "total": 0, "passed": 0, "failed": 0,
            "duration_ms": 0,
            "failures": [] if exit_code == 0 else [{"test": "(unknown)", "message": output[-300:]}],
            "raw_snippet": output[-200:] if exit_code != 0 else ""
        }


def _read_jest_coverage(project_dir):
    """读取 jest coverage json-summary 的全量行覆盖率（无配置时返回 None）。"""
    summary = os.path.join(project_dir, ".regress", ".coverage", "coverage-summary.json")
    try:
        with open(summary) as f:
            data = json.load(f)
        total = data.get("total", {}).get("lines", {}).get("pct")
        return round(total) if isinstance(total, (int, float)) else None
    except (IOError, json.JSONDecodeError, KeyError):
        return None


def _parse_jest(output, exit_code, project_dir=None):
    """解析 jest --json 输出。优先读 --outputFile 文件。"""
    data = None
    # 优先读 outputFile（避免 stdout 混入诊断信息）
    # jest 以 cwd=project_dir 运行，文件写在 project_dir/.regress/ 下
    base = project_dir or os.getcwd()
    jest_file = os.path.join(base, ".regress", ".jest-result.json")
    if os.path.exists(jest_file):
        try:
            with open(jest_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            data = None
        finally:
            try: os.remove(jest_file)
            except OSError: pass

    # fallback：从 stdout 提取
    if not data:
        matches = list(re.finditer(r'\{.*\}', output, re.DOTALL))
        for m in reversed(matches):
            try:
                data = json.loads(m.group())
                break
            except json.JSONDecodeError:
                continue

    if data and "testResults" in data:
        suites = data.get("testResults", [])
        total = sum(len(s.get("assertionResults", [])) for s in suites)
        passed = sum(
            1 for s in suites for a in s.get("assertionResults", [])
            if a.get("status") == "passed"
        )
        failed = sum(
            1 for s in suites for a in s.get("assertionResults", [])
            if a.get("status") == "failed"
        )
        failures = [
            {
                "test": a.get("fullName", ""),
                "message": (a.get("failureMessages", [""]) or [""])[0][:200]
            }
            for s in suites for a in s.get("assertionResults", [])
            if a.get("status") == "failed"
        ]
        return {
            "runner": "jest",
            "status": "pass" if failed == 0 and exit_code == 0 else "fail",
            "total": total, "passed": passed, "failed": failed,
            "duration_ms": 0,
            "failures": failures[:20],
            "raw_snippet": "",
            "coverage_pct": _read_jest_coverage(base),
        }

    # 完全无法解析 → 靠 exit code（覆盖率独立于测试数解析，仍尝试读取）
    return {
        "runner": "jest",
        "status": "pass" if exit_code == 0 else "fail",
        "total": 0, "passed": 0, "failed": 0,
        "duration_ms": 0,
        "coverage_pct": _read_jest_coverage(base),
        "failures": [] if exit_code == 0 else [{"test": "(parse error)", "message": output[-200:]}],
        "raw_snippet": output[-200:]
    }


def _parse_pytest(output, exit_code):
    """解析 pytest 输出。"""
    # pytest 末尾通常有：===== 3 passed in 0.12s =====
    match = re.search(
        r'(\d+) passed(?:.*?(\d+) failed)?(?:.*?(\d+) error)?',
        output
    )
    passed = failed = errors = 0
    if match:
        passed = int(match.group(1))
        failed = int(match.group(2) or 0)
        errors = int(match.group(3) or 0)

    if exit_code == 0 and failed == 0 and errors == 0:
        return {
            "runner": "pytest", "status": "pass",
            "total": passed, "passed": passed, "failed": 0,
            "duration_ms": 0, "failures": [], "raw_snippet": ""
        }

    # 失败时提取失败用例
    failures = []
    for line in output.split("\n"):
        if "FAILED" in line:
            failures.append({"test": line.strip()[:200], "message": ""})

    return {
        "runner": "pytest", "status": "fail",
        "total": passed + failed + errors,
        "passed": passed, "failed": failed + errors,
        "duration_ms": 0,
        "failures": failures[:20] if failures else [{"test": "(unknown)", "message": output[-200:]}],
        "raw_snippet": output[-300:]
    }


if __name__ == "__main__":
    # CLI 用法：python3 test_runner.py [project_dir]
    project_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    result = run_tests(project_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] in ("pass", "skip") else 1)
