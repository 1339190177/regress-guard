"""dsh 命令面契约（批205，公网 issue#3 根治层）。

病根：install.py 装命令到 ~/.zcode/commands/，dsh 不扫该目录——16 个
/regress-* 在 dsh 全部失效（issue#3 实测：输入无反应、AI 当普通文本）。
修复形态：deploy/dsh-native/lib/commands.js 零依赖模块——扫命令 md 经
ctx.commands.register 入 dsh 斜杠菜单（name/description/hint 取自
frontmatter，单一事实源仍是 commands/*.md），执行=md 正文 $ARGUMENTS
展开后构造宿主契约 UserMessage（id+source 必带——agent-loop step 读
message.source.kind，裸 {role,content} 炸 turn 静默丢消息）经
agent.followup 注入新回合（ZCode slash command 语义平移；issue 作者
以为 handler 不能触达模型，实则 followup/inbox 是正门——dsh-acp 同款）。

钉死面：
- 源码契约：index.js 运行时注入 commands（非硬 inject——老宿主拒载会
  拖死钩子面）+ steer 老调用点消息形状收口
- 行为契约：注册全集==仓内命令全集（漂移 ratchet：新命令 md 不接入
  dsh 当场红）；$ARGUMENTS 展开/幂等注册/外来命令不碰/文档缺失指引
- 消息形状：id(uuid)/role/content/source 四件套+frozen——防裸消息回归
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMANDS_JS = ROOT / "deploy" / "dsh-native" / "lib" / "commands.js"
INDEX_JS = ROOT / "deploy" / "dsh-native" / "lib" / "index.js"
REPO_COMMANDS = ROOT / "commands"


def _src(p):
    return open(p, encoding="utf-8").read()


def _node(script, env_extra=None):
    """node 行为探针：commands.js 零外部依赖，可直载（路径经 env 免引号地狱）。"""
    env = {**os.environ, "RG_CMDS_JS": COMMANDS_JS.as_uri(),
           **(env_extra or {})}
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30, env=env)
    assert proc.returncode == 0, f"node 探针崩：{proc.stderr[-600:]}"
    return proc.stdout


def _node_json(script, env_extra=None):
    out = _node(script, env_extra)
    return json.loads(out.strip().splitlines()[-1])


# ─── 源码契约：index.js 接线形态（防重构回归）────────────────────

def test_index_uses_runtime_inject_not_hard():
    src = _src(INDEX_JS)
    # commands 服务走运行时注入：老宿主无该服务时硬 inject=整个插件拒载，
    # 拦截面（治理主体）陪葬——fail-closed 回归，禁止
    assert 'ctx.inject(["commands"]' in src, \
        "commands 必须运行时注入（ctx.inject）——硬 inject 会拖死老宿主钩子面"
    assert 'export const inject = ["workingDirectory"];' in src, \
        "顶层 inject 不得加 commands（老宿主拒载风险）"


def test_index_wires_registrar_and_reconcile():
    src = _src(INDEX_JS)
    assert "createCommandRegistrar" in src, "apply 未接命令注册器"
    assert "registrar?.reconcile()" in src, \
        "session-start 未对账注册（运行中装的新命令免重启入册）"


def test_steer_call_site_message_shape_fixed():
    """批205 同族修复：反思 deny 的 steer 原是裸 {role,content}——缺 source
    会让 agent-loop step 读 message.source.kind 时 TypeError 炸 turn，
    拦截理由静默丢失。"""
    src = _src(INDEX_JS)
    assert "agent.steer(userTextMessage(r.stderr))" in src, \
        "steer 调用点必须走 userTextMessage（id+source 四件套）"
    assert '{ role: "user", content:' not in src, \
        "裸 UserMessage 构造回归（缺 id/source 会炸 turn）"


def test_commands_js_contract_markers():
    src = _src(COMMANDS_JS)
    assert "followup" in src and "agent.steer(" in src, \
        "handler 必须优先 followup、老宿主 steer 兜底"
    assert '$ARGUMENTS' in src, "展开语义（ZCode slash command 平移）必须保留"
    assert 'startsWith("regress-")' in src, \
        "管辖域过滤：~/.zcode/commands/ 同住的外来命令（handoff 等）不碰"


# ─── 行为契约：真仓命令全集注册（漂移 ratchet）──────────────────

def _probe_registrar_body(extra=""):
    return """
    const { createCommandRegistrar } = await import(process.env.RG_CMDS_JS);
    const defs = [];
    const ctx = { commands: { register: (d) => {
        if (defs.some(x => x.name === d.name)) throw new Error("dup: " + d.name);
        defs.push(d); return () => {};
    } } };
    const r = createCommandRegistrar(ctx, process.env.RG_CMD_DIR, undefined);
    const added1 = r.reconcile();
    const added2 = r.reconcile();
    """ + extra + """
    console.log(JSON.stringify({
        added1, added2_count: added2.length,
        names: defs.map(d => d.name),
        bad_desc: defs.filter(d => !d.description || !d.description.trim()).map(d => d.name),
        bad_name: defs.filter(d => !/^[a-z0-9][a-z0-9_-]*$/.test(d.name)).map(d => d.name),
    }));
    """


def test_registrar_covers_every_repo_command():
    """漂移 ratchet：仓内 commands/*.md 全集 == dsh 注册全集——新命令 md
    不接入 dsh（扫描/过滤断裂）当场红。这是 issue#3 的"提前根治"位：
    命令面漂移不再靠用户提 issue 发现。"""
    r = _node_json(_probe_registrar_body(), {"RG_CMD_DIR": str(REPO_COMMANDS)})
    repo = sorted(p.stem for p in REPO_COMMANDS.glob("*.md"))
    assert r["added1"] == repo, f"注册面≠仓内全集：{set(repo) ^ set(r['added1'])}"
    assert r["added2_count"] == 0, "重复 reconcile 必须幂等（宿主同名注册 throw）"
    assert not r["bad_desc"], f"缺 description（斜杠菜单显示用）：{r['bad_desc']}"
    assert not r["bad_name"], f"非法命令名（宿主契约小写域）：{r['bad_name']}"


def test_every_command_md_has_description_frontmatter():
    """frontmatter description 是 dsh 注册与 ZCode 菜单共用元数据——
    新命令 md 缺它=双宿主菜单同降级。"""
    for p in sorted(REPO_COMMANDS.glob("*.md")):
        text = open(p, encoding="utf-8").read()
        m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
        assert m, f"{p.name} 缺 frontmatter"
        assert re.search(r"^description:\s*\S", m.group(1), re.M), \
            f"{p.name} 缺 description（dsh 斜杠菜单注册元数据）"


# ─── 行为契约：注册过滤与执行注入 ────────────────────────────────

def test_registrar_scopes_to_regress_files_only(tmp_path):
    d = tmp_path / "cmds"
    d.mkdir()
    (d / "regress-a.md").write_text(
        "---\ndescription: 甲\nargument-hint: <x>\n---\n正文A $ARGUMENTS",
        encoding="utf-8")
    (d / "handoff.md").write_text("---\ndescription: 外来\n---\nx",
                                  encoding="utf-8")
    (d / "ask-deepseek.md").write_text("---\ndescription: 外来\n---\nx",
                                       encoding="utf-8")
    (d / "regress-BAD.md").write_text("---\ndescription: 非法名\n---\nx",
                                      encoding="utf-8")
    script = _probe_registrar_body() .replace(
        "console.log(JSON.stringify({",
        "console.log(JSON.stringify({ hint: defs.find(x=>x.name==='regress-a')?.input?.hint,")
    r = _node_json(script, {"RG_CMD_DIR": str(d)})
    assert r["added1"] == ["regress-a"], "外来/非法名命令不得注册"
    assert r["hint"] == "<x>", "argument-hint 应进 input.hint"


def test_handler_expands_and_injects_user_turn(tmp_path):
    """执行语义：md 正文（剥 frontmatter）$ARGUMENTS→rawInput，构造
    id/role/content/source 四件套 frozen UserMessage 经 followup 注入。"""
    d = tmp_path / "cmds"
    d.mkdir()
    (d / "regress-plan.md").write_text(
        "---\ndescription: 计划\n---\n\n# /regress-plan\n\n需求：$ARGUMENTS\n步骤…",
        encoding="utf-8")
    script = """
    const { createCommandRegistrar } = await import(process.env.RG_CMDS_JS);
    const defs = [];
    const ctx = { commands: { register: (d) => { defs.push(d); return () => {}; } } };
    createCommandRegistrar(ctx, process.env.RG_CMD_DIR, undefined).reconcile();
    const followups = [];
    const agent = { followup: (m) => followups.push(m) };
    const res = defs[0].handler({ agent, rawInput: " 修复登录bug ", commandId: "c",
                                  attachments: [], signal: undefined });
    const m = followups[0];
    console.log(JSON.stringify({
        kind: res.kind,
        uuid: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(m.id),
        role: m.role, source: m.source.kind, frozen: Object.isFrozen(m),
        content_type: m.content[0].type,
        text: m.content[0].text,
    }));
    """
    r = _node_json(script, {"RG_CMD_DIR": str(d)})
    assert r["kind"] == "success"
    assert r["uuid"] and r["role"] == "user" and r["source"] == "user", \
        "UserMessage 四件套缺件（裸消息会炸 agent-loop turn）"
    assert r["frozen"], "消息应 frozen（宿主 createUserMessage 语义）"
    assert r["content_type"] == "text"
    text = r["text"]
    assert "需求： 修复登录bug" in text, "$ARGUMENTS 未按 rawInput 展开"
    assert "$ARGUMENTS" not in text, "占位符残留"
    assert "description: 计划" not in text, "frontmatter 必须剥除（元数据不进模型）"
    assert text.lstrip().startswith("# /regress-plan"), "正文应从命令体开始"


def test_handler_fallbacks_and_missing_md(tmp_path):
    d = tmp_path / "cmds"
    d.mkdir()
    (d / "regress-init.md").write_text("---\ndescription: 初始化\n---\n正文",
                                       encoding="utf-8")
    script = """
    const fs = await import("node:fs");
    const path = await import("node:path");
    const { createCommandRegistrar } = await import(process.env.RG_CMDS_JS);
    const defs = [];
    const ctx = { commands: { register: (d) => { defs.push(d); return () => {}; } } };
    const r = createCommandRegistrar(ctx, process.env.RG_CMD_DIR, undefined);
    r.reconcile();
    const h = defs.find(x => x.name === "regress-init").handler;
    const steers = [];
    const steerOnly = h({ agent: { steer: (m) => steers.push(m) }, rawInput: "" });
    const noAgent = h({ agent: {}, rawInput: "" });
    fs.rmSync(path.join(process.env.RG_CMD_DIR, "regress-init.md"));
    const missing = h({ agent: { followup: () => {} }, rawInput: "" });
    // 无 commands 服务 / 目录不可读：fail-soft 不抛
    const bare = createCommandRegistrar({}, process.env.RG_CMD_DIR, undefined).reconcile();
    const nodir = createCommandRegistrar(ctx, "/nonexistent-dir-rg205").reconcile();
    console.log(JSON.stringify({
        steer_ok: steerOnly.kind, steer_frozen: Object.isFrozen(steers[0]),
        no_agent: noAgent.kind, no_agent_text: noAgent.text,
        missing_kind: missing.kind, missing_text: missing.text,
        bare, nodir,
    }));
    """
    r = _node_json(script, {"RG_CMD_DIR": str(d)})
    assert r["steer_ok"] == "success" and r["steer_frozen"], \
        "老宿主 steer 兜底（idle steer 同样开 turn）"
    assert r["no_agent"] == "error" and "followup" in r["no_agent_text"], \
        "宿主无注入通道必须显式报错（不静默假装成功）"
    assert r["missing_kind"] == "error" and "install.py" in r["missing_text"], \
        "文档缺失要给修复指引"
    assert r["bare"] == [] and r["nodir"] == [], \
        "无 commands 服务/目录不可读必须 fail-soft（钩子面不受牵连）"


def test_late_command_reconciles_without_restart(tmp_path):
    """session-start 对账语义：注册器存活期间新落盘的命令 md 补注入册
    （install.py 升级后免重启 dsh）。"""
    d = tmp_path / "cmds"
    d.mkdir()
    (d / "regress-old.md").write_text("---\ndescription: 旧\n---\nx",
                                      encoding="utf-8")
    script = """
    const fs = await import("node:fs");
    const path = await import("node:path");
    const { createCommandRegistrar } = await import(process.env.RG_CMDS_JS);
    const defs = [];
    const ctx = { commands: { register: (d) => { defs.push(d); return () => {}; } } };
    const r = createCommandRegistrar(ctx, process.env.RG_CMD_DIR, undefined);
    r.reconcile();
    fs.writeFileSync(path.join(process.env.RG_CMD_DIR, "regress-new.md"),
        "---\\ndescription: 新\\n---\\ny");
    const added = r.reconcile();
    console.log(JSON.stringify({ added, total: defs.length }));
    """
    r = _node_json(script, {"RG_CMD_DIR": str(d)})
    assert r["added"] == ["regress-new"] and r["total"] == 2


# ─── 安装器：命令面诊断（--check / 安装后输出）──────────────────

def test_commands_surface_counts_only_regress(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import install_dsh as ids
    cmds = tmp_path / "commands"
    cmds.mkdir()
    for n in ("regress-a.md", "regress-b.md", "handoff.md", "notes.txt"):
        (cmds / n).write_text("x", encoding="utf-8")
    root = tmp_path / "regress-guard-hooks"
    root.mkdir()
    n, cdir = ids.commands_surface(root=str(root))
    assert n == 2 and cdir == str(cmds)
    # 根目录同级无 commands/ → 0（install.py 未跑的实况）
    other = tmp_path / "elsewhere"
    other.mkdir()
    n0, _ = ids.commands_surface(root=str(other / "regress-guard-hooks"))
    assert n0 == 0
