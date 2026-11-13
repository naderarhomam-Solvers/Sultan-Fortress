import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { verifySignature, verifyChallenge, extractMessages, createWhatsAppHandler, makeSender } from "./whatsapp.mjs";

const payload = (msgs) => ({ entry: [{ changes: [{ value: { messages: msgs } }] }] });
const text = (id, from, body) => ({ id, from, type: "text", text: { body } });

test("signature: valid, tampered, missing secret/header", () => {
  const raw = '{"a":1}', sig = "sha256=" + crypto.createHmac("sha256", "s3").update(raw).digest("hex");
  assert.ok(verifySignature(raw, sig, "s3"));
  assert.ok(!verifySignature(raw + " ", sig, "s3"));
  assert.ok(!verifySignature(raw, sig, ""));
  assert.ok(!verifySignature(raw, undefined, "s3"));
  assert.ok(!verifySignature(raw, "sha256=abc", "s3"));
});
test("challenge handshake", () => {
  const p = new URLSearchParams({ "hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42" });
  assert.equal(verifyChallenge(p, "tok"), "42");
  assert.equal(verifyChallenge(p, "other"), null);
  assert.equal(verifyChallenge(p, undefined), null);
});
test("extractMessages tolerates odd payloads", () => {
  assert.deepEqual(extractMessages({}), []);
  assert.deepEqual(extractMessages({ entry: [{ changes: [{ value: { statuses: [] } }] }] }), []);
  assert.equal(extractMessages(payload([text("1", "9", "hi")]))[0].text, "hi");
});
test("handler: replies, keeps history, dedupes retries, handles non-text, notifies staff on handoff", async () => {
  const sent = [], staff = [], seenHistories = [];
  const chat = async (h) => { seenHistories.push(h.map((m) => m.content)); return h.at(-1).content.includes("ألم") ? { reply: "حولناك", trace: [{ tool: "handoff_to_human", input: { reason: "pain", customer_summary: "s" } }] } : { reply: "رد", trace: [] }; };
  const handle = createWhatsAppHandler({ chat, send: async (to, b) => sent.push([to, b]), notifyStaff: async (m) => staff.push(m) });
  await handle(payload([text("m1", "218911", "مرحبا")]));
  await handle(payload([text("m1", "218911", "مرحبا")])); // Meta retry
  await handle(payload([text("m2", "218911", "عندي ألم")]));
  await handle(payload([{ id: "m3", from: "218911", type: "image" }]));
  assert.deepEqual(sent.map((s) => s[1]).slice(0, 2), ["رد", "حولناك"]);
  assert.equal(sent.length, 3);
  assert.deepEqual(seenHistories[1], ["مرحبا", "رد", "عندي ألم"]);
  assert.equal(seenHistories.length, 2);
  assert.equal(staff.length, 1); assert.match(staff[0], /pain/);
});
test("handler: rate-limited senders get no reply; errors send a safe fallback", async () => {
  const sent = [];
  const h1 = createWhatsAppHandler({ chat: async () => ({ reply: "x", trace: [] }), send: async (...a) => sent.push(a), limiter: () => false });
  await h1(payload([text("a", "1", "hi")])); assert.equal(sent.length, 0);
  const h2 = createWhatsAppHandler({ chat: async () => { throw new Error("api down"); }, send: async (...a) => sent.push(a), log: () => {} });
  await h2(payload([text("b", "1", "hi")])); assert.match(sent[0][1], /موظفينا/);
});
test("makeSender posts the Graph API request", async () => {
  let call; const send = makeSender({ token: "T", phoneId: "P", fetchImpl: async (u, i) => { call = [u, i]; return new Response("{}", { status: 200 }); } });
  await send("218", "hello");
  assert.match(call[0], /\/P\/messages$/); assert.equal(call[1].headers.authorization, "Bearer T");
  assert.equal(JSON.parse(call[1].body).to, "218");
});

test("staffAlerts: handoff includes callback phone; confirmed booking announced once; duplicates and failures are silent", async () => {
  const { staffAlerts } = await import("./whatsapp.mjs");
  const h = [{ tool: "handoff_to_human", input: { reason: "pain", customer_summary: "s", customer_phone: "0911" } }];
  assert.match(staffAlerts(h, "web")[0], /هاتف: 0911/);
  const bk = { customer_name: "Ali", service_id: "checkup", date: "2026-10-12", time: "10:00", customer_phone: "0911" };
  assert.equal(staffAlerts([{ tool: "book_appointment", result: { confirmed: true, booking: bk } }], "x").length, 1);
  assert.equal(staffAlerts([{ tool: "book_appointment", result: { confirmed: true, duplicate: true, booking: bk } }], "x").length, 0);
  assert.equal(staffAlerts([{ tool: "book_appointment", result: { error: "slot not available" } }], "x").length, 0);
});
