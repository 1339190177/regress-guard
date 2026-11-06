"""批206（Windows 兼容根治）：subprocess 解码纪律 ratchet。

CI 病例（run 42184306662）：text=True 无 encoding 的调用在 Windows runner
上按 locale（cp1252）解码守卫的 UTF-8 stderr → 读线程 UnicodeDecodeError
被吞 → PytestUnhandledThreadExceptionWarning ×9 且 r.stderr 恒空串——
「拦截文在场」从未被验证过。本测试把「text 模式必带显式 encoding」固化成
机器纪律：新增违例当场红，不等人肉审计（AST 扫描，豁免清单零条目——
豁免清单本身会腐化，规则绝对化才有纪律强度）。"""
import ast
import pathlib

TESTS_DIR = pathlib.Path(__file__).parent
_TEXT_KWS = {"text", "universal_newlines"}
# 只认方法形态（subprocess.run / sp.run / subprocess.Popen）——bare 名调用
# （from subprocess import run）项目内不存在，误报面为零
_FUNC_NAMES = {"run", "Popen", "check_output", "check_call", "call"}


def test_all_text_mode_subprocess_calls_have_explicit_encoding():
    offenders = []
    for py in sorted(TESTS_DIR.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if getattr(f, "attr", None) not in _FUNC_NAMES:
                continue
            kws = {k.arg for k in node.keywords}
            if kws & _TEXT_KWS and "encoding" not in kws:
                offenders.append(f"{py.name}:{node.lineno}")
    assert not offenders, (
        "subprocess text 模式调用缺显式 encoding（Windows cp1252 下解码守卫的"
        "UTF-8 输出必炸，读线程吞异常=stderr 恒空）：\n  " + "\n  ".join(offenders))
