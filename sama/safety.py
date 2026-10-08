"""Safety layer: every tool call is classified before it runs.

SAFE    -> runs immediately (read-only)
CONFIRM -> needs explicit user approval (in "auto" mode only DANGEROUS ones ask)
BLOCKED -> never runs
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

SAFE, CONFIRM, BLOCKED = "safe", "confirm", "blocked"

READ_ONLY_TOOLS = {"list_dir", "read_file", "system_info", "screenshot", "look", "recall"}
STATE_TOOLS = {"write_file", "open_app", "run_shell", "mouse_click", "type_text", "hotkey", "remember"}

# Commands that must never run, however the model phrases them.
BLOCKED_SHELL = [
    r"\bformat\s+[a-z]:", r"\bdiskpart\b", r"\bbcdedit\b", r"\bvssadmin\b.*delete",
    r"\bcipher\s+/w", r"\breg\s+(delete|add)\s+hk(lm|ey_local_machine)", r"\bshutdown\b",
    r"\bdel\s+.*(/s|/q).*[a-z]:\\(windows|users)\b", r"\brd\s+/s\b.*[a-z]:\\(windows)?\s*$",
    r"remove-item\s+.*-recurse.*[a-z]:\\\s*$", r"\brm\s+-rf\s+/(\s|$)", r"\bmkfs\b", r"\bnet\s+user\b",
    r"invoke-expression|\biex\b.*(downloadstring|http)", r"\bcurl\b.*\|\s*(sh|bash|iex)",
]
# Always asks even in "auto" mode.
DANGEROUS_SHELL = [r"\bdel\b", r"\berase\b", r"\brmdir\b", r"\brd\b", r"remove-item", r"\bmove\b",
                   r"\bstop-process\b", r"\btaskkill\b", r"\bpip\s+install\b", r"\bwinget\b",
                   r"\bsc\s+(stop|delete)\b", r"\bpowershell\b.*-enc"]


def resolve_in_roots(path: str, roots) -> Path:
    """Return the resolved path, or raise PermissionError if it escapes the allowed roots."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(roots[0]) / p
    p = p.resolve()
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
            return p
        except ValueError:
            continue
    raise PermissionError(f"المسار خارج المجلدات المسموحة: {p}")


class Decision:
    def __init__(self, level, reason=""):
        self.level, self.reason = level, reason


class Safety:
    def __init__(self, config, audit_path: Path):
        self.cfg = config
        self.audit_path = audit_path
        self.stop_event = threading.Event()  # kill switch
        self._pending = {}
        self._lock = threading.Lock()

    # ---- classification -------------------------------------------------
    def classify(self, tool: str, args: dict) -> Decision:
        if tool not in READ_ONLY_TOOLS | STATE_TOOLS:
            return Decision(BLOCKED, f"أداة غير معروفة: {tool}")
        try:
            for key in ("path",):
                if key in args and tool in ("list_dir", "read_file", "write_file"):
                    resolve_in_roots(str(args[key]), self.cfg.allowed_roots)
        except PermissionError as e:
            return Decision(BLOCKED, str(e))
        if tool == "run_shell":
            cmd = str(args.get("command", "")).lower()
            for pat in BLOCKED_SHELL:
                if re.search(pat, cmd):
                    return Decision(BLOCKED, "أمر خطير ممنوع نهائياً")
            if any(re.search(p, cmd) for p in DANGEROUS_SHELL):
                return Decision(CONFIRM, "أمر قد يحذف/يعدّل النظام")
            return Decision(CONFIRM, "تنفيذ أمر في الطرفية")
        if tool in READ_ONLY_TOOLS:
            return Decision(SAFE)
        if self.cfg.mode == "auto" and tool in ("write_file", "open_app", "remember"):
            return Decision(SAFE)
        return Decision(CONFIRM, "إجراء يغيّر حالة الجهاز")

    # ---- approvals ------------------------------------------------------
    def ask(self, tool, args, reason) -> bool:
        aid = uuid.uuid4().hex[:8]
        ev = threading.Event()
        with self._lock:
            self._pending[aid] = {"id": aid, "tool": tool, "args": args, "reason": reason, "ok": False, "event": ev}
        deadline = time.time() + self.cfg.approval_timeout
        while time.time() < deadline and not self.stop_event.is_set():
            if ev.wait(0.25):
                break
        with self._lock:
            item = self._pending.pop(aid)
        return bool(item["ok"]) and ev.is_set()

    def answer(self, aid, ok) -> bool:
        with self._lock:
            item = self._pending.get(aid)
            if not item:
                return False
            item["ok"] = bool(ok)
            item["event"].set()
            return True

    def pending(self):
        with self._lock:
            return [{k: v for k, v in i.items() if k != "event"} for i in self._pending.values()]

    # ---- audit ----------------------------------------------------------
    def audit(self, **rec):
        rec["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
