import json
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from sama.agent import Agent
from sama.config import Config
from sama.memory import Memory
from sama.safety import BLOCKED, CONFIRM, SAFE, Safety
from sama.server import make_server
from sama.tools import Tools


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages):
        return json.dumps(self.replies.pop(0))

    def available(self):
        return True


@pytest.fixture
def env():
    d = Path(tempfile.mkdtemp())
    cfg = Config(allowed_roots=[str(d / "ws")], approval_timeout=3)
    Path(cfg.allowed_roots[0]).mkdir()
    mem = Memory(d / "m.db")
    safety = Safety(cfg, d / "audit.jsonl")
    return cfg, mem, safety, Tools(cfg, mem, d), d


def mk_agent(env, replies):
    cfg, mem, safety, tools, _ = env
    return Agent(cfg, FakeLLM(replies), tools, safety, mem)


def test_classify(env):
    s = env[2]
    assert s.classify("list_dir", {"path": "."}).level == SAFE
    assert s.classify("read_file", {"path": "/etc/passwd"}).level == BLOCKED
    assert s.classify("read_file", {"path": "../../x"}).level == BLOCKED
    assert s.classify("run_shell", {"command": "dir"}).level == CONFIRM
    assert s.classify("run_shell", {"command": "shutdown /s"}).level == BLOCKED
    assert s.classify("run_shell", {"command": "format C:"}).level == BLOCKED
    assert s.classify("hack_planet", {}).level == BLOCKED


def test_approved_write(env):
    a = mk_agent(env, [{"tool": "write_file", "args": {"path": "a.txt", "content": "hi"}}, {"final": "done"}])
    t = threading.Thread(target=lambda: setattr(a, "res", a.run("make file")))
    t.start()
    for _ in range(40):
        if env[2].pending():
            env[2].answer(env[2].pending()[0]["id"], True)
            break
        time.sleep(0.05)
    t.join()
    assert a.res == "done"
    assert (Path(env[0].allowed_roots[0]) / "a.txt").read_text() == "hi"
    assert "write_file" in (env[4] / "audit.jsonl").read_text()


def test_denied_write(env):
    a = mk_agent(env, [{"tool": "write_file", "args": {"path": "a.txt", "content": "hi"}}, {"final": "ok"}])
    t = threading.Thread(target=lambda: setattr(a, "res", a.run("x")))
    t.start()
    for _ in range(40):
        if env[2].pending():
            env[2].answer(env[2].pending()[0]["id"], False)
            break
        time.sleep(0.05)
    t.join()
    assert not (Path(env[0].allowed_roots[0]) / "a.txt").exists()


def test_approval_timeout_denies(env):
    env[0].approval_timeout = 1
    assert env[2].ask("run_shell", {"command": "dir"}, "x") is False


def test_blocked_never_asks(env):
    a = mk_agent(env, [{"tool": "run_shell", "args": {"command": "shutdown /s"}}, {"final": "no"}])
    assert a.run("x") == "no"
    assert not env[2].pending()


def test_kill_switch(env):
    env[2].stop_event.set()
    assert "الإيقاف" in mk_agent(env, []).run("x")


def test_server_auth(env):
    cfg, mem, safety, tools, _ = env
    agent = mk_agent(env, [])
    srv, token = make_server(agent, safety, FakeLLM([]), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/state")
    assert e.value.code == 403
    r = urllib.request.Request(base + "/api/state", headers={"X-Token": token})
    assert json.loads(urllib.request.urlopen(r).read())["busy"] is False
    assert token in urllib.request.urlopen(base + "/").read().decode()
    srv.shutdown()


def test_look_uses_vision(env):
    cfg, mem, safety, _, d = env

    class V(FakeLLM):
        def vision(self, path, q):
            return f"saw:{q}"

    t = Tools(cfg, mem, d, V([]))
    t.t_screenshot = lambda: "x.png"
    assert t.call("look", {"question": "where is OK?"}) == "saw:where is OK?"
    assert safety.classify("look", {}).level == SAFE
