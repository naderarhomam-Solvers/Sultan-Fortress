import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildIcs, fold } from "./ics.mjs";

const config = JSON.parse(readFileSync(new URL("./clinic.example.json", import.meta.url), "utf8"));
const b = { id: "abc12345", date: "2026-10-12", time: "10:00", service_id: "cleaning", customer_name: "Ali; Hassan, Jr.", customer_phone: "0910000000", source: "whatsapp" };

test("ICS has correct UTC times, duration, escaping and CRLF", () => {
  const ics = buildIcs([b], config, new Date("2026-10-11T06:00:00Z"));
  assert.ok(ics.startsWith("BEGIN:VCALENDAR\r\n") && ics.endsWith("END:VCALENDAR\r\n"));
  assert.match(ics, /DTSTART:20261012T080000Z/);   // 10:00 Tripoli = 08:00Z
  assert.match(ics, /DTEND:20261012T084500Z/);     // cleaning = 45 min
  assert.match(ics, /UID:abc12345@mustaqbil/);
  const unfolded = ics.replace(/\r\n /g, "");
  assert.ok(unfolded.includes("Ali\; Hassan\\, Jr."));
  assert.ok(!/[^\r]\n/.test(ics));
});
test("fold keeps every physical line <= 75 octets, multibyte-safe, and unfolds losslessly", () => {
  const line = "SUMMARY:" + "عيادة الأمل ".repeat(20);
  const folded = fold(line);
  for (const l of folded.split("\r\n")) assert.ok(Buffer.byteLength(l) <= 75, l);
  assert.equal(folded.replace(/\r\n /g, ""), line);
});
test("empty calendar is valid", () => {
  assert.match(buildIcs([], config), /BEGIN:VCALENDAR[\s\S]*END:VCALENDAR/);
});
