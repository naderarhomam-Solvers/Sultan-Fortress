"""Settings. Override with %APPDATA%/Sama/config.json (or ~/.sama/config.json)."""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "Sama" if base else Path.home() / ".sama"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Config:
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b-instruct"
    max_steps: int = 15
    llm_timeout: int = 180
    approval_timeout: int = 120
    port: int = 0  # 0 = pick a free port
    # Files may only be touched inside these roots.
    allowed_roots: list = field(default_factory=lambda: [str(Path.home() / "SamaWorkspace")])
    # "ask" = confirm every state-changing action, "auto" = only confirm dangerous ones.
    mode: str = "ask"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        p = data_dir() / "config.json"
        if p.exists():
            for k, v in json.loads(p.read_text(encoding="utf-8")).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        else:
            p.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
        for r in cfg.allowed_roots:
            Path(r).mkdir(parents=True, exist_ok=True)
        return cfg
