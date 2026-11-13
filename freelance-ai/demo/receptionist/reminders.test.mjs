import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createStore } from "./tools.mjs";
import { dueReminders, reminderParams, startReminderLoop } from "./reminders.mjs";

const config = JSON.parse(readFileSync(new URL("./clinic.example.json", import.meta.url), "utf8"));
// the booking starts 2026-10-12 10:00 Tripoli == 08:00Z
const mkB = (o = {}) => ({ id: "b1", date: "2026-10-12", time: "10:00", service_id: "checkup", customer_name: "Ali", wa_id: "218910000000", created_at: "2026-10-10T08:00:00Z", ...o });
const at = (iso) => new Date(iso);

test("due only inside the 24h window", () => {
  assert.equal(dueReminders([mkB()], config, at("2026-10-11T07:00:00Z")).length, 0); // 25h before
  assert.equal(dueReminders([mkB()], config, at("2026-10-11T09:00:00Z")).length, 1); // 23h before
  assert.equal(dueReminders([mkB()], config, at("2026-10-12T08:00:00Z")).length, 0); // already started
});
test("skips web bookings, already reminded, exhausted attempts, and just-created bookings", () => {
  const now = at("2026-10-11T09:00:00Z");
  assert.equal(dueReminders([mkB({ wa_id: undefined })], config, now).length, 0);
  assert.equal(dueReminders([mkB({ reminded_at: "x" })], config, now).length, 0);
  assert.equal(dueReminders([mkB({ reminder_attempts: 3 })], config, now).length, 0);
  assert.equal(dueReminders([mkB({ created_at: "2026-10-11T08:30:00Z" })], config, now).length, 0); // booked 30 min ago
});
test("template params order: name, service, date, time", () => {
  assert.deepEqual(reminderParams(mkB(), config), ["Ali", "كشف وفحص", "2026-10-12", "10:00"]);
});
test("loop sends once, marks reminded, counts failures, never overlaps", async () => {
  const now = at("2026-10-11T09:00:00Z");
  const s = createStore(config, { now: () => now });
  s.bookings.push(mkB(), mkB({ id: "b2", wa_id: "218920000000" }));
  const sent = [];
  let fail = true;
  const sendTemplate = async (to, name, lang, params) => { if (to.endsWith("20000000") && fail) throw new Error("meta 131047"); sent.push([to, name, lang, params[0]]); };
  const loop = startReminderLoop({ store: s, config, sendTemplate, template: "appt_reminder", now: () => now, intervalMs: 3_600_000, log: () => {} });
  await loop.tick();
  assert.deepEqual(sent, [["218910000000", "appt_reminder", "ar", "Ali"]]);
  assert.ok(s.bookings[0].reminded_at); assert.equal(s.bookings[1].reminder_attempts, 1);
  await loop.tick(); assert.equal(sent.length, 1); // b1 not re-sent
  fail = false; await loop.tick(); assert.equal(sent.length, 2); // b2 retried and delivered
  await Promise.all([loop.tick(), loop.tick()]); assert.equal(sent.length, 2);
  loop.stop();
});

test("a failing state write inside the failure path does not crash the loop", async () => {
  const now = at("2026-10-11T09:00:00Z");
  const store = { bookings: [mkB()], update() { throw new Error("disk full"); } };
  const logs = [];
  const loop = startReminderLoop({ store, config, sendTemplate: async () => { throw new Error("meta down"); }, template: "t", now: () => now, intervalMs: 3_600_000, log: (...a) => logs.push(a.join(" ")) });
  await assert.doesNotReject(loop.tick());
  assert.ok(logs.some((l) => l.includes("reminder state not saved")));
  loop.stop();
});
