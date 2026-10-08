"""Tools the agent may call. GUI libraries are imported lazily so the core works headless."""
import os
import platform
import subprocess
from pathlib import Path

from .safety import resolve_in_roots

MAX_OUT = 4000


class Tools:
    def __init__(self, config, memory, shots_dir: Path):
        self.cfg, self.mem, self.shots_dir = config, memory, shots_dir

    def specs(self) -> str:
        return """\
list_dir(path)                      - list files in a folder
read_file(path)                     - read a text file
write_file(path, content)           - create/overwrite a text file
open_app(name)                      - open an app or file/URL (e.g. notepad, calc, https://...)
run_shell(command)                  - run a PowerShell/cmd command, returns output
screenshot()                        - save a screenshot, returns its path
mouse_click(x, y)                   - click at screen coordinates
type_text(text)                     - type text into the focused window
hotkey(keys)                        - press a combo, e.g. "ctrl+s"
system_info()                       - OS, CPU, RAM, disk info
remember(key, value) / recall(query) - long-term memory"""

    def call(self, name, args):
        fn = getattr(self, f"t_{name}", None)
        if not fn:
            raise ValueError(f"unknown tool {name}")
        out = fn(**args)
        out = out if isinstance(out, str) else str(out)
        return out[:MAX_OUT] + ("\n...[truncated]" if len(out) > MAX_OUT else "")

    # ---- files ----
    def _p(self, path):
        return resolve_in_roots(path, self.cfg.allowed_roots)

    def t_list_dir(self, path="."):
        p = self._p(path)
        return "\n".join(f"{'[D]' if c.is_dir() else '[F]'} {c.name}" for c in sorted(p.iterdir())) or "(empty)"

    def t_read_file(self, path):
        return self._p(path).read_text(encoding="utf-8", errors="replace")

    def t_write_file(self, path, content):
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"written {len(content)} chars to {p}"

    # ---- system ----
    def t_open_app(self, name):
        if platform.system() == "Windows":
            os.startfile(name)  # noqa: S606 (user-approved)
        else:
            subprocess.Popen(["xdg-open", name])
        return f"opened {name}"

    def t_run_shell(self, command):
        if platform.system() == "Windows":
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            argv = ["bash", "-c", command]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                           cwd=self.cfg.allowed_roots[0], errors="replace")
        return f"exit={r.returncode}\n{r.stdout}{r.stderr}"

    def t_system_info(self):
        info = {"os": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count()}
        try:
            import psutil
            info["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
            info["disk_free_gb"] = round(psutil.disk_usage(str(Path.home())).free / 2**30, 1)
        except ImportError:
            pass
        return info

    # ---- GUI ----
    def _gui(self):
        import pyautogui
        pyautogui.FAILSAFE = True  # slam mouse into a corner = abort
        pyautogui.PAUSE = 0.2
        return pyautogui

    def t_screenshot(self):
        p = self.shots_dir / f"shot_{int(__import__('time').time())}.png"
        self._gui().screenshot(str(p))
        return str(p)

    def t_mouse_click(self, x, y):
        self._gui().click(int(x), int(y))
        return f"clicked {x},{y}"

    def t_type_text(self, text):
        self._gui().write(text, interval=0.02)
        return "typed"

    def t_hotkey(self, keys):
        self._gui().hotkey(*[k.strip() for k in str(keys).split("+")])
        return f"pressed {keys}"

    # ---- memory ----
    def t_remember(self, key, value):
        self.mem.remember(key, value)
        return "saved"

    def t_recall(self, query=""):
        return self.mem.recall(query) or "nothing found"
