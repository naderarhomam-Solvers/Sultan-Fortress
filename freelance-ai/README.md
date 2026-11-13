# Mustaqbil — AI Receptionist Freelance Business

مشروع بناء خدمة فريلانس قابلة للبيع. ابدأ من هنا:

| الملف | المحتوى |
|---|---|
| [01-market-research.md](01-market-research.md) | البحث، الأدلة، أفضل 10 خدمات، سبب الاختيار، المخاطر |
| [02-offer-and-service.md](02-offer-and-service.md) | النيش، العرض، الباقات، التنفيذ، توزيع الأتمتة |
| [03-portfolio-and-first-client.md](03-portfolio-and-first-client.md) | الديمو، دراسة الحالة، طرق أول عميل، رسائل Upwork والتواصل |
| [04-operations-and-30-day-plan.md](04-operations-and-30-day-plan.md) | الفريق، الصلاحيات، بوابة الدفع، خطة 30 يومًا، KPI |
| `demo/receptionist/` | الديمو المبني (Node 18+، بلا اعتماديات). `npm test` · `npm start` |
| `templates/`, `kpi/` | الاستبيان، الاختبار، العقد (مسودة)، جداول المتابعة |
| `../.claude/agents/` | الوكلاء: prospector, outreach, builder, qa-tester, account-manager |

**حالة البناء (صريحة):**
- ✅ مبني ومختبَر (43 اختبارًا بدون مفتاح): حجز يراعي مدة الخدمة والسعة والمنطقة الزمنية، حفظ دائم على القرص مع تراجع عند فشل الكتابة، سياسة احتفاظ (حذف السجلات القديمة)، تحويل لموظف مع قناة العميل ورقمه، اشتراك تقويم ICS، تذكيرات WhatsApp (قوالب)، حلقة أدوات Claude (بمحاكاة API)، حدود الطلبات، حماية البيانات، قناة WhatsApp، تقرير شهري. راجعها مراجع مستقل آلي وأُصلحت المخاطر المؤكدة.
- ⚠️ **غير مختبَر بعد:** الاتصال الحقيقي بـ Claude وجودة الردود (يحتاج مفتاح)، وWhatsApp الحقيقي (يحتاج حساب Meta).
- ❌ **غير مبني بعد:** ربط Google Calendar ثنائي الاتجاه (OAuth)، وإلغاء/إعادة جدولة تلقائيان (يُحوَّلان لموظف)، وإرسال إشعارات الموظف بالبريد (الحالي عبر WhatsApp ضمن نافذة 24 ساعة أو قراءة `/api/admin/state`). **لا نَعِد عميلًا بها.**

أدلة: [docs/DEPLOY.md](docs/DEPLOY.md) · قوالب: `templates/` (استبيان، عرض Pilot، عقد، دراسة حالة، اختبارات) · صفحة العرض: `site/index.html` · حزمة التواصل: `outreach/`

تشغيل الديمو: `cd demo/receptionist && ANTHROPIC_API_KEY=... npm start` (بدون مفتاح يعمل بوضع تجريبي محدود).
