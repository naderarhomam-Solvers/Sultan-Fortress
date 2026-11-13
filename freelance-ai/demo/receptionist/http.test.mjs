process.env.ADMIN_TOKEN = "adm"; process.env.RATE_PER_MIN = "3";
import test from "node:test";
import assert from "node:assert/strict";
const { server } = await import("./server.mjs");
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;
test.after(() => server.close());

test("public state exposes no customer data; admin needs token", async () => {
  const pub = await (await fetch(base + "/api/state")).json();
  assert.deepEqual(Object.keys(pub), ["mode"]);
  assert.equal((await fetch(base + "/api/admin/state")).status, 401);
  assert.equal((await fetch(base + "/api/admin/state", { headers: { "x-admin-token": "nope" } })).status, 401);
  assert.equal((await fetch(base + "/api/admin/state", { headers: { "x-admin-token": "adm" } })).status, 200);
});
test("chat validates input, rate-limits, webhook rejects unsigned", async () => {
  const post = (b) => fetch(base + "/api/chat", { method: "POST", body: JSON.stringify(b) });
  assert.equal((await post({ messages: [{ role: "system", content: "x" }] })).status, 400);
  assert.equal((await post({ messages: [{ role: "user", content: "hi" }] })).status, 200);
  assert.equal((await post({ messages: [{ role: "user", content: "hi" }] })).status, 200);
  assert.equal((await post({ messages: [{ role: "user", content: "hi" }] })).status, 429);
  assert.equal((await fetch(base + "/webhook", { method: "POST", body: "{}" })).status, 503); // WhatsApp not configured
  assert.equal((await fetch(base + "/webhook?hub.mode=subscribe&hub.verify_token=x&hub.challenge=1")).status, 403);
  assert.equal((await fetch(base + "/..%2fserver.mjs")).status, 403);
  assert.equal((await fetch(base + "/")).status, 200);
});
