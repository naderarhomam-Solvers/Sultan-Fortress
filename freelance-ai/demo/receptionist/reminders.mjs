// Appointment reminders via WhatsApp *template* messages (reminders fall outside the 24h free-form window).
// Only customers who booked through WhatsApp themselves (wa_id set) are reminded: that is the opt-in.
import { zonedToUtc } from "./tools.mjs";

export function dueReminders(bookings, config, nowDate, { hoursBefore = 24, maxAttempts = 3, minAgeMs = 2 * 3600_000 } = {}) {
  return bookings.filter((b) => {
    if (!b.wa_id || b.reminded_at || (b.reminder_attempts ?? 0) >= maxAttempts) return false;
    if (nowDate - new Date(b.created_at) < minAgeMs) return false; // don't "remind" right after booking
    const untilStart = zonedToUtc(b.date, b.time, config.timezone || "UTC") - nowDate;
    return untilStart > 0 && untilStart <= hoursBefore * 3600_000;
  });
}

/** Template body params, in this order: {{1}} name, {{2}} service, {{3}} date, {{4}} time. */
export function reminderParams(b, config) {
  const svc = config.services.find((s) => s.id === b.service_id);
  return [b.customer_name, svc?.name ?? b.service_id, b.date, b.time];
}

export function startReminderLoop({ store, config, sendTemplate, template, language = "ar", intervalMs = 300_000, hoursBefore = 24, now = () => new Date(), log = console.error }) {
  let running = false;
  async function tick() {
    if (running) return; // never overlap ticks
    running = true;
    try {
      for (const b of dueReminders(store.bookings, config, now(), { hoursBefore })) {
        try {
          await sendTemplate(b.wa_id, template, language, reminderParams(b, config));
          store.update(b.id, { reminded_at: now().toISOString() });
        } catch (e) {
          log("reminder failed:", b.id, e.message);
          store.update(b.id, { reminder_attempts: (b.reminder_attempts ?? 0) + 1 });
        }
      }
    } finally { running = false; }
  }
  const timer = setInterval(tick, intervalMs);
  timer.unref?.();
  return { tick, stop: () => clearInterval(timer) };
}
