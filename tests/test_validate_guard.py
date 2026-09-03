"""架构守卫（validate 5/5）的负路径测试——从未失败过的守卫等于未验证的守卫。"""
import glob
import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRAP = os.path.join(ROOT, "hooks", "scripts", "_zz_trap_guardtest.py")


def test_architecture_guard_detects_planted_violation():
    """种一个 lib 之外的块解析正则 → validate 的 grep 必须检出（finally 清理防留 trap）。"""
    try:
        with open(TRAP, "w", encoding="utf-8") as f:
            f.write('_APPROVED_BLOCK = re.compile(r"^approved:\\s*\\n(?:[ \\t]+.*\\n?)*", re.M)\n')
        r = subprocess.run(
            ["grep", "-l", "-E", r"\^(approved|blocked|provisional):"]
            + glob.glob(os.path.join(ROOT, "hooks", "scripts", "*.py")),
            capture_output=True, text=True, timeout=10)
        assert TRAP in r.stdout, "守卫失明：种了违规未检出"
    finally:
        if os.path.exists(TRAP):
            os.remove(TRAP)
    # 清理后守卫应恢复干净
    r2 = subprocess.run(
        ["grep", "-l", "-E", r"\^(approved|blocked|provisional):"]
        + glob.glob(os.path.join(ROOT, "hooks", "scripts", "*.py")),
        capture_output=True, text=True, timeout=10)
    assert r2.stdout.strip() == "", f"清理后仍有残留检出: {r2.stdout}"


def test_lib_single_source_has_the_patterns():
    """正样本：单一来源本身必须包含三个块解析（守卫没把合法宿主也禁了）。"""
    src = open(os.path.join(ROOT, "hooks", "scripts", "lib", "manifest_fields.py"),
               encoding="utf-8").read()
    for block in ("approved", "blocked", "provisional"):
        assert f"^{{{block}}}:\\s" in src or f"^({block}):" in src or block in src


def test_command_byte_budget_warns_on_bloat():
    """v1.23.1 长度预算：超预算命令文件 → warn；预算内 → 静默（正负双路）。"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_docs
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "commands"))
        # 负路：造一个超预算文件
        big = os.path.join(td, "commands", "regress:fat.md")
        with open(big, "w", encoding="utf-8") as f:
            f.write("x" * (check_docs.COMMAND_BYTE_BUDGET + 1))
        errs, warns = [], []
        check_docs.check_v123(td, errs, warns)
        assert not errs and len(warns) == 1 and "regress:fat.md" in warns[0]
        # 正路：删掉后无告警
        os.remove(big)
        with open(os.path.join(td, "commands", "regress:lean.md"), "w",
                  encoding="utf-8") as f:
            f.write("x" * 100)
        errs2, warns2 = [], []
        check_docs.check_v123(td, errs2, warns2)
        assert not errs2 and not warns2


def test_deploy_contract_drift_guard(tmp_path):
    """v1.26.1：REQUIRED_HOOK/LIB 与源目录漂移 → block（病例：2026-09-03 审计半量拷贝）。"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_docs
    # 正路：真实插件目录无漂移
    errs, warns = [], []
    check_docs.check_v1241(ROOT, errs, warns)
    assert not errs, f"真实目录被判漂移: {errs}"
    # 负路：伪源目录多一个脚本不在清单 → 报错
    import shutil
    proj = tmp_path / "plug"
    (proj / "hooks" / "scripts" / "lib").mkdir(parents=True)
    heal = proj / "hooks" / "scripts" / "self_heal.py"
    heal.write_text('REQUIRED_HOOK_FILES = ["a.py"]\nREQUIRED_LIB_FILES = ["l.py"]\n',
                    encoding="utf-8")
    (proj / "hooks" / "scripts" / "a.py").write_text("", encoding="utf-8")
    (proj / "hooks" / "scripts" / "zzz_extra.py").write_text("", encoding="utf-8")
    (proj / "hooks" / "scripts" / "lib" / "l.py").write_text("", encoding="utf-8")
    (proj / "hooks" / "scripts" / "lib" / "zzz_lib.py").write_text("", encoding="utf-8")
    errs2, _ = [], []
    check_docs.check_v1241(str(proj), errs2, _)
    assert any("zzz_extra" in e for e in errs2) and any("zzz_lib" in e for e in errs2)
