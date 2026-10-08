import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createStore, systemPrompt } from "./tools.mjs";

const config = JSON.parse(readFileSync(new URL("./clinic.example.json", import.meta.url), "utf8"));
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function openDay() { // next date that is not a closed weekday
  const d = new Date(); d.setDate(d.getDate() + 1);
  while (config.slots.closed_weekdays.includes(d.getDay())) d.setDate(d.getDate() + 1);
  return iso(d);
}

test("availability excludes booked slot and double-booking is rejected", () => {
  const s = createStore(config); const date = openDay();
  const a = s.run("check_availability", { date, service_id: "checkup" });
  assert.ok(a.available.includes("10:00"));
  const ok = s.run("book_appointment", { date, time: "10:00", service_id: "checkup", customer_name: "Ali", customer_phone: "0910000000" });
  assert.equal(ok.confirmed, true);
  assert.ok(!s.run("check_availability", { date, service_id: "checkup" }).available.includes("10:00"));
  assert.equal(s.run("book_appointment", { date, time: "10:00", service_id: "checkup", customer_name: "B", customer_phone: "1" }).error, "slot not available");
});
test("rejects unknown service, bad date, missing contact, past date", () => {
  const s = createStore(config);
  assert.ok(s.run("check_availability", { date: openDay(), service_id: "nope" }).error);
  assert.ok(s.run("check_availability", { date: "tomorrow", service_id: "checkup" }).error);
  assert.ok(s.run("book_appointment", { date: openDay(), time: "10:00", service_id: "checkup" }).error);
  assert.deepEqual(s.run("check_availability", { date: "2020-01-01", service_id: "checkup" }).available, []);
});
test("handoff is recorded; system prompt carries safety rules", () => {
  const s = createStore(config);
  assert.equal(s.run("handoff_to_human", { reason: "pain", customer_summary: "x" }).handed_off, true);
  assert.equal(s.handoffs.length, 1);
  assert.match(systemPrompt(config), /Never give medical advice/);
});
