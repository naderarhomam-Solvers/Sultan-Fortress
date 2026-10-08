// Zero-dependency demo server: POST /api/chat {messages:[{role,content}]} -> {reply, trace}
// Uses Anthropic Messages API when ANTHROPIC_API_KEY is set; otherwise a tiny scripted mock so the UI is testable offline.
import http from "node:http";
import { readFile, appendFile } from "node:fs/promises";
import { createHash, timingSafeEqual } from "node:crypto";
import { extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { createStore, toolDefs, systemPrompt } from "./tools.mjs";
import { sanitizeHistory, createLimiter } from "./guards.mjs";
import { verifySignature, verifyChallenge, makeSender, createWhatsAppHandler } from "./whatsapp.mjs";

const dir = fileURLToPath(new URL(".", import.meta.url));
const configPath = process.env.CLIENT_CONFIG || join(dir, "clinic.example.json");
export const config = JSON.parse(await readFile(configPath, "utf8"));
const store = createStore(config);
const MODEL = process.env.CLAUDE_MODEL || "claude-sonnet-5-5";
const KEY = process.env.ANTHROPIC_API_KEY;
export const MODE = KEY ? "claude" : "mock";
const MAX_TURNS = 6;
const FALLBACK_REPLY = "عذرًا، حدث خطأ مؤقت. سيتواصل معك أحد موظفينا قريبًا. / Sorry, a temporary error occurred; our staff will contact you.";

async function callClaude(messages) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model: MODEL, max_tokens: 800, system: systemPrompt(config), tools: toolDefs, messages }),
    signal: AbortSignal.timeout(Number(process.env.API_TIMEOUT_MS) || 25_000), // a hung upstream must not hang the customer
  });
  if (!res.ok) throw new Error(`Anthropic API ${res.status}: ${await res.text()}`);
  return res.json();
}

const LOG_FILE = process.env.LOG_FILE; // JSONL conversation log (retention is agreed with the client)
const anon = (v) => (v ? createHash("sha256").update(String(v)).digest("hex").slice(0, 10) : undefined);
async function logTurn(meta, history, out) {
  if (!LOG_FILE) return;
  const entry = { ts: new Date().toISOString(), channel: meta.channel ?? "web", sender: anon(meta.sender), user: history.at(-1)?.content, reply: out.reply, tools: out.trace.map((t) => ({ tool: t.tool, input: t.input, ok: !t.result?.error })) };
  try { await appendFile(LOG_FILE, JSON.stringify(entry) + "\n"); } catch (e) { console.error("log failed:", e.message); }
}

export async function chat(history, meta = {}) {
  const out = await chatInner(history);
  await logTurn(meta, history, out);
  return out;
}

async function chatInner(history) {
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
const limiter = createLimiter({ perMinute: Number(process.env.RATE_PER_MIN) || 15, perDay: Number(process.env.DAILY_CAP) || 500 });
const clientIp = (req) => (process.env.TRUST_PROXY === "1" ? String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() : "") || req.socket.remoteAddress || "?";
const same = (a, b) => { const x = Buffer.from(String(a ?? "")), y = Buffer.from(String(b ?? "")); return x.length === y.length && x.length > 0 && timingSafeEqual(x, y); };
const json = (res, code, obj) => { res.writeHead(code, { "content-type": "application/json; charset=utf-8" }); res.end(JSON.stringify(obj)); };

async function readBody(req, max) {
  let body = "";
  for await (const c of req) { body += c; if (body.length > max) throw Object.assign(new Error("payload too large"), { status: 413 }); }
  return body;
}

const WA = process.env.WHATSAPP_TOKEN && process.env.WHATSAPP_PHONE_ID
  ? createWhatsAppHandler({
      chat, limiter,
      send: makeSender({ token: process.env.WHATSAPP_TOKEN, phoneId: process.env.WHATSAPP_PHONE_ID }),
      // Staff alerts only work inside WhatsApp's 24h window (staff must have messaged this number) - see docs/DEPLOY.md
      notifyStaff: process.env.STAFF_WHATSAPP ? makeSender({ token: process.env.WHATSAPP_TOKEN, phoneId: process.env.WHATSAPP_PHONE_ID }).bind(null, process.env.STAFF_WHATSAPP) : undefined,
    })
  : null;

export const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    if (req.method === "POST" && url.pathname === "/api/chat") {
      if (!limiter(clientIp(req))) return json(res, 429, { error: "too many requests" });
      const { messages } = JSON.parse(await readBody(req, 50_000));
      const history = sanitizeHistory(messages); // 400 on bad input, before any upstream call
      try {
        return json(res, 200, await chat(history, { channel: "web", sender: clientIp(req) }));
      } catch (e) { // upstream failure/timeout: degrade to a safe human-handoff message instead of a 500
        console.error("chat failed:", e.message);
        return json(res, 200, { reply: FALLBACK_REPLY, trace: [], degraded: true });
      }
    }
    if (req.method === "GET" && url.pathname === "/api/state") return json(res, 200, { mode: MODE });
    if (req.method === "GET" && url.pathname === "/api/admin/state") {
      if (!process.env.ADMIN_TOKEN || !same(req.headers["x-admin-token"], process.env.ADMIN_TOKEN)) return json(res, 401, { error: "unauthorized" });
      return json(res, 200, { mode: MODE, bookings: store.bookings, handoffs: store.handoffs });
    }
    if (url.pathname === "/webhook") {
      if (req.method === "GET") {
        const c = verifyChallenge(url.searchParams, process.env.WHATSAPP_VERIFY_TOKEN);
        if (c === null) { res.writeHead(403); return res.end(); }
        res.writeHead(200, { "content-type": "text/plain" }); return res.end(c);
      }
      if (req.method === "POST") {
        const raw = await readBody(req, 200_000);
        if (!WA || !verifySignature(raw, req.headers["x-hub-signature-256"], process.env.WHATSAPP_APP_SECRET)) { res.writeHead(WA ? 401 : 503); return res.end(); }
        res.writeHead(200); res.end(); // ack fast; Meta retries slow responses
        WA(JSON.parse(raw)).catch((e) => console.error("webhook:", e.message));
        return;
      }
    }
    if (req.method !== "GET") return json(res, 405, { error: "method not allowed" });
    const path = url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname);
    const file = normalize(join(dir, "public", path));
    if (!file.startsWith(join(dir, "public") + sep)) { res.writeHead(403); return res.end(); }
    const data = await readFile(file);
    res.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" });
    res.end(data);
  } catch (e) {
    const status = e.status || (e.code === "ENOENT" || e.code === "EISDIR" ? 404 : e instanceof SyntaxError ? 400 : 500);
    if (status === 500) console.error(e);
    json(res, status, { error: status === 500 ? "internal error" : e.code === "ENOENT" ? "not found" : String(e.message) });
  }
});

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = process.env.PORT || 3000;
  server.listen(port, () => console.log(`Receptionist demo on http://localhost:${port} (${KEY ? "Claude " + MODEL : "MOCK mode — set ANTHROPIC_API_KEY"})`));
}
