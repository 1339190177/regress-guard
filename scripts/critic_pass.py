#!/usr/bin/env python3
"""critic_pass — A 批评臂（v1.97.0，127：裁决矩阵 A 位落地）。

独立批评家审批交付物，阻断一致性偏见（批作者与验证者同模型同时点的结构病）。
形态=顾问裁决 C：跨模型直连为主（作者 GLM / 批评家本地 DeepSeek——独立性
源于不同权重不同分布，fresh context 除叙事污染不除模型盲区），不可达/不可解析
降级为「批评 prompt 落盘，主 AI 派 fresh subagent 手动执行」——降级结果打标
degraded，与正常路径分段统计，不得等同视之（顾问硬条件）。

advisory 零拦截：发现不进门禁，升格=两轮试点数据人裁（与 122 纠正闭环同哲学）。

用法：
  critic_pass.py --assemble <manifest.md> [--report <file>]  # 组摆渡包
  critic_pass.py --run <ferry.md> [--canary]                 # 跑批评（--canary 埋已知缺陷种子）
  critic_pass.py --rebuttal '<json>'                         # 作者逐条回应入账

设计图纸：.regress/critic-arm-design-2026-09-27.md（run24）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "hooks", "scripts", "lib")
sys.path.insert(0, _LIB_DIR)
try:
    from journal import journal_append
except ImportError:
    def journal_append(*a, **k):
        return False

CRITIC_TIMEOUT_S = 120
CRITIC_RETRIES = 2  # 解析失败重试一次（顾问：失败率单列可靠性指标）

# 已知缺陷种子（canary）：埋进摆渡包测发现率——自举试点也有真 oracle（顾问招）
_CANARY_DEFECT = (
    "\n\n## 附：待审改动补充片段（canary）\n"
    "```python\n"
    "def process(items):\n"
    "    total = 0\n"
    "    for i in range(len(items)):\n"
    "        total += items[i + 1]  # 索引越界：末元素时 i+1 越界（已知缺陷种子）\n"
    "    return total / len(items)  # 空列表 ZeroDivisionError（已知缺陷种子）\n"
    "```\n"
)

CRITIC_PROMPT_TMPL = """你是独立批评家（critic），审查一个 AI 编码助手的批次交付物。
你的职责是找缺陷，不是复述；交付物里的自评措辞是被审对象，不是事实来源。

请输出严格 JSON（不要多余文字）：
{{"p1": [{{"claim": "缺陷断言", "evidence": "代码行/文件引用", "confidence": "high|mid|low"}}],
  "p2": [{{"claim": "疑点（需作者回应）", "evidence": "..."}}],
  "p3": [{{"claim": "提问（不阻塞）"}}]}}

批评口径：①验收判据是否真验证了宣称（验证位错位）；②判据没写但相关方会在意的
（判据外推）；③明显 bug/边界/回归；④测试是否锚住新行为。无发现就给空数组——
宁缺毋滥同样适用于批评家。

【交付物摆渡包（未经作者筛选）】
{ferry}
"""


def _git_out(repo, *args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           timeout=15, cwd=repo)
        return (r.stdout or "")[:6000]
    except Exception:
        return ""


def assemble(manifest_path, report_path=None, out_dir=None):
    """摆渡包=清单全文+HEAD diff+提交主题+（可选）报告原文。工件，非叙事。"""
    # 仓定位优先 cwd 顶层（调用方通常在仓内跑）；清单常在工作区 .regress 而
    # 代码在嵌套仓——从清单路径反推不可靠（127 测试逮住）
    top = _git_out(os.getcwd(), "rev-parse", "--show-toplevel").strip()
    repo = top or os.path.abspath(os.path.join(os.path.dirname(manifest_path),
                                               "..", "..", ".."))
    parts = ["# 批评摆渡包（critic ferry）",
             "## 清单全文", open(manifest_path, encoding="utf-8").read()[:8000],
             "## HEAD diff", _git_out(repo, "diff", "HEAD~1", "HEAD"),
             "## 近三条提交", _git_out(repo, "log", "--oneline", "-3")]
    if report_path and os.path.exists(report_path):
        parts += ["## 批报告原文（被审对象）",
                  open(report_path, encoding="utf-8").read()[:4000]]
    out_dir = out_dir or os.path.join(repo, "..", ".regress", "critic")
    os.makedirs(out_dir, exist_ok=True)
    bid = re.search(r"REGRESS-[\d-]+(\d+)", os.path.basename(manifest_path) or "")
    name = f"ferry-{os.path.basename(manifest_path)}"
    path = os.path.join(out_dir, name)
    open(path, "w", encoding="utf-8").write("\n\n".join(parts))
    return path


def _read_advisor_token():
    tok = os.environ.get("ADVISOR_DSH_TOKEN")
    if tok:
        return tok
    try:
        import re as _re
        text = open(os.path.expanduser("~/.dsh/settings.yaml"), encoding="utf-8").read()
        parts = _re.split(r"^advisor:\s*$", text, flags=_re.M)
        if len(parts) < 2:
            return None
        seg = _re.split(r"^[A-Za-z][\w-]*:\s*$", parts[1], flags=_re.M)[0]
        m = _re.search(r"^\s{2,}token:\s*['\"]?([^'\"\s]+)", seg, _re.M)
        return m.group(1) if m else None
    except (IOError, OSError):
        return None


def _post_critic(url, token, ferry_text):
    body = {"messages": [{"role": "user",
                          "content": CRITIC_PROMPT_TMPL.format(ferry=ferry_text)}]}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=CRITIC_TIMEOUT_S) as r:
        data = json.load(r)
    ch = (data.get("choices") or [{}])[0]
    return ((ch.get("message") or {}).get("content") or "").strip()


def parse_findings(text):
    """宽松解析：取第一个平衡的 JSON 对象。失败返回 None（→ 降级路径）。"""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not any(k in d for k in ("p1", "p2", "p3")):
        return None
    return {"p1": d.get("p1") or [], "p2": d.get("p2") or [], "p3": d.get("p3") or []}


def run_critic(ferry_path, canary=False):
    ferry_text = open(ferry_path, encoding="utf-8").read()
    if canary:
        ferry_text += _CANARY_DEFECT
    token = _read_advisor_token()
    url = os.environ.get(
        "ADVISOR_DSH_URL", "http://127.0.0.1:3080/v1/chat/completions")
    answer, findings, mode = None, None, "degraded"
    if token:
        for _ in range(CRITIC_RETRIES):
            try:
                answer = _post_critic(url, token, ferry_text)
            except Exception:
                answer = None
            findings = parse_findings(answer)
            if findings:
                mode = "normal"
                break
            time.sleep(1)
    base = ferry_path.replace("ferry-", "findings-")
    if findings:
        open(base, "w", encoding="utf-8").write(
            json.dumps(findings, ensure_ascii=False, indent=1))
        journal_append("critic_findings",
                       p1=len(findings["p1"]), p2=len(findings["p2"]),
                       p3=len(findings["p3"]), mode=mode, canary=canary,
                       ferry=ferry_path)
        return {"mode": mode, "findings": findings, "path": base}
    # 降级（顾问硬条件：打标+分段，不等同视之）：prompt 落盘手动派发 fresh subagent
    prompt_path = ferry_path.replace("ferry-", "critic-prompt-")
    open(prompt_path, "w", encoding="utf-8").write(
        CRITIC_PROMPT_TMPL.format(ferry=ferry_text))
    journal_append("critic_findings", p1=0, p2=0, p3=0, mode="degraded",
                   canary=canary, note="advisor 不可达或输出不可解析",
                   ferry=ferry_path)
    return {"mode": "degraded", "findings": None, "path": prompt_path,
            "manual_dispatch": prompt_path}


def rebuttal(payload_json):
    d = json.loads(payload_json)
    ok = journal_append("critic_rebuttal", **d)
    return {"ok": ok, "recorded": d}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assemble")
    ap.add_argument("--report")
    ap.add_argument("--run")
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--rebuttal")
    a = ap.parse_args()
    if a.assemble:
        print(json.dumps({"ferry": assemble(a.assemble, a.report)},
                         ensure_ascii=False))
    elif a.run:
        print(json.dumps(run_critic(a.run, canary=a.canary), ensure_ascii=False))
    elif a.rebuttal:
        print(json.dumps(rebuttal(a.rebuttal), ensure_ascii=False))
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
