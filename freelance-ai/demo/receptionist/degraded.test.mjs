process.env.ANTHROPIC_API_KEY = "test-key";
const fetch_ = globalThis.fetch;
import test from "node:test";
import assert from "node:assert/strict";
const { server } = await import("./server.mjs");
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;
test.after(() => server.close());

test("web chat degrades to a handoff message (HTTP 200) when the API is down; bad input is still 400", async () => {
  globalThis.fetch = (url, init) => url.startsWith("https://api.anthropic.com") ? Promise.reject(new Error("network down")) : fetch_(url, init);
  const ok = await fetch_(base + "/api/chat", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: "hi" }] }) });
  const body = await ok.json();
  assert.equal(ok.status, 200); assert.equal(body.degraded, true); assert.match(body.reply, /موظفينا/);
  const bad = await fetch_(base + "/api/chat", { method: "POST", body: JSON.stringify({ messages: [{ role: "tool", content: "x" }] }) });
  assert.equal(bad.status, 400);
});
