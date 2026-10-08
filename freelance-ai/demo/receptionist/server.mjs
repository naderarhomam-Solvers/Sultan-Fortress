// Zero-dependency demo server: POST /api/chat {messages:[{role,content}]} -> {reply, trace}
// Uses Anthropic Messages API when ANTHROPIC_API_KEY is set; otherwise a tiny scripted mock so the UI is testable offline.
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { createStore, toolDefs, systemPrompt } from "./tools.mjs";

const dir = fileURLToPath(new URL(".", import.meta.url));
const configPath = process.env.CLIENT_CONFIG || join(dir, "clinic.example.json");
export const config = JSON.parse(await readFile(configPath, "utf8"));
const store = createStore(config);
const MODEL = process.env.CLAUDE_MODEL || "claude-sonnet-5-5";
const KEY = process.env.ANTHROPIC_API_KEY;
export const MODE = KEY ? "claude" : "mock";
const MAX_TURNS = 6;

async function callClaude(messages) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model: MODEL, max_tokens: 800, system: systemPrompt(config), tools: toolDefs, messages }),
  });
  if (!res.ok) throw new Error(`Anthropic API ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function chat(history) {
  const trace = [];
  const messages = history.map((m) => ({ role: m.role, content: m.content }));
  if (!KEY) return mockChat(messages, trace);
  for (let i = 0; i < MAX_TURNS; i++) {
    const out = await callClaude(messages);
    const uses = out.content.filter((b) => b.type === "tool_use");
    if (out.stop_reason !== "tool_use" || !uses.length) {
      return { reply: out.content.filter((b) => b.type === "text").map((b) => b.text).join("\n"), trace };
    }
    messages.push({ role: "assistant", content: out.content });
    const results = uses.map((u) => {
      const result = store.run(u.name, u.input);
      trace.push({ tool: u.name, input: u.input, result });
      return { type: "tool_result", tool_use_id: u.id, content: JSON.stringify(result) };
    });
    messages.push({ role: "user", content: results });
  }
  return { reply: "عذرًا، سأحوّلك إلى موظف الاستقبال. / Sorry, let me hand you to our staff.", trace };
}

function mockChat(messages, trace) {
  const last = String(messages.at(-1)?.content ?? "");
  const risky = config.handoff.triggers.some((t) => last.toLowerCase().includes(t.toLowerCase()));
  if (risky) {
    const r = store.run("handoff_to_human", { reason: "trigger word", customer_summary: last.slice(0, 200) });
    trace.push({ tool: "handoff_to_human", result: r });
    return { reply: "[وضع تجريبي بدون مفتاح] تم تحويلك لموظف الاستقبال وسيتواصل معك قريبًا.", trace };
  }
  const svc = config.services.map((s) => `${s.name} (${s.price})`).join("، ");
  return { reply: `[وضع تجريبي بدون مفتاح API] أهلًا بك في ${config.business_name}. خدماتنا: ${svc}. كيف أساعدك؟`, trace };
}

const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css" };
const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "POST" && req.url === "/api/chat") {
      let body = "";
      for await (const c of req) { body += c; if (body.length > 50_000) throw new Error("payload too large"); }
      const { messages } = JSON.parse(body);
      if (!Array.isArray(messages) || !messages.length) throw new Error("messages required");
      const out = await chat(messages.slice(-20));
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      return res.end(JSON.stringify(out));
    }
    if (req.method === "GET" && req.url === "/api/state") {
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify({ bookings: store.bookings, handoffs: store.handoffs, mode: KEY ? "claude" : "mock" }));
    }
    const path = req.url === "/" ? "/index.html" : req.url.split("?")[0];
    const file = normalize(join(dir, "public", path));
    if (!file.startsWith(join(dir, "public"))) { res.writeHead(403); return res.end(); }
    const data = await readFile(file);
    res.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" });
    res.end(data);
  } catch (e) {
    const notFound = e.code === "ENOENT";
    res.writeHead(notFound ? 404 : 500, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: notFound ? "not found" : String(e.message) }));
  }
});

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = process.env.PORT || 3000;
  server.listen(port, () => console.log(`Receptionist demo on http://localhost:${port} (${KEY ? "Claude " + MODEL : "MOCK mode — set ANTHROPIC_API_KEY"})`));
}
