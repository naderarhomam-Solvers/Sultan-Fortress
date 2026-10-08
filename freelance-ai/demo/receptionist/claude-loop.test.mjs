// Verifies the tool-use loop against a stubbed Anthropic API (no key or network needed).
process.env.ANTHROPIC_API_KEY = "test-key";
import test from "node:test";
import assert from "node:assert/strict";
const { chat, MODE, config } = await import("./server.mjs");

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function openDay() { const d = new Date(); d.setDate(d.getDate() + 1); while (config.slots.closed_weekdays.includes(d.getDay())) d.setDate(d.getDate() + 1); return iso(d); }

test("runs tools, returns tool_result with matching id, then final text", async () => {
  const date = openDay(), requests = [];
  const script = [
    { stop_reason: "tool_use", content: [{ type: "tool_use", id: "tu_1", name: "check_availability", input: { date, service_id: "checkup" } }] },
    { stop_reason: "tool_use", content: [{ type: "tool_use", id: "tu_2", name: "book_appointment", input: { date, time: "10:00", service_id: "checkup", customer_name: "Ali", customer_phone: "0911111111" } }] },
    { stop_reason: "end_turn", content: [{ type: "text", text: "تم الحجز" }] },
  ];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, headers: init.headers, body: JSON.parse(init.body) });
    return new Response(JSON.stringify(script[requests.length - 1]), { status: 200 });
  };
  const out = await chat([{ role: "user", content: "احجز" }]);
  assert.equal(MODE, "claude");
  assert.equal(out.reply, "تم الحجز");
  assert.deepEqual(out.trace.map((t) => t.tool), ["check_availability", "book_appointment"]);
  assert.equal(out.trace[1].result.confirmed, true);
  assert.equal(requests.length, 3);
  assert.equal(requests[0].headers["x-api-key"], "test-key");
  const lastMsgs = requests[1].body.messages;
  assert.equal(lastMsgs.at(-1).content[0].tool_use_id, "tu_1");
  assert.equal(lastMsgs.at(-2).role, "assistant");
  assert.ok(requests[0].body.system.includes("Never give medical advice"));
});

test("API error surfaces; runaway tool loop ends with handoff message", async () => {
  globalThis.fetch = async () => new Response("boom", { status: 500 });
  await assert.rejects(chat([{ role: "user", content: "x" }]), /Anthropic API 500/);
  globalThis.fetch = async () => new Response(JSON.stringify({ stop_reason: "tool_use", content: [{ type: "tool_use", id: "t", name: "check_availability", input: { date: "bad", service_id: "x" } }] }), { status: 200 });
  const out = await chat([{ role: "user", content: "x" }]);
  assert.match(out.reply, /موظف/);
});

test("upstream calls carry a timeout signal", async () => {
  let init;
  globalThis.fetch = async (_u, i) => { init = i; return new Response(JSON.stringify({ stop_reason: "end_turn", content: [{ type: "text", text: "ok" }] }), { status: 200 }); };
  await chat([{ role: "user", content: "x" }]);
  assert.ok(init.signal instanceof AbortSignal);
});
