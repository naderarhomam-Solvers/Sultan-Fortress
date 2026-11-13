# Weighted scoring for the 10 candidate services. Scores 0-10 are analyst judgments
# informed by research (see 01-market-research.md); weights are the user's.
W = dict(demand=20, ease=15, ai=20, first=15, profit=10, comp=10, scale=5, libya=5)
S = {
 "1 AI Receptionist/WhatsApp booking for appointment businesses": (8,7,8,7,8,6,9,6),
 "2 Generic AI workflow automation (n8n/Make) for SMBs":          (9,7,8,6,7,3,7,6),
 "3 AI support chatbot for e-commerce stores":                    (7,7,8,6,6,4,7,6),
 "4 Outbound lead-gen automation (enrichment + personalised email)":(7,6,7,6,7,4,7,5),
 "5 Claude Code custom small apps / internal tools":              (8,5,9,6,7,4,5,6),
 "6 AI-assisted websites / landing pages":                        (6,8,8,7,5,2,4,7),
 "7 Reporting & data-analysis automation (Sheets/dashboards)":    (6,6,7,5,7,6,6,6),
 "8 AI content / SEO articles":                                   (5,9,9,5,3,1,4,7),
 "9 AI video repurposing / short-form editing":                   (7,7,6,6,6,4,6,6),
 "10 Arabic AI data annotation / LLM evaluation":                 (6,6,5,6,5,6,3,6),
}
keys = list(W)
rows = sorted(((sum(W[k]*v for k,v in zip(keys,s))/10, n) for n,s in S.items()), reverse=True)
for sc,n in rows: print(f"{sc:5.1f}  {n}")
