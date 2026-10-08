"""Entry point: python -m sama  (opens a native window if pywebview is installed)."""
import threading

from .agent import Agent
from .config import Config, data_dir
from .llm import LLM
from .memory import Memory
from .safety import Safety
from .server import make_server
from .tools import Tools


def main():
    cfg, d = Config.load(), data_dir()
    shots = d / "shots"
    shots.mkdir(exist_ok=True)
    mem = Memory(d / "memory.db")
    safety = Safety(cfg, d / "audit.jsonl")
    llm = LLM(cfg)
    agent = Agent(cfg, llm, Tools(cfg, mem, shots, llm), safety, mem)
    server, _ = make_server(agent, safety, llm, cfg.port)
    url = f"http://127.0.0.1:{server.server_port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Sama running at", url)
    try:
        import webview
        webview.create_window("Sama | سما", url, width=1000, height=700)
        webview.start()
    except ImportError:
        import webbrowser
        webbrowser.open(url)
        threading.Event().wait()


if __name__ == "__main__":
    main()
