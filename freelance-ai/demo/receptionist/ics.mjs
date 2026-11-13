// iCalendar (RFC 5545) feed of bookings: subscribe from Google/Apple/Outlook calendar, no OAuth needed.
// Calendar apps poll subscribed feeds every few hours - this is NOT real-time.
import { zonedToUtc } from "./tools.mjs";

const esc = (s) => String(s ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\;").replace(/,/g, "\\,").replace(/\r\n|\r|\n/g, "\\n");
const stamp = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

export function fold(line) { // 75 octets per line; continuation lines start with one space
  const out = []; let cur = ""; let bytes = 0;
  for (const ch of line) {
    const b = Buffer.byteLength(ch);
    if (bytes + b > (out.length ? 74 : 75)) { out.push(cur); cur = ""; bytes = 0; }
    cur += ch; bytes += b;
  }
  out.push(cur);
  return out.join("\r\n ");
}

export function buildIcs(bookings, config, now = new Date()) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mustaqbil//Receptionist//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", `X-WR-CALNAME:${esc(config.business_name)}`];
  for (const b of bookings) {
    const svc = config.services.find((s) => s.id === b.service_id);
    const start = zonedToUtc(b.date, b.time, config.timezone || "UTC");
    const end = new Date(start.getTime() + (svc?.duration_min ?? 30) * 60_000);
    lines.push("BEGIN:VEVENT", `UID:${b.id}@mustaqbil`, `DTSTAMP:${stamp(now)}`, `DTSTART:${stamp(start)}`, `DTEND:${stamp(end)}`,
      `SUMMARY:${esc(`${svc?.name ?? b.service_id} — ${b.customer_name}`)}`,
      `DESCRIPTION:${esc(`Phone: ${b.customer_phone}\nSource: ${b.source ?? "web"}`)}`, "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}
