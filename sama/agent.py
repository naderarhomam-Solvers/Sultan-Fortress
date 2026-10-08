"""ReAct-style agent loop: model proposes one tool call per step; Safety gates it."""
import json
import re
import threading
import time

from .safety import SAFE, BLOCKED

SYSTEM = """You are Sama, a local assistant that operates the user's Windows PC.
Work step by step. Reply with ONE JSON object only, either:
  {"thought": "short reasoning", "tool": "<name>", "args": {...}}
or, when the goal is done or impossible:
  {"final": "answer to the user, in the user's language"}
Never invent results; use a tool and read its output. Prefer the least invasive tool.
If a tool is refused or blocked, do not retry the same thing; explain or pick another way.
Available tools:
%s
Known facts about the user: %s"""


def parse_action(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


class Agent:
    def __init__(self, config, llm, tools, safety, memory):
        self.cfg, self.llm, self.tools, self.safety, self.mem = config, llm, tools, safety, memory
        self.events = []  # shown in the UI
        self.busy = False
        self._lock = threading.Lock()

    def emit(self, kind, text):
        self.events.append({"t": time.strftime("%H:%M:%S"), "kind": kind, "text": text})
        del self.events[:-200]

    def start(self, goal) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
        self.safety.stop_event.clear()
        threading.Thread(target=self._run, args=(goal,), daemon=True).start()
        return True

    def _run(self, goal):
        try:
            result = self.run(goal)
        except Exception as e:  # never crash the app loop
            result = f"خطأ: {e}"
        self.emit("final", result)
        self.mem.log_task(goal, result)
        self.busy = False

    def run(self, goal) -> str:
        self.emit("user", goal)
        msgs = [{"role": "system", "content": SYSTEM % (self.tools.specs(), self.mem.recall())},
                {"role": "user", "content": goal}]
        for _ in range(self.cfg.max_steps):
            if self.safety.stop_event.is_set():
                return "تم الإيقاف من المستخدم."
            raw = self.llm.chat(msgs)
            msgs.append({"role": "assistant", "content": raw})
            try:
                act = parse_action(raw)
            except Exception:
                msgs.append({"role": "user", "content": "Invalid JSON. Reply with one JSON object."})
                continue
            if "final" in act:
                return str(act["final"])
            tool, args = act.get("tool", ""), act.get("args") or {}
            self.emit("thought", act.get("thought", ""))
            obs = self._execute(tool, args)
            msgs.append({"role": "user", "content": f"Tool result:\n{obs}"})
        return "وصلت للحد الأقصى من الخطوات دون إكمال المهمة."

    def _execute(self, tool, args) -> str:
        d = self.safety.classify(tool, args)
        desc = f"{tool} {json.dumps(args, ensure_ascii=False)}"
        if d.level == BLOCKED:
            self.safety.audit(tool=tool, args=args, result="BLOCKED", reason=d.reason)
            self.emit("blocked", f"{desc} — {d.reason}")
            return f"BLOCKED: {d.reason}"
        if d.level != SAFE:
            self.emit("ask", desc)
            if not self.safety.ask(tool, args, d.reason):
                self.safety.audit(tool=tool, args=args, result="DENIED")
                self.emit("denied", desc)
                return "DENIED by user."
        try:
            out = self.tools.call(tool, args)
            self.safety.audit(tool=tool, args=args, result="OK")
            self.emit("tool", f"{desc}\n→ {out[:300]}")
            return out
        except Exception as e:
            self.safety.audit(tool=tool, args=args, result=f"ERROR {e}")
            self.emit("error", f"{desc} — {e}")
            return f"ERROR: {e}"
