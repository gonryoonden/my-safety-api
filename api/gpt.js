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

// lawSearch: JSON 우선 → 실패/HTML이면 XML 폴백 + 디버그
async function searchLaws(lawText) {
  const q = encodeURIComponent(lawText);
  const urlJSON = `${BASE}/lawSearch.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&query=${q}&display=10&page=1`;
  const urlXML  = `${BASE}/lawSearch.do?OC=${encodeURIComponent(OC)}&target=law&type=XML&query=${q}&display=10&page=1`;

  // JSON 우선
  try {
    const r = await fetch(urlJSON, {
      headers: { "Accept": "application/json", "User-Agent": "my-safety-api/1.0" }
    });
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    const body = await r.text();
    if (r.ok && ct.includes("application/json")) {
      const j = JSON.parse(body);
      const items = j?.Laws?.law ?? j?.law ?? [];
      return { items, debug: { source: "json", ct, url: urlJSON.replace(/OC=[^&]+/, "OC=***") } };
    }
    if (body) {
      return { items: [], debug: { source: "json-non-json", ct, sample: body.slice(0,160), url: urlJSON.replace(/OC=[^&]+/, "OC=***") } };
    }
  } catch (_) { /* 계속 XML 시도 */ }

  // XML 폴백
  try {
    const rx = await fetch(urlXML, { headers: { "User-Agent": "my-safety-api/1.0" } });
    const ct = (rx.headers.get("content-type") || "").toLowerCase();
    const xml = await rx.text();
    const blocks = [...xml.matchAll(/<law>([\s\S]*?)<\/law>/g)].map(m => m[1]);
    const items = blocks.map(b => ({
      MST: (b.match(/<MST>(.*?)<\/MST>/) || [])[1] || "",
      LAW_ID: (b.match(/<LAW_ID>(.*?)<\/LAW_ID>/) || [])[1] || "",
      LAW_NM: (b.match(/<LAW_NM>(.*?)<\/LAW_NM>/) || [])[1] || ""
    })).filter(x => x.MST);

    if (items.length) {
      return { items, debug: { source: "xml", ct, url: urlXML.replace(/OC=[^&]+/, "OC=***") } };
    }
    return { items: [], debug: { source: "xml-empty", ct, sample: xml.slice(0,160), url: urlXML.replace(/OC=[^&]+/, "OC=***") } };
  } catch (e) {
    return { items: [], debug: { source: "xml-fail", error: String(e) } };
  }
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
