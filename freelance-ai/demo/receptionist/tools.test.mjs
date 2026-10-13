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
