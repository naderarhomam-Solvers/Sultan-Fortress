import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const file = join(mkdtempSync(join(tmpdir(), "cal-")), "b.json");
writeFileSync(file, JSON.stringify({ bookings: [{ id: "bk000001", date: "2030-01-07", time: "10:00", service_id: "checkup", customer_name: "Ali", customer_phone: "0910000000", phone: "910000000", source: "whatsapp", created_at: "2029-12-01T00:00:00Z" }], handoffs: [] }));
process.env.BOOKINGS_FILE = file; process.env.ADMIN_TOKEN = "adm"; process.env.CALENDAR_TOKEN = "cal-secret";
import test from "node:test";
import assert from "node:assert/strict";
const { server } = await import("./server.mjs");
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;
test.after(() => server.close());

test("calendar feed requires the secret token and lists persisted bookings", async () => {
  assert.equal((await fetch(base + "/calendar.ics")).status, 404);
  assert.equal((await fetch(base + "/calendar.ics?token=wrong")).status, 404);
  const ok = await fetch(base + "/calendar.ics?token=cal-secret");
  assert.equal(ok.status, 200); assert.match(ok.headers.get("content-type"), /text\/calendar/); assert.equal(ok.headers.get("cache-control"), "no-store");
  const body = await ok.text();
  assert.match(body, /DTSTART:20300107T080000Z/); assert.match(body, /Ali/);
});
test("admin cancel needs token, removes booking from feed and from disk", async () => {
  const post = (h, b) => fetch(base + "/api/admin/cancel", { method: "POST", headers: h, body: JSON.stringify(b) });
  assert.equal((await post({}, { id: "bk000001" })).status, 401);
  assert.equal((await post({ "x-admin-token": "adm" }, { id: "nope" })).status, 404);
  assert.equal((await post({ "x-admin-token": "adm" }, { id: "bk000001" })).status, 200);
  assert.doesNotMatch(await (await fetch(base + "/calendar.ics?token=cal-secret")).text(), /bk000001/);
  assert.deepEqual(JSON.parse(readFileSync(file, "utf8")).bookings, []);
});
