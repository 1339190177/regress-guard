"""人类介入通知（v1.30）：正负路径——通道参数化/事件开关/best-effort/test 事件。"""
import json
import os
import stat
import subprocess
import sys

LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts", "lib"))
NOTIFY = os.path.join(LIB, "notify.py")


def _load():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("nt", NOTIFY)
    nt = ilu.module_from_spec(spec)
    spec.loader.exec_module(nt)
    return nt


def _mk(tmp_path, conf=None):
    proj = tmp_path / "proj"
    (proj / ".regress").mkdir(parents=True, exist_ok=True)
    if conf is not None:
        (proj / ".regress" / "config.json").write_text(
            json.dumps({"notify": conf}, ensure_ascii=False), encoding="utf-8")
    return proj


def _channel_stub(tmp_path, marker):
    stub = tmp_path / "stub.sh"
    stub.write_text("#!/bin/sh\necho \"$@\" >> %s\n" % marker, encoding="utf-8")
    stub.chmod(stat.S_IRWXU)
    return str(stub)


def test_channel_runs_with_quoted_placeholders(tmp_path):
    nt = _load()
    proj = _mk(tmp_path, {"channels": [_channel_stub(tmp_path, tmp_path / "m1") + " {title} {body}"]})
    assert nt.notify(str(proj), "plan_approval", "📋 待批准 REGRESS-1", "改动 3 文件") == 1
    out = (tmp_path / "m1").read_text(encoding="utf-8")  # body 带 🕐 换行，全文断言
    assert "待批准 REGRESS-1" in out and "改动 3 文件" in out


def test_project_name_prefix_and_time_suffix(tmp_path):
    """v1.31.2 格式统一：标题带【项目名】（cfg.name 优先于目录名），正文缀 🕐 时间。"""
    import re as _re
    nt = _load()
    proj = _mk(tmp_path, {"name": "会场助手",
                          "channels": [_channel_stub(tmp_path, tmp_path / "m7") + " {title} {body}"]})
    nt.notify(str(proj), "done", "🏁 完成 R1", "干净收尾")
    out = (tmp_path / "m7").read_text(encoding="utf-8")
    assert "【会场助手】🏁 完成 R1" in out
    assert _re.search(r"🕐 \d{2}-\d{2} \d{2}:\d{2}", out)
    # 无 name 配置 → 目录名兜底
    proj2 = tmp_path / "myproj"
    (proj2 / ".regress").mkdir(parents=True, exist_ok=True)
    (proj2 / ".regress" / "config.json").write_text(
        json.dumps({"notify": {"channels": [_channel_stub(tmp_path, tmp_path / "m8") + " {title} {body}"]}}),
        encoding="utf-8")
    nt.notify(str(proj2), "blocked", "🛑 受阻")
    assert "【myproj】🛑 受阻" in (tmp_path / "m8").read_text(encoding="utf-8")


def test_wecom_subprocess_receives_merged_conf(tmp_path, monkeypatch):
    """v1.31.4 回归：裸项目+机器级 wecom → 企微子进程必须真拿到合并配置（API 桩被命中）。
    病例：2026-09-05 合并只活在父进程，子进程只读项目文件 → 演示项目推送静默失败，
    而当时测试只断言了合并字典（oracle 宽松断言）。"""
    import http.server
    import importlib.util as ilu
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def _json(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            hits.append(self.path)
            self._json({"errcode": 0, "access_token": "T1", "expires_in": 7200})

        def do_POST(self):
            hits.append(self.path)
            self._json({"errcode": 0, "errmsg": "ok"})

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("WECOM_API_BASE", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("WECOM_TOKEN_DIR", str(tmp_path / "tk"))

    mach = tmp_path / "machine.json"
    mach.write_text(json.dumps({"notify": {
        "wecom": {"corpid": "wwM", "secret": "SM", "agentid": 1}}}), encoding="utf-8")
    monkeypatch.setenv("RG_MACHINE_NOTIFY", str(mach))

    nt = _load()
    bare = tmp_path / "bare"  # 项目级无任何 notify 配置
    (bare / ".regress").mkdir(parents=True, exist_ok=True)
    assert nt.notify(str(bare), "done", "跨项目") >= 1
    assert any("corpid=wwM" in h and "gettoken" in h for h in hits), \
        "企微子进程未拿到机器级合并配置（env 传递失效）"
    srv.shutdown()


def test_machine_fallback_and_keywise_merge(tmp_path, monkeypatch):
    """v1.31.3 两层合并：项目无 notify 块 → 机器级生效；项目按键覆盖（wecom 深合并）。"""
    import importlib
    mach = tmp_path / "machine.json"
    mach.write_text(json.dumps({"notify": {
        "name": "机器默认",
        "events": {"done": True, "blocked": True},
        "wecom": {"corpid": "wwM", "secret": "SM", "agentid": 1},
        "channels": [_channel_stub(tmp_path, tmp_path / "mm") + " {title}"],
    }}), encoding="utf-8")
    monkeypatch.setenv("RG_MACHINE_NOTIFY", str(mach))
    monkeypatch.setenv("WECOM_API_BASE", "http://127.0.0.1:1")  # 死端口：wecom 秒败 rc=2 不计数
    nt = _load()

    # 项目无 notify 块：机器级通道全量生效，name 用机器级
    bare = tmp_path / "bare"
    (bare / ".regress").mkdir(parents=True, exist_ok=True)
    assert nt.notify(str(bare), "done", "跨项目零配置") == 1
    out = (tmp_path / "mm").read_text(encoding="utf-8")
    assert "【机器默认】跨项目零配置" in out

    # 项目覆盖 name + 单个事件开关；wecom 深合并：agentid 覆盖、corpid 继承
    proj = _mk(tmp_path, {"name": "会场助手", "events": {"done": False},
                          "wecom": {"agentid": 9}})
    c = nt.load_conf(str(proj))
    assert c["name"] == "会场助手"
    assert c["events"]["done"] is False and c["events"]["blocked"] is True
    assert c["wecom"] == {"corpid": "wwM", "secret": "SM", "agentid": 9}
    assert nt.notify(str(proj), "done", "t") == 0  # 机器开、项目关 → 项目胜


def test_event_toggle_and_master_switch(tmp_path):
    nt = _load()
    stub = _channel_stub(tmp_path, tmp_path / "m2")
    proj = _mk(tmp_path, {"channels": [stub], "events": {"blocked": False}})
    assert nt.notify(str(proj), "blocked", "t") == 0
    proj2 = _mk(tmp_path, {"enabled": False, "channels": [stub]})
    assert nt.notify(str(proj2), "plan_approval", "t") == 0
    proj3 = _mk(tmp_path, {"channels": [stub]})
    assert nt.notify(str(proj3), "sensory", "t") == 1


def test_done_event_default_on_and_toggleable(tmp_path):
    """done（v1.31.1 离场召回）：存量配置无 done 键默认开；显式关掉则静默。"""
    nt = _load()
    stub = _channel_stub(tmp_path, tmp_path / "m6")
    proj = _mk(tmp_path, {"channels": [stub]})  # events 无 done 键
    assert nt.notify(str(proj), "done", "🏁 完成 R1") == 1
    proj2 = _mk(tmp_path, {"channels": [stub], "events": {"done": False}})
    assert nt.notify(str(proj2), "done", "t") == 0


def test_test_event_bypasses_toggles(tmp_path):
    """test 事件忽略事件开关——通道验收专用。"""
    nt = _load()
    stub = _channel_stub(tmp_path, tmp_path / "m5")
    proj = _mk(tmp_path, {"channels": [stub], "events": {"blocked": False, "sensory": False}})
    assert nt.notify(str(proj), "test", "🔔 通道测试") == 1


def test_failing_channel_never_raises(tmp_path):
    nt = _load()
    proj = _mk(tmp_path, {"channels": ["definitely-not-a-command-xyz {title}",
                                       _channel_stub(tmp_path, tmp_path / "m3")]})
    ran = nt.notify(str(proj), "finish_open", "t", "b")  # 不抛即过
    assert ran == 1


def test_cli_smoke(tmp_path):
    proj = _mk(tmp_path, {"channels": [_channel_stub(tmp_path, tmp_path / "m4") + " {title} {body}"]})
    r = subprocess.run([sys.executable, NOTIFY, str(proj), "blocked",
                        "--title", "🛑 受阻", "--body", "需要：白名单"],
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0
    assert "受阻" in (tmp_path / "m4").read_text(encoding="utf-8")


def test_wecom_push_roundtrip(tmp_path, monkeypatch):
    """企业微信推送全链（桩服务器）：gettoken→send，token 缓存生效，未配置降级。"""
    import http.server
    import importlib.util as ilu
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def _json(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            hits.append(("GET", self.path))
            self._json({"errcode": 0, "access_token": "T1", "expires_in": 7200})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            hits.append(("POST", self.path + " " + self.rfile.read(n).decode("utf-8")))
            self._json({"errcode": 0, "errmsg": "ok"})

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("WECOM_API_BASE", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("WECOM_TOKEN_DIR", str(tmp_path / "tk"))
    spec = ilu.spec_from_file_location(
        "wn", os.path.join(LIB, "wecom_notify.py"))
    wn = ilu.module_from_spec(spec)
    spec.loader.exec_module(wn)
    proj = _mk(tmp_path, {"wecom": {"corpid": "wwX", "secret": "S",
                                    "agentid": 1000002, "touser": "@all"}})
    assert wn.main([str(proj), "📋 待批准 R1", "改动 3 文件"]) == 0
    assert any("gettoken" in h[1] for h in hits)
    posts = [h for h in hits if h[0] == "POST"]
    assert posts and "message/send" in posts[0][1] and "待批准 R1" in posts[0][1]
    # token 已缓存：第二次推送不再 GET
    hits.clear()
    wn.main([str(proj), "t2", "b2"])
    assert not any(h[0] == "GET" for h in hits)
    # 未配置项目：exit 1 不炸
    empty = tmp_path / "empty"
    (empty / ".regress").mkdir(parents=True, exist_ok=True)
    assert wn.main([str(empty), "t", "b"]) == 1


def test_wecom_proxy_roundtrip(tmp_path, monkeypatch):
    """proxy 配置（v1.30.1 可信IP中转）：流量必须真的过代理——错凭据 407 时桩不得被触达。"""
    import http.server
    import importlib.util as ilu
    import socket
    import subprocess
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def _json(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            hits.append(("GET", self.path))
            self._json({"errcode": 0, "access_token": "T1", "expires_in": 7200})

        def do_POST(self):
            hits.append(("POST", self.path))
            self._json({"errcode": 0, "errmsg": "ok"})

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    px_port = s.getsockname()[1]
    s.close()
    proxy = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "..", "deploy", "vps_proxy.py"),
         str(px_port), "u1", "p1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    import time
    for _ in range(50):  # 等代理完成 bind（Popen 后立即连会拒连）
        try:
            socket.create_connection(("127.0.0.1", px_port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)

    try:
        monkeypatch.setenv("WECOM_API_BASE", f"http://127.0.0.1:{srv.server_port}")
        spec = ilu.spec_from_file_location("wn2", os.path.join(LIB, "wecom_notify.py"))
        wn = ilu.module_from_spec(spec)
        spec.loader.exec_module(wn)
        base = {"corpid": "wwX", "secret": "S", "agentid": 1000002, "touser": "@all"}

        # 正确凭据：过代理送达桩
        monkeypatch.setenv("WECOM_TOKEN_DIR", str(tmp_path / "tk_ok"))
        proj = _mk(tmp_path, {"wecom": dict(base, proxy=f"http://u1:p1@127.0.0.1:{px_port}")})
        assert wn.main([str(proj), "t", "b"]) == 0
        assert any("gettoken" in h[1] for h in hits) and \
            any(h[0] == "POST" and "message/send" in h[1] for h in hits)

        # 错误凭据：代理 407，请求到不了桩（证明确实走了代理）
        hits.clear()
        monkeypatch.setenv("WECOM_TOKEN_DIR", str(tmp_path / "tk_bad"))
        proj2 = _mk(tmp_path, {"wecom": dict(base, proxy=f"http://u1:bad@127.0.0.1:{px_port}")})
        assert wn.main([str(proj2), "t", "b"]) == 2  # best-effort 不炸；rc=2=推送失败不计通道数
        assert not hits
    finally:
        proxy.terminate()
        srv.shutdown()
