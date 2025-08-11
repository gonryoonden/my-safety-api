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
        encoded_q = httpx.utils.quote(q.strip())
        json_url = f"{self.base_url}/lawSearch.do?OC={self.oc}&target=law&type=JSON&query={encoded_q}&display={size}&page={page}"
        try:
            resp = await self._get(json_url, headers={"Accept": "application/json"})
            data = resp.json()
            items = data.get("law", [])
            if isinstance(items, dict):
                items = [items]
            total = int(data.get("totalCnt", 0))
            return items, total
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise UpstreamServiceError("법령 검색 서비스 호출 실패", detail=str(e)) from e
        except Exception as e:
            raise UpstreamServiceError("법령 검색 결과 처리 중 예외 발생", detail=str(e)) from e

    async def get_law_detail(self, law_id: str) -> Dict:
        detail_url = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=JSON&ID={law_id}"
        try:
            resp = await self._get(detail_url, headers={"Accept": "application/json"})
            data = resp.json()
            # API 응답 구조가 가변적이므로 여러 키를 확인
            law_info = data.get("법령", {}).get("기본정보", data.get("law"))
            if not law_info:
                raise LawNotFoundError(f"ID '{law_id}'에 해당하는 법령을 찾을 수 없습니다.")
            return law_info
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise UpstreamServiceError(f"법령 상세 정보({law_id}) 조회 실패", detail=str(e)) from e
        except LawNotFoundError:
            raise
        except Exception as e:
            raise UpstreamServiceError(f"법령 상세 정보({law_id}) 처리 중 예외 발생", detail=str(e)) from e