// api/gpt.js
const OC = process.env.LAW_OC; // 예: shg30335
const BASE = process.env.LAW_BASE || "https://www.law.go.kr/DRF";

// 후보 선택: 완전일치 > 부분일치 > 첫번째
function pickCandidate(items, q) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const exact = items.find(x => (x.LAW_NM || "").trim() === q.trim());
  if (exact) return exact;
  const includes = items.find(x => (x.LAW_NM || "").includes(q.trim()));
  return includes || items[0];
}

// lawSearch: JSON 우선 시도 → 실패/HTML이면 XML로 폴백
async function searchLaws(lawText) {
  const q = encodeURIComponent(lawText);
  const urlJSON = `${BASE}/lawSearch.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&query=${q}&display=5&page=1`;
  const urlXML  = `${BASE}/lawSearch.do?OC=${encodeURIComponent(OC)}&target=law&type=XML&query=${q}&display=5&page=1`;

  try {
    const r = await fetch(urlJSON, { headers: { Accept: "application/json" } });
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (r.ok && ct.includes("application/json")) {
      const j = await r.json();
      return j?.Laws?.law ?? j?.law ?? [];
    }
    // JSON이 아닌 경우 아래로 폴백
  } catch (_) {
    // 무시하고 XML 폴백
  }

  const rx = await fetch(urlXML);
  const xml = await rx.text();
  // 간단 파서: <law>…</law> 블록에서 필요한 필드만 추출
  const blocks = [...xml.matchAll(/<law>([\s\S]*?)<\/law>/g)].map(m => m[1]);
  const items = blocks.map(b => ({
    MST: (b.match(/<MST>(.*?)<\/MST>/) || [])[1] || "",
    LAW_ID: (b.match(/<LAW_ID>(.*?)<\/LAW_ID>/) || [])[1] || "",
    LAW_NM: (b.match(/<LAW_NM>(.*?)<\/LAW_NM>/) || [])[1] || ""
  })).filter(x => x.MST);
  return items;
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
    if (!OC) return res.status(500).json({ status: "ERROR", message: "LAW_OC is not set" });

    const lawText = String(args.law_text || "").trim();
    if (!lawText) return res.status(400).json({ status: "ERROR", message: "law_text is required" });

    // 1) 검색(JSON→XML 폴백)
    const items = await searchLaws(lawText);
    const cand = pickCandidate(items, lawText);
    if (!cand) return res.status(404).json({ status: "ERROR", message: "No law found" });

    const mst = String(cand.MST || cand.mst || cand.Mst || "");
    const lawId = String(cand.LAW_ID || cand.lawId || cand.LawID || "");
    const lawName = String(cand.LAW_NM || cand.lawName || lawText);

    // 2) 상세(JSON) — 시행일자 추출
    const svcUrl = `${BASE}/lawService.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&MST=${encodeURIComponent(mst)}`;
    const vRes = await fetch(svcUrl, { headers: { Accept: "application/json" } });
    if (!vRes.ok) throw new Error(`lawService ${vRes.status}`);
    const vJson = await vRes.json();
    const meta = vJson?.law || vJson;
    const effective =
      meta?.EFYD || meta?.EFFECTIVE_DATE || meta?.법령정보?.시행일자 || meta?.시행일자 || "";

    // 3) 응답
    return res.status(200).json({
      status: "OK",
      answer: {
        law_name: lawName,
        law_id: lawId,
        mst,
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
