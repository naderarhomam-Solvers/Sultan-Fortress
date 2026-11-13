import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createStore, systemPrompt, nowInTz, zonedToUtc, normalizePhone } from "./tools.mjs";

const base = JSON.parse(readFileSync(new URL("./clinic.example.json", import.meta.url), "utf8"));
const mk = (over = {}) => structuredClone({ ...base, ...over });
// Fixed clock: Sunday 2026-10-11 10:00 in Tripoli (UTC+2) == 08:00Z. Closed weekday in config is 5 (Friday).
const NOW = new Date("2026-10-11T08:00:00Z");
const store = (cfg = base, opts = {}) => createStore(cfg, { now: () => NOW, ...opts });
const DAY = "2026-10-12"; // Monday
const book = (s, o = {}) => s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Ali", customer_phone: "0910000000", ...o });

test("timezone helpers: Tripoli is UTC+2, conversions round-trip", () => {
  assert.deepEqual(nowInTz("Africa/Tripoli", NOW), { date: "2026-10-11", minutes: 600 });
  assert.equal(zonedToUtc("2026-10-12", "10:00", "Africa/Tripoli").toISOString(), "2026-10-12T08:00:00.000Z");
  assert.equal(zonedToUtc("2026-10-12", "10:00", "UTC").toISOString(), "2026-10-12T10:00:00.000Z");
  // server running in UTC just before Tripoli midnight: it is already the next day in Tripoli
  assert.equal(nowInTz("Africa/Tripoli", new Date("2026-10-11T22:30:00Z")).date, "2026-10-12");
});

test("availability excludes booked slot; double booking and duplicate retries behave", () => {
  const s = store();
  assert.ok(s.run("check_availability", { date: DAY, service_id: "checkup" }).available.includes("10:00"));
  const ok = book(s); assert.equal(ok.confirmed, true);
  assert.ok(!s.run("check_availability", { date: DAY, service_id: "checkup" }).available.includes("10:00"));
  assert.equal(book(s, { customer_name: "B", customer_phone: "0921111111" }).error, "slot not available");
  const retry = book(s); assert.equal(retry.duplicate, true); assert.equal(s.bookings.length, 1);
});

test("a long service blocks every overlapping start time and respects closing time", () => {
  const s = store();
  assert.equal(book(s, { service_id: "whitening", time: "10:00" }).confirmed, true); // 60 min: 10:00-11:00
  const a = s.run("check_availability", { date: DAY, service_id: "checkup" }).available;
  assert.ok(!a.includes("10:00") && !a.includes("10:30") && a.includes("11:00") && a.includes("09:30"));
  // a 60-min service starting 09:30 would overlap 10:00 -> not offered
  assert.ok(!s.run("check_availability", { date: DAY, service_id: "whitening" }).available.includes("09:30"));
  // closing at 17:00: whitening (60) cannot start 16:30
  const late = s.run("check_availability", { date: "2026-10-14", service_id: "whitening" }).available;
  assert.ok(late.includes("16:00") && !late.includes("16:30"));
});

test("capacity > 1 allows parallel bookings up to capacity", () => {
  const cfg = mk(); cfg.slots.capacity = 2; const s = store(cfg);
  assert.equal(book(s, { customer_phone: "0911111111" }).confirmed, true);
  assert.equal(book(s, { customer_phone: "0922222222" }).confirmed, true);
  assert.equal(book(s, { customer_phone: "0933333333" }).error, "slot not available");
});

test("past times today, closed days, bad/impossible dates, out-of-range", () => {
  const s = store();
  const today = s.run("check_availability", { date: "2026-10-11", service_id: "checkup" }).available;
  assert.ok(!today.includes("09:00") && !today.includes("10:00") && today.includes("10:30")); // now is 10:00 local
  assert.deepEqual(s.run("check_availability", { date: "2026-10-16", service_id: "checkup" }).available, []); // Friday closed
  assert.ok(s.run("check_availability", { date: "2026-02-31", service_id: "checkup" }).error);
  assert.ok(s.run("check_availability", { date: "tomorrow", service_id: "checkup" }).error);
  assert.deepEqual(s.run("check_availability", { date: "2026-10-10", service_id: "checkup" }).available, []);
  assert.deepEqual(s.run("check_availability", { date: "2027-01-01", service_id: "checkup" }).available, []);
  assert.ok(s.run("check_availability", { date: DAY, service_id: "nope" }).error);
});

test("input validation: phone, name, time; per-phone cap", () => {
  const s = store();
  assert.ok(book(s, { customer_phone: "abc" }).error);
  assert.ok(book(s, { customer_phone: "1" }).error);
  assert.ok(book(s, { customer_name: "  " }).error);
  assert.ok(book(s, { time: "25:00" }).error);
  assert.ok(s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup" }).error);
  assert.equal(normalizePhone("+218 91-234 5678"), "218912345678");
  assert.equal(book(s, { time: "09:00" }).confirmed, true);
  assert.equal(book(s, { time: "09:30" }).confirmed, true);
  assert.equal(book(s, { time: "10:00" }).confirmed, true);
  assert.match(book(s, { time: "10:30" }).error, /too many upcoming/);
});

test("bookings persist atomically to disk, survive restart, cancel is persisted, corrupt file fails loudly", () => {
  const file = join(mkdtempSync(join(tmpdir(), "bk-")), "b.json");
  const s1 = store(base, { file }); book(s1, { time: "11:00" });
  s1.run("handoff_to_human", { reason: "x", customer_summary: "y" });
  assert.ok(!existsSync(file + ".tmp"));
  const s2 = store(base, { file });
  assert.equal(s2.bookings.length, 1); assert.equal(s2.handoffs.length, 1);
  assert.ok(!s2.run("check_availability", { date: DAY, service_id: "checkup" }).available.includes("11:00"));
  const id = s2.bookings[0].id;
  assert.equal(s2.cancel(id), true); assert.equal(s2.cancel(id), false);
  assert.equal(store(base, { file }).bookings.length, 0);
  writeFileSync(file, "{not json");
  assert.throws(() => store(base, { file }));
});

test("whatsapp bookings record the wa_id (reminder opt-in); web bookings do not", () => {
  const s = store();
  const w = s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "A", customer_phone: "0910000001" }, { channel: "whatsapp", sender: "218910000001" });
  const web = s.run("book_appointment", { date: DAY, time: "11:00", service_id: "checkup", customer_name: "B", customer_phone: "0910000002" }, { channel: "web", sender: "1.2.3.4" });
  assert.equal(w.booking.wa_id, "218910000001"); assert.equal(web.booking.wa_id, undefined);
});

test("handoff is recorded; system prompt uses the business timezone date and carries safety rules", () => {
  const s = store();
  assert.equal(s.run("handoff_to_human", { reason: "pain", customer_summary: "x" }).handed_off, true);
  assert.equal(s.handoffs.length, 1);
  const p = systemPrompt(base, new Date("2026-10-11T22:30:00Z"));
  assert.match(p, /Today is 2026-10-12/); assert.match(p, /Never give medical advice/); assert.match(p, /cannot cancel or reschedule/);
});

// ---- regressions for the independent review ----
const cfgWith = (slots = {}, extra = {}) => { const c = mk(extra); Object.assign(c.slots, slots); c.default_country_code = "218"; return c; };

test("retry guard: same person only; no PII echoed; different name needs capacity; other WhatsApp sender is not a duplicate", () => {
  const s = store(cfgWith({ capacity: 2 }));
  const ctxA = { channel: "whatsapp", sender: "218911112222" };
  const first = s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Mona", customer_phone: "0911112222" }, ctxA);
  assert.equal(first.confirmed, true);
  const retry = s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: " mona ", customer_phone: "+218 91 111 2222" }, ctxA);
  assert.equal(retry.duplicate, true);
  assert.deepEqual(Object.keys(retry.booking).sort(), ["date", "id", "service_id", "time"]);
  // someone else who only knows the phone number must not get the stored booking back
  const attacker = s.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Mona", customer_phone: "0911112222" }, { channel: "whatsapp", sender: "218900000000" });
  assert.ok(!attacker.duplicate);
  // mother books her daughter in the same slot with the same phone: a real second booking (fresh store, so the seat above is free)
  const fam = store(cfgWith({ capacity: 2 }));
  fam.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Mona", customer_phone: "0911112222" }, ctxA);
  const daughter = fam.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Sara", customer_phone: "0911112222" }, ctxA);
  assert.equal(daughter.confirmed, true); assert.ok(!daughter.duplicate); assert.equal(fam.bookings.length, 2);
  const strict = store(cfgWith({ capacity: 1 }));
  strict.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Mona", customer_phone: "0911112222" });
  assert.equal(strict.run("book_appointment", { date: DAY, time: "10:00", service_id: "checkup", customer_name: "Sara", customer_phone: "0911112222" }).error, "slot not available");
});

test("phone spellings collapse to one canonical key (cap cannot be bypassed)", () => {
  for (const v of ["0910000000", "+218910000000", "00218910000000", "+218 91 0000000", "910000000"]) assert.equal(normalizePhone(v, "218"), "218910000000", v);
  assert.equal(normalizePhone("0000", "218"), null);
  const s = store(cfgWith());
  const spell = ["0910000000", "+218910000000", "00218910000000", "+218 91-0000000"];
  const times = ["09:00", "09:30", "10:00", "10:30"];
  const res = spell.map((p, i) => s.run("book_appointment", { date: DAY, time: times[i], service_id: "checkup", customer_name: "Ali", customer_phone: p }));
  assert.equal(res.filter((r) => r.confirmed).length, 3);
  assert.match(res[3].error, /too many upcoming/);
});

test("per-sender cap stops one visitor hoarding slots with invented numbers", () => {
  const c = cfgWith({ max_per_sender: 2, max_per_phone: 99 }); const s = store(c);
  const ctx = { channel: "web", sender: "9.9.9.9" };
  const b = (i) => s.run("book_appointment", { date: DAY, time: ["09:00", "09:30", "10:00"][i], service_id: "checkup", customer_name: "X", customer_phone: `09100000${10 + i}` }, ctx);
  assert.equal(b(0).confirmed, true); assert.equal(b(1).confirmed, true); assert.match(b(2).error, /too many upcoming bookings from this sender/);
  assert.ok(!JSON.stringify(s.bookings).includes("9.9.9.9")); // only a hash is stored
});

test("a failed disk write rolls memory back: no phantom booking, retry is not a fake duplicate", () => {
  const dir = mkdtempSync(join(tmpdir(), "rb-")); const file = join(dir, "sub", "b.json"); // directory does not exist -> write fails
  const s = store(base, { file });
  const r = book(s);
  assert.match(r.error, /storage_unavailable/);
  assert.equal(s.bookings.length, 0);
  assert.ok(s.run("check_availability", { date: DAY, service_id: "checkup" }).available.includes("10:00"));
  assert.match(book(s).error, /storage_unavailable/); // still an honest failure, never {duplicate:true}
  assert.match(s.run("handoff_to_human", { reason: "x", customer_summary: "y" }).error, /storage_unavailable/);
  assert.equal(s.handoffs.length, 0);
});

test("retention purge removes old bookings/handoffs on load and on demand, keeps recent ones", () => {
  const file = join(mkdtempSync(join(tmpdir(), "pg-")), "b.json");
  writeFileSync(file, JSON.stringify({
    bookings: [{ id: "old1", date: "2026-05-01", time: "10:00", service_id: "checkup", customer_name: "Old", phone: "1" }, { id: "new1", date: "2026-10-12", time: "10:00", service_id: "checkup", customer_name: "New", phone: "2" }],
    handoffs: [{ id: "h-old", at: "2026-05-01T00:00:00Z" }, { id: "h-new", at: "2026-10-10T00:00:00Z" }],
  }));
  const s = store(base, { file });
  assert.deepEqual(s.bookings.map((b) => b.id), ["new1"]); assert.deepEqual(s.handoffs.map((h) => h.id), ["h-new"]);
  assert.deepEqual(JSON.parse(readFileSync(file, "utf8")).bookings.map((b) => b.id), ["new1"]);
  assert.equal(s.purge(1), 0); // cutoff 2026-10-10: both remaining records are newer
  const later = createStore(base, { file, now: () => new Date("2026-12-01T00:00:00Z") }); // default retention 90 days keeps them
  assert.equal(later.bookings.length, 1);
  assert.equal(later.purge(30), 2); assert.equal(later.bookings.length, 0); assert.equal(later.handoffs.length, 0);
});

test("handoff keeps channel, wa_id and callback phone so staff can actually follow up", () => {
  const s = store(cfgWith());
  s.run("handoff_to_human", { reason: "pain", customer_summary: "x", customer_phone: "0911112222" }, { channel: "whatsapp", sender: "218911112222" });
  s.run("handoff_to_human", { reason: "refund", customer_summary: "y" }, { channel: "web", sender: "1.2.3.4" });
  assert.deepEqual([s.handoffs[0].channel, s.handoffs[0].wa_id, s.handoffs[0].customer_phone], ["whatsapp", "218911112222", "218911112222"]);
  assert.deepEqual([s.handoffs[1].channel, s.handoffs[1].wa_id, s.handoffs[1].customer_phone], ["web", undefined, undefined]);
});

test("malformed tool input never throws out of run()", () => {
  const s = store();
  for (const input of [null, undefined, 5, "x", [], { date: ["2026-10-12"], service_id: {} }, { date: DAY, service_id: "checkup", customer_name: {}, customer_phone: [] }]) {
    for (const name of ["check_availability", "book_appointment", "handoff_to_human"]) assert.doesNotThrow(() => s.run(name, input), `${name} ${JSON.stringify(input)}`);
  }
  assert.ok(s.run("book_appointment", { date: DAY, time: 1000, service_id: "checkup", customer_name: "A", customer_phone: "0910000000" }).error);
});

test("invalid client config fails at startup with a clear message", () => {
  assert.throws(() => store(mk({ timezone: "Mars/Base" })), /timezone/);
  const c = mk(); c.slots.step_min = 0; assert.throws(() => store(c), /step_min/);
  const d = mk(); d.slots.days_ahead = undefined; assert.throws(() => store(d), /days_ahead/);
  const e = mk(); e.services = []; assert.throws(() => store(e), /services/);
});
