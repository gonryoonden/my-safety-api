export default async function handler(req, res) {
  // CORS (개발용)
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.status(204).end();
    return;
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method !== 'POST') {
    res.status(405).json({ status: "ERROR", message: "Method Not Allowed" });
    return;
  }

  try {
    const { function_name, arguments: args } = req.body || {};

    if (function_name === "search_safety_law") {
      // 🔸연동 확인용 더미 응답 (우선 Actions 연결부터 성공시키는 목적)
      return res.status(200).json({
        status: "OK",
        answer: {
          law_name: "산업안전보건기준에 관한 규칙",
          law_id: "007363",
          // law.go.kr 예시 링크 (MST는 이후 실제 검색로직에서 대체)
          source_url: "http://www.law.go.kr/DRF/lawService.do?OC=shg30335&target=law&MST=272927&type=HTML",
          effective_date: "20250717"
        },
        checklist: [],
        limitations: []
      });
    }

    res.status(400).json({ status: "ERROR", message: "Unknown function_name" });
  } catch (e) {
    res.status(500).json({ status: "ERROR", message: e?.message || "Server error" });
  }
}
