# app/clients/law_client.py

from __future__ import annotations
import os
import re
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from typing import Dict, List, Optional, Tuple
class LawNotFoundError(Exception):
    """주어진 ID로 법령을 찾을 수 없을 때 발생하는 예외"""
    pass

class UpstreamServiceError(Exception):
    """상위 법령 서비스에서 예기치 않은 오류를 반환할 때 발생하는 예외"""
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.detail = detail

class LawClient:
    """법령 검색 및 상세 정보 조회를 위한 클라이언트"""
    DEFAULT_BASE = "https://www.law.go.kr/DRF"

    def __init__(self, oc: Optional[str] = None, base_url: Optional[str] = None):
        self.oc = oc or os.getenv("LAW_OC")
        if not self.oc:
            raise ValueError("LAW_OC 환경 변수가 설정되어야 합니다.")
        self.base_url = base_url or os.getenv("LAW_BASE", self.DEFAULT_BASE)
        self._client = httpx.AsyncClient(timeout=5.0)

    async def close(self):
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(
            lambda exc: (
                isinstance(exc, httpx.RequestError) or
                (isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))
            )
        ),
    )
    async def _get(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        response = await self._client.get(url, headers=headers or {})
        if response.status_code == 429 or response.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code} error", request=response.request, response=response
            )
        response.raise_for_status()
        return response

    async def search_laws(self, q: str, page: int = 1, size: int = 10) -> Tuple[List[Dict], int]:
        # ... (이전 답변의 law_client.py 내 search_laws 함수 내용과 동일) ...
        # 이 부분은 매우 길기 때문에 생략하며, 이전 답변에서 제공된 코드를 그대로 사용하시면 됩니다.
        # 핵심은 LawClient 클래스 안에 이 함수가 포함된다는 것입니다.
        # (실제 구현 시에는 전체 코드를 붙여넣어야 합니다.)
        # For brevity, this is a placeholder. In reality, you'd paste the full function code.
        # Start of placeholder
        encoded_q = httpx.utils.quote(q.strip())
        json_url = f"{self.base_url}/lawSearch.do?OC={self.oc}&target=law&type=JSON&query={encoded_q}&display={size}&page={page}"
        try:
            resp = await self._get(json_url, headers={"Accept": "application/json"})
            data = resp.json()
            items = data.get("law", [])
            total = int(data.get("totalCount", 0))
            return items, total
        except Exception as e:
            raise UpstreamServiceError("Search failed", detail=str(e)) from e
        # End of placeholder

    async def get_law_detail(self, law_id: str) -> Dict:
        # ... (이전 답변의 law_client.py 내 get_law_detail 함수 내용과 동일) ...
        # (실제 구현 시에는 전체 코드를 붙여넣어야 합니다.)
        # For brevity, this is a placeholder. In reality, you'd paste the full function code.
        # Start of placeholder
        # Simplified logic: In a real scenario, this would likely involve another search to get MST
        detail_url = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=JSON&ID={law_id}"
        try:
            resp = await self._get(detail_url, headers={"Accept": "application/json"})
            if resp.status_code == 404:
                raise LawNotFoundError()
            data = resp.json()
            law_info = data.get("law", {})
            source_url = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&MST={law_info.get('MST', '')}&type=HTML"
            return {
                "law_id": law_id,
                "title": law_info.get("LAW_NM", ""),
                "effective_date": law_info.get("EFYD", ""),
                "source_url": source_url
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise LawNotFoundError() from e
            raise UpstreamServiceError("Get detail failed", detail=str(e)) from e
        except Exception as e:
            raise UpstreamServiceError("Get detail failed", detail=str(e)) from e
        # End of placeholder
```