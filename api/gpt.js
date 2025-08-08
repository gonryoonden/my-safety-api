// api/gpt.js
const OC = process.env.LAW_OC; // 예: shg30335
const BASE = process.env.LAW_BASE || "https://www.law.go.kr/DRF";

// 간단 후보 선택: 완전일치 > 부분일치 > 첫번째
function pickCandidate(items, q) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const exact = items.find(x => (x.LAW_NM || "").trim() === q.trim());
  if (exact) return exact;
  const includes = items.find(x => (x.LAW_NM || "").includes(q.trim()));
  return includes || items[0];
}

export default async function handler(req, res) {
  // CORS & 헬스
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS, GET");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
    res.status(204).end(); return;
  }
  if (req.method === "GET") {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.status(200).json({ ok: true, message: "Use POST /api/gpt" }); return;
  }
  if (req.method !== "POST") {
    res.status(405).json({ status: "ERROR", message: "Method Not Allowed" }); return;
  }
  res.setHeader("Access-Control-Allow-Origin", "*");

  try {
    const { function_name, arguments: args = {} } = req.body || {};
    if (function_name !== "search_safety_law") {
      return res.status(400).json({ status: "ERROR", message: "Unknown function_name" });
    }
    const lawText = String(args.law_text || "").trim();
    if (!lawText) return res.status(400).json({ status: "ERROR", message: "law_text is required" });
    if (!OC) return res.status(500).json({ status: "ERROR", message: "LAW_OC is not set" });

    // 1) 검색
    const searchUrl = `${BASE}/lawSearch.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&query=${encodeURIComponent(lawText)}&display=5&page=1`;
    const sRes = await fetch(searchUrl, { headers: { "Accept": "application/json" } });
    if (!sRes.ok) throw new Error(`lawSearch ${sRes.status}`);
    const sJson = await sRes.json();
    const items = sJson?.Laws?.law ?? sJson?.law ?? [];
    const cand = pickCandidate(items, lawText);
    if (!cand) return res.status(404).json({ status: "ERROR", message: "No law found" });

    const mst = String(cand.MST || cand.mst || cand.Mst || "");
    const lawId = String(cand.LAW_ID || cand.lawId || cand.LawID || "");
    const lawName = String(cand.LAW_NM || cand.lawName || lawText);

    // 2) 상세(JSON)
    const svcUrl = `${BASE}/lawService.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&MST=${encodeURIComponent(mst)}`;
    const vRes = await fetch(svcUrl, { headers: { "Accept": "application/json" } });
    if (!vRes.ok) throw new Error(`lawService ${vRes.status}`);
    const vJson = await vRes.json();
    const meta = vJson?.law || vJson;

    // 시행일자 필드 보강 추출
    const effective =
      meta?.EFYD || meta?.EFFECTIVE_DATE || meta?.법령정보?.시행일자 || meta?.시행일자 || "";

    return res.status(200).json({
      status: "OK",
      answer: {
        law_name: lawName,
        law_id: lawId,
        mst, // ✅ 이제 포함됨
        source_url: `${BASE}/lawService.do?OC=${encodeURIComponent(OC)}&target=law&MST=${encodeURIComponent(mst)}&type=HTML`,
        effective_date: String(effective || "")
      },
      checklist: [],
      limitations: []
    });
  } catch (e) {
    res.status(500).json({ status: "ERROR", message: e?.message || "Server error" });
  }
}
