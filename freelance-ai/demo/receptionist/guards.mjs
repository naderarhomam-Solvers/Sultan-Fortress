// Input validation and cost/abuse limits shared by the web and WhatsApp channels.
const bad = (msg) => Object.assign(new Error(msg), { status: 400 });

/** Accept only plain user/assistant text from the client; never trust tool blocks or system roles. */
export function sanitizeHistory(messages, { maxMessages = 20, maxLen = 2000 } = {}) {
  if (!Array.isArray(messages) || !messages.length) throw bad("messages required");
  const out = messages.slice(-maxMessages).map((m) => {
    if (!m || (m.role !== "user" && m.role !== "assistant") || typeof m.content !== "string") throw bad("invalid message");
    return { role: m.role, content: m.content.slice(0, maxLen) };
  });
  while (out.length && out[0].role !== "user") out.shift(); // API requires the first turn to be the user's
  if (!out.length || out.at(-1).role !== "user") throw bad("last message must be from the user");
  if (!out.at(-1).content.trim()) throw bad("empty message");
  return out;
}

/** Per-key per-minute limit plus a global daily cap that bounds API spend. Returns check(key) -> boolean. */
export function createLimiter({ perMinute = 20, perDay = 500, now = Date.now } = {}) {
  const hits = new Map();
  let day = { d: Math.floor(now() / 86400000), n: 0 };
  return (key) => {
    const t = now();
    const d = Math.floor(t / 86400000);
    if (day.d !== d) day = { d, n: 0 };
    if (day.n >= perDay) return false;
    if (hits.size > 10_000) hits.clear();
    const recent = (hits.get(key) || []).filter((x) => t - x < 60_000);
    if (recent.length >= perMinute) { hits.set(key, recent); return false; }
    recent.push(t); hits.set(key, recent); day.n++;
    return true;
  };
}
