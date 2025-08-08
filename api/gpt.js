// api/gpt.js (CommonJS)
// Node 16+ / Vercel Node.js 환경 가정
'use strict';

const OC = process.env.LAW_OC; // 예: shg30335
const BASE = process.env.LAW_BASE || 'https://www.law.go.kr/DRF';

// 후보 선택: 완전일치 > 부분일치 > 첫번째
function pickCandidate(items, q) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const t = (q || '').trim();
  const exact = items.find(x => ((x.LAW_NM || '').trim() === t));
  if (exact) return exact;
  const includes = items.find(x => (x.LAW_NM || '').includes(t));
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
      headers: { Accept: 'application/json', 'User-Agent': 'my-safety-api/1.0' }
    });
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    const body = await r.text();
    if (r.ok && ct.includes('application/json')) {
      const j = JSON.parse(body || '{}');
      const items = j?.Laws?.law ?? j?.law ?? [];
      return { items, debug: { source: 'json', ct, url: urlJSON.replace(/OC=[^&]+/, 'OC=***') } };
    }
    if (body) {
      return {
        items: [],
        debug: {
          source: 'json-non-json',
          ct,
          sample: body.slice(0, 160),
          url: urlJSON.replace(/OC=[^&]+/, 'OC=***')
        }
      };
    }
  } catch (_) {
    // XML로 폴백
  }

  // XML 폴백
  try {
    const rx = await fetch(urlXML, { headers: { 'User-Agent': 'my-safety-api/1.0' } });
    const ct = (rx.headers.get('content-type') || '').toLowerCase();
    const xml = await rx.text();
    const blocks = [...xml.matchAll(/<law>([\s\S]*?)<\/law>/g)].map(m => m[1]);
    const items = blocks.map(b => ({
      MST:    (b.match(/<MST>(.*?)<\/MST>/) || [])[1] || '',
      LAW_ID: (b.match(/<LAW_ID>(.*?)<\/LAW_ID>/) || [])[1] || '',
      LAW_NM: (b.match(/<LAW_NM>(.*?)<\/LAW_NM>/) || [])[1] || ''
    })).filter(x => x.MST);

    if (items.length) {
      return { items, debug: { source: 'xml', ct, url: urlXML.replace(/OC=[^&]+/, 'OC=***') } };
    }
    return {
      items: [],
      debug: { source: 'xml-empty', ct, sample: xml.slice(0, 160), url: urlXML.replace(/OC=[^&]+/, 'OC=***') }
    };
  } catch (e) {
    return { items: [], debug: { source: 'xml-fail', error: String(e) } };
  }
}

// ✅ CommonJS export
module.exports = async (req, res) => {
  // CORS & 헬스
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS, GET');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.status(204).end();
    return;
  }

  if (req.method === 'GET') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(200).json({ ok: true, message: 'Use POST /api/gpt' });
    return;
  }

  if (req.method !== 'POST') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(405).json({ status: 'ERROR', message: 'Method Not Allowed' });
    return;
  }

  res.setHeader('Access-Control-Allow-Origin', '*');

  try {
    // Vercel Node 함수에서 req.body가 문자열일 수 있음
    const raw = req.body ?? {};
    const body = (typeof raw === 'string') ? JSON.parse(raw || '{}') : raw;

    // "arguments"는 JS 예약어라 혼선을 피하기 위해 다른 식별자 사용
    const { function_name, arguments: argsRaw } = body;
    const args = argsRaw ?? {};

    if (function_name !== 'search_safety_law') {
      return res.status(400).json({ status: 'ERROR', message: 'Unknown function_name' });
    }
    if (!OC) {
      return res.status(500).json({ status: 'ERROR', message: 'LAW_OC is not set' });
    }

    const lawText = String(args.law_text || '').trim();
    if (!lawText) {
      return res.status(400).json({ status: 'ERROR', message: 'law_text is required' });
    }

    // 1) 검색(JSON→XML 폴백)
    const { items, debug } = await searchLaws(lawText);
    const cand = pickCandidate(items, lawText);
    if (!cand) {
      return res.status(502).json({ status: 'ERROR', message: 'No law found', debug });
    }

    const mst = String(cand.MST || cand.mst || cand.Mst || '');
    const lawId = String(cand.LAW_ID || cand.lawId || cand.LawID || '');
    const lawName = String(cand.LAW_NM || cand.lawName || lawText);

    // 2) 상세(JSON) — 시행일자 추출
    const svcUrl = `${BASE}/lawService.do?OC=${encodeURIComponent(OC)}&target=law&type=JSON&MST=${encodeURIComponent(mst)}`;
    const vRes = await fetch(svcUrl, { headers: { Accept: 'application/json', 'User-Agent': 'my-safety-api/1.0' } });
    const vCt = (vRes.headers.get('content-type') || '').toLowerCase();
    const vBody = await vRes.text();
    let vJson = {};
    if (vRes.ok && vCt.includes('application/json')) {
      try { vJson = JSON.parse(vBody || '{}'); } catch { /* ignore */ }
    }
    const meta = vJson?.law || vJson;
    const effective =
      meta?.EFYD || meta?.EFFECTIVE_DATE || meta?.법령정보?.시행일자 || meta?.시행일자 || '';

    // 3) 응답
    return res.status(200).json({
      status: 'OK',
      answer: {
        law_name: lawName,
        law_id: lawId,
        mst,
        source_url: `${BASE}/lawService.do?OC=${encodeURIComponent(OC)}&target=law&MST=${encodeURIComponent(mst)}&type=HTML`,
        effective_date: String(effective || '')
      },
      checklist: [],
      limitations: []
    });
  } catch (e) {
    res.status(500).json({ status: 'ERROR', message: e?.message || 'Server error' });
  }
};
