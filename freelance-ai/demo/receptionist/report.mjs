// Monthly client report from the JSONL conversation log. Usage: node report.mjs conversations.jsonl [out.md]
import { readFile, writeFile } from "node:fs/promises";
const [file, out] = process.argv.slice(2);
if (!file) { console.error("usage: node report.mjs <log.jsonl> [out.md]"); process.exit(2); }
const rows = (await readFile(file, "utf8")).split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
const count = (arr) => arr.reduce((m, k) => ((m[k] = (m[k] || 0) + 1), m), {});
const tools = rows.flatMap((r) => r.tools || []);
const bookings = tools.filter((t) => t.tool === "book_appointment" && t.ok);
const handoffs = tools.filter((t) => t.tool === "handoff_to_human");
const senders = new Set(rows.map((r) => r.sender).filter(Boolean));
const hours = rows.map((r) => new Date(r.ts).getHours());
const after = hours.filter((h) => h < 9 || h >= 21).length; // rough "outside working hours" (edit to client hours)
const md = [
  `# تقرير الأداء`,
  `الفترة: ${rows[0]?.ts?.slice(0, 10) ?? "-"} → ${rows.at(-1)?.ts?.slice(0, 10) ?? "-"}`,
  "",
  `| المؤشر | القيمة |`, `|---|---|`,
  `| رسائل العملاء المُجابة | ${rows.length} |`,
  `| عملاء مختلفون (تقريبًا) | ${senders.size} |`,
  `| رسائل خارج 9ص–9م | ${after} |`,
  `| مواعيد حُجزت | ${bookings.length} |`,
  `| حالات حُوّلت لموظف | ${handoffs.length} |`,
  "",
  `## خدمات الحجوزات`,
  ...Object.entries(count(bookings.map((b) => b.input?.service_id))).map(([k, v]) => `- ${k}: ${v}`),
  "",
  `## أسباب التحويل (للمراجعة وتحسين المعلومات المعتمدة)`,
  ...handoffs.slice(0, 30).map((h) => `- ${h.input?.reason ?? "?"}`),
  "",
  `## أسئلة تحتاج مراجعة (ردود بعد تحويل أو بدون أدوات)`,
  ...rows.filter((r) => (r.tools || []).some((t) => t.tool === "handoff_to_human")).slice(0, 15).map((r) => `- "${String(r.user).slice(0, 120)}"`),
  "",
  `> الأرقام مأخوذة من سجل المحادثات الفعلي. لا تُنسب نتائج مالية (إيراد/توفير) إلا بعد تأكيدها مع العميل.`,
].join("\n");
if (out) await writeFile(out, md); else console.log(md);
