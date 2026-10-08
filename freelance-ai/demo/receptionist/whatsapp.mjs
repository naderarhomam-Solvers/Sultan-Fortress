// WhatsApp Cloud API (Meta) adapter. The CLIENT owns the Meta business account, phone number and tokens.
import crypto from "node:crypto";

export function verifySignature(rawBody, header, appSecret) {
  if (!appSecret || !header || !header.startsWith("sha256=")) return false;
  const expected = crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  const got = header.slice(7);
  return got.length === expected.length && crypto.timingSafeEqual(Buffer.from(got), Buffer.from(expected));
}

/** GET /webhook subscription handshake. Returns the challenge string to echo, or null. */
export function verifyChallenge(params, token) {
  if (token && params.get("hub.mode") === "subscribe" && params.get("hub.verify_token") === token) return params.get("hub.challenge");
  return null;
}

export function extractMessages(payload) {
  const out = [];
  for (const entry of payload?.entry ?? []) for (const ch of entry.changes ?? []) for (const m of ch.value?.messages ?? []) {
    out.push({ id: m.id, from: m.from, type: m.type, text: m.type === "text" ? m.text?.body ?? "" : "" });
  }
  return out;
}

export function makeSender({ token, phoneId, fetchImpl = fetch }) {
  return async (to, body) => {
    const res = await fetchImpl(`https://graph.facebook.com/v21.0/${phoneId}/messages`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify({ messaging_product: "whatsapp", to, type: "text", text: { body } }),
    });
    if (!res.ok) throw new Error(`WhatsApp send ${res.status}: ${await res.text()}`);
  };
}

const NON_TEXT = "عذرًا، أستطيع قراءة الرسائل النصية فقط حاليًا. اكتب لي طلبك وسأساعدك 🌿 / Sorry, I can only read text messages.";
const BUSY = "عذرًا، حدث خطأ مؤقت. سيتواصل معك أحد موظفينا قريبًا. / Sorry, a temporary error occurred; our staff will contact you.";

export function createWhatsAppHandler({ chat, send, notifyStaff, limiter = () => true, ttlMs = 24 * 3600_000, now = Date.now, log = console.error }) {
  const sessions = new Map();
  const seen = new Set();
  return async function handle(payload) {
    for (const m of extractMessages(payload)) {
      if (seen.has(m.id)) continue; // Meta retries deliveries
      seen.add(m.id); if (seen.size > 5000) seen.clear();
      try {
        if (m.type !== "text" || !m.text.trim()) { await send(m.from, NON_TEXT); continue; }
        if (!limiter(m.from)) continue; // silently drop floods; never spend API budget on them
        let s = sessions.get(m.from);
        if (!s || now() - s.ts > ttlMs) s = { ts: now(), messages: [] };
        s.messages.push({ role: "user", content: m.text.slice(0, 2000) });
        s.messages = s.messages.slice(-20);
        while (s.messages[0]?.role !== "user") s.messages.shift();
        const out = await chat(s.messages, { channel: "whatsapp", sender: m.from });
        s.messages.push({ role: "assistant", content: out.reply }); s.ts = now();
        sessions.set(m.from, s);
        await send(m.from, out.reply);
        const h = out.trace.find((t) => t.tool === "handoff_to_human");
        if (h && notifyStaff) await notifyStaff(`تحويل من ${m.from}: ${h.input?.reason ?? ""} — ${h.input?.customer_summary ?? ""}`);
      } catch (e) {
        log("whatsapp handler error:", e.message);
        try { await send(m.from, BUSY); } catch {}
      }
    }
  };
}
