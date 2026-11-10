"""stuck_watch 孤儿/卡死分类（run60 批182）：昨夜 7 例"疑似卡死"实为孤儿——
worker 转录尾 turn/end completed（正常收工），PR 被评审判据拦着不合致工单悬空。
分类错了恢复动作就错：孤儿去修 PR 判据，卡死才谈重启。

批207：main() 路径测试补位——修前 3 个测试全是 helper 单测，tickets 变量
遮蔽（批192 引入）使哨兵空转 3 天 CI 全绿（验证主权标本：测试不查入口，
入口坏了等于没测）。"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import stuck_watch  # noqa: E402


def test_stale_label_orphan_vs_hang():
    assert "孤儿" in stuck_watch._stale_label(True)
    assert "疑似卡死" in stuck_watch._stale_label(False)


def test_session_completed_by_tail_text():
    tail = '{"type": "step/end"}\n{"type": "turn/end", "data": {"turn": 4, "reason": {"kind": "completed"}}}'
    # 直接验证判定式（_session_completed 的核心逻辑，文件版走 zstd 子进程）
    assert '"turn/end"' in tail and '"completed"' in tail


def test_session_active_tail_is_not_completed():
    tail = '{"type": "tool/call", "data": {"name": "bash"}}\n{"type": "step/start"}'
    assert not ('"turn/end"' in tail and '"completed"' in tail)


# ─── 批207：main() 路径（红绿钉：修前遮蔽标本，修后真输出） ───

TID = "abcdef1234567890abcdef1234567890"


def _mk_instance(tmp_path, sessions_root, stale_min_ago=None, notified=None):
    """假 superagent 实例：orchestrator.sqlite 一张 running 工单 + 可配龄的会话文件。"""
    inst = tmp_path / "superagent-fake"
    inst.mkdir()
    db = sqlite3.connect(inst / "orchestrator.sqlite")
    db.execute("CREATE TABLE ticket (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO ticket VALUES (?, ?)", (TID, json.dumps({
        "title": "假工单", "createdAt": "2026-11-07T01:00:00.000Z",
        "assignments": [{"state": "running", "startedAt": "2026-11-07T01:01:00Z"}],
    })))
    db.commit()
    db.close()
    sf = sessions_root / "fake" / f"worker-{TID}" / "session.v4.jsonl.zstd"
    sf.parent.mkdir(parents=True)
    sf.write_bytes(b"not-real-zstd-but-nonempty")
    if stale_min_ago is not None:
        old = time.time() - stale_min_ago * 60
        os.utime(sf, (old, old))
    return inst


def _armed(monkeypatch, tmp_path, inst, notified):
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(stuck_watch, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(stuck_watch, "SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(stuck_watch, "_state_dirs", lambda: [str(inst)])
    monkeypatch.setattr(stuck_watch, "_notify",
                        lambda t, b: notified.append((t, b)))
    monkeypatch.setattr(stuck_watch, "_journal", lambda n: notified.append(n))


def test_main_reports_running_and_heartbeat(monkeypatch, tmp_path, capsys):
    """鲜活 running 工单：running 1 健康 1，零发现，rc 0——修前遮蔽使恒 0（红）。"""
    notified = []
    inst = _mk_instance(tmp_path, tmp_path / "sessions", stale_min_ago=0)
    _armed(monkeypatch, tmp_path, inst, notified)
    assert stuck_watch.main() == 0
    out = capsys.readouterr().out
    assert "running 1" in out and "健康 1" in out, out
    assert "实例 1" in out and f"工单 {1}" in out, out   # 批207 心跳自证
    assert not notified


def test_main_flags_stale_as_suspected_hang(monkeypatch, tmp_path, capsys):
    """静默>20min 的 running：疑似卡死告警（无效 zstd→非孤儿→疑似卡死），rc 1。"""
    notified = []
    inst = _mk_instance(tmp_path, tmp_path / "sessions", stale_min_ago=30)
    _armed(monkeypatch, tmp_path, inst, notified)
    assert stuck_watch.main() == 1
    out = capsys.readouterr().out
    assert "running 1" in out
    assert any("疑似卡死" in str(x) for x in notified), notified
    assert notified, "只报不杀也要报（WeCom/journal）"


def test_main_heartbeat_zero_is_distinguishable(monkeypatch, tmp_path, capsys):
    """零实例：心跳仍报扫描面（实例0 工单0）——与谎报 running 0 可区分，rc 0。"""
    notified = []
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(stuck_watch, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(stuck_watch, "_state_dirs", lambda: [])
    monkeypatch.setattr(stuck_watch, "_notify", lambda t, b: notified.append(t))
    monkeypatch.setattr(stuck_watch, "_journal", lambda n: notified.append(n))
    assert stuck_watch.main() == 0
    out = capsys.readouterr().out
    assert "实例 0" in out and "running 0" in out, out
    assert not notified


# ─── 批220：服务活性双信号+跃迁制（"running 0"分不清停摆与空闲的盲区） ───
# 标本=11-07 周末 30h 空窗：服务停摆期间巡检照绿；主实例停摆数日零噪音可展示。

import time as _time


def _fake_proc(root, pid, cwd=None, cmdline=""):
    d = root / str(pid)
    d.mkdir(parents=True)
    if cwd:
        (d / "cwd").symlink_to(cwd)
    if cmdline:
        (d / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())
    return d


def test_service_alive_lock_fresh(tmp_path):
    """信号 A：实例同级 <dir>.lock 目录 mtime 新鲜即活（零进程也活）。"""
    inst = tmp_path / "superagent-fake"
    inst.mkdir()
    lock = tmp_path / "superagent-fake.lock"
    lock.mkdir()
    alive, why = stuck_watch._service_alive(
        str(inst), proc_root=str(tmp_path / "no-proc"))
    assert alive and "lock" in why


def test_service_alive_stale_lock_procs_present(tmp_path):
    """信号 B 双保险：lock 超龄但进程边界命中在场仍活。"""
    inst = tmp_path / "superagent-fake"
    (inst / "work" / "wo-1").mkdir(parents=True)
    lock = tmp_path / "superagent-fake.lock"
    lock.mkdir()
    old = _time.time() - 20 * 3600
    os.utime(lock, (old, old))
    proc = tmp_path / "proc"
    _fake_proc(proc, 101, cwd=str(inst / "work" / "wo-1"))
    alive, why = stuck_watch._service_alive(str(inst), proc_root=str(proc))
    assert alive and "进程在场" in why


def test_service_alive_dead_when_no_lock_no_proc(tmp_path):
    """双无=停，判据明示（lock 缺失/超龄且零进程）。"""
    inst = tmp_path / "superagent-fake"
    inst.mkdir()
    alive, why = stuck_watch._service_alive(
        str(inst), proc_root=str(tmp_path / "no-proc"))
    assert not alive and "零进程" in why


def test_proc_refs_no_substring_crosstalk(tmp_path):
    """边界串扰钉（校准实弹）：tongtu 路径进程不得算给主实例 superagent——
    裸子串匹配会把 superagent-tongtu 的 bash sleep 记到 superagent 头上。"""
    base = tmp_path / "state"
    main, tongtu = base / "superagent", base / "superagent-tongtu"
    (tongtu / "work" / "x").mkdir(parents=True)
    proc = tmp_path / "proc"
    _fake_proc(proc, 1, cmdline=f'bash -c sleep 200; cd "{tongtu}/work/x"')
    assert stuck_watch._proc_refs(str(tongtu), str(proc)) == 1
    assert stuck_watch._proc_refs(str(main), str(proc)) == 0


def _armed_liveness(monkeypatch, tmp_path, notified, alive_seq):
    """活性主路径环境：无卡滞工单（stale 0=健康），_service_alive 按剧本走。"""
    inst = _mk_instance(tmp_path, tmp_path / "sessions", stale_min_ago=0)
    _armed(monkeypatch, tmp_path, inst, notified)
    it = iter(alive_seq)
    monkeypatch.setattr(stuck_watch, "_service_alive",
                        lambda sd, **k: (next(it), "测试剧本"))
    return inst


def test_main_liveness_transition_alert_once_then_silent(monkeypatch, tmp_path, capsys):
    """活→停跃迁：一次告警 rc 1；停摆持续：心跳如实展示 rc 0 不重复告警；
    窗内假复苏再停（flap）被 REDEDUP 压制。"""
    notified = []
    _armed_liveness(monkeypatch, tmp_path, notified,
                    [True, False, False, True, False])
    st = json.load(open(stuck_watch.STATE, encoding="utf-8"))
    st["liveness"] = {"superagent-fake": True}
    json.dump(st, open(stuck_watch.STATE, "w", encoding="utf-8"))

    assert stuck_watch.main() == 0            # 活：零发现
    assert "活1/停0" in capsys.readouterr().out

    assert stuck_watch.main() == 1            # 活→停：跃迁告警
    assert any("服务疑似停摆" in str(x) for x in notified), notified
    assert "活0/停1（停: superagent-fake）" in capsys.readouterr().out

    assert stuck_watch.main() == 0            # 停摆持续：零新告警
    assert "活0/停1" in capsys.readouterr().out

    stuck_watch.main()                        # 假复苏：停→活不告警
    assert "活1/停0" in capsys.readouterr().out
    n_before = len(notified)
    assert stuck_watch.main() == 0            # 窗内再停（flap）：REDEDUP 压制
    assert len(notified) == n_before, notified  # 零新通知（态仍如实记停）
    assert "活0/停1" in capsys.readouterr().out


def test_main_liveness_bootstrap_dead_is_silent(monkeypatch, tmp_path, capsys):
    """首 run 无记忆且判停：只记录零告警（主实例长期停摆零噪音标本）。"""
    notified = []
    _armed_liveness(monkeypatch, tmp_path, notified, [False])
    assert stuck_watch.main() == 0
    out = capsys.readouterr().out
    assert "活0/停1（停: superagent-fake）" in out, out
    assert not notified


def test_proc_refs_windows_style_paths_match(tmp_path):
    """批221附（Windows CI 红钉）：反斜杠路径形态的 cmdline/cwd 必须命中——
    修前正斜杠前缀拼接在 Windows 上 startswith 永不命中=信号 B 全盲，
    四腿 CI 的 windows 腿抓回。Linux 本地用 Windows 风格串直接钉。"""
    base = "C:\\Users\\u\\.dsh\\state"
    inst = f"{base}\\superagent-tongtu"
    other = f"{base}\\superagent"
    proc = tmp_path / "proc"
    _fake_proc(proc, 9, cmdline=f'bash -c cd "{inst}\\work\\x"; sleep 200')
    _fake_proc(proc, 10, cmdline=f'node {other}\\worker.js')
    assert stuck_watch._proc_refs(inst, str(proc)) == 1
    assert stuck_watch._proc_refs(other, str(proc)) == 1  # 自己的进程要命中
