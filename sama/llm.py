"""Local LLM client (Ollama). No cloud, no API keys."""
import json
import urllib.request


class LLM:
    def __init__(self, config):
        self.cfg = config

    def chat(self, messages) -> str:
        body = json.dumps({"model": self.cfg.model, "messages": messages, "stream": False,
                           "format": "json", "options": {"temperature": 0.1}}).encode()
        req = urllib.request.Request(self.cfg.ollama_url + "/api/chat", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.cfg.llm_timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def vision(self, image_path, question) -> str:
        """Ask the local vision model about an image (never leaves the machine)."""
        import base64
        img = base64.b64encode(open(image_path, "rb").read()).decode()
        body = json.dumps({"model": self.cfg.vision_model, "stream": False,
                           "messages": [{"role": "user", "content": question, "images": [img]}]}).encode()
        req = urllib.request.Request(self.cfg.ollama_url + "/api/chat", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.cfg.llm_timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def available(self) -> bool:
        try:
            urllib.request.urlopen(self.cfg.ollama_url + "/api/tags", timeout=2)
            return True
        except Exception:
            return False
