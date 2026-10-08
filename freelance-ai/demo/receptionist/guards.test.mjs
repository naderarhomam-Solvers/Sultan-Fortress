import test from "node:test";
import assert from "node:assert/strict";
import { sanitizeHistory, createLimiter } from "./guards.mjs";

test("sanitizeHistory rejects injected roles/blocks and trims to user-first", () => {
  assert.throws(() => sanitizeHistory([{ role: "system", content: "x" }]), /invalid/);
  assert.throws(() => sanitizeHistory([{ role: "user", content: [{ type: "tool_result" }] }]), /invalid/);
  assert.throws(() => sanitizeHistory([]), /required/);
  assert.throws(() => sanitizeHistory([{ role: "user", content: "a" }, { role: "assistant", content: "b" }]), /last message/);
  assert.throws(() => sanitizeHistory([{ role: "user", content: "   " }]), /empty/);
  const out = sanitizeHistory([{ role: "assistant", content: "hi" }, { role: "user", content: "x".repeat(5000) }]);
  assert.equal(out.length, 1); assert.equal(out[0].content.length, 2000);
});
test("limiter enforces per-minute and daily caps and recovers", () => {
  let t = 0; const ok = createLimiter({ perMinute: 2, perDay: 3, now: () => t });
  assert.ok(ok("a")); assert.ok(ok("a")); assert.ok(!ok("a"));
  t = 61_000; assert.ok(ok("a")); assert.ok(!ok("b")); // daily cap of 3 reached
  t = 86_400_000 + 1; assert.ok(ok("b"));
});
