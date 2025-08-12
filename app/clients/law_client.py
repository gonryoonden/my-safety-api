# app/clients/law_client.py

from __future__ import annotations
import os
import urllib.parse
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

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
    DEFAULT_BASE = "http://www.law.go.kr/DRF" # 가이드 준수: DRF는 http 권장

    def __init__(self, oc: Optional[str] = None, base_url: Optional[str] = None):
        self.oc = oc or os.getenv("LAW_OC")
        if not self.oc:
            raise ValueError("LAW_OC 환경 변수가 설정되어야 합니다.")
        self.base_url = base_url or os.getenv("LAW_BASE", self.DEFAULT_BASE)
        # 브라우저 유사 헤더로 WAF/콘텐츠 협상 이슈 회피
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=6.0, read=20.0, write=10.0, pool=8.0),
            follow_redirects=True,
            headers={
                # 예전 성공 사례와 유사하게 UA만 필수로 유지
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/91.0.4472.124 Safari/537.36"),
                # 필요시 주석 해제
                # "Accept-Language": "ko-KR,ko;q=0.9",
                # "Referer": "http://www.law.go.kr/DRF/index.do",
                "Connection": "close",
            },
            http2=False,
        )
        
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

    async def search_laws(
        self,
        q: str,
        page: int = 1,
        size: int = 10,
        search: int = 1,  # 1: 법령명, 2: 본문 (2차 시도에만 사용)
    ) -> Tuple[List[Dict], int]:
        # 유효성 검사: 가이드 기준 1 또는 2만 허용
        if search not in (1, 2):
            raise ValueError("search must be 1 (법령명) or 2 (본문)")

        # 표준 라이브러리 quote 사용 (httpx.utils.quote 절대 사용하지 않음)
        encoded_q = quote(q.strip(), safe="")

        # 1차: 예전 형태와 동일하게 'search' 미포함
        url1 = (
            f"{self.base_url}/lawSearch.do"
            f"?OC={self.oc}&target=law&type=JSON"
            f"&query={encoded_q}&display={size}&page={page}"
        )
        try:
            resp = await self._get(url1)

            # --- 👇 여기부터 디버깅 코드 추가 👇 ---
            print("--- DEBUG START ---")
            print(f"Request URL: {url1}")
            print(f"Upstream Status Code: {resp.status_code}")
            print(f"Upstream Content-Type: {resp.headers.get('content-type','')}")
            print(f"Upstream Response Text: {resp.text}")
            # --- 👆 여기까지 디버깅 코드 추가 👆 ---
            # HTML(오류페이지) 탐지 → 2차 시도
            ctype = (resp.headers.get("content-type") or "").lower()
            if "text/html" in ctype or "<html" in resp.text.lower() or "페이지 접속 실패" in resp.text:
                raise ValueError("HTML_200_DETECTED")

            data = resp.json()
            container = data.get("LawSearch", data)
            items = container.get("law", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            return items, total
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            # 상위 서비스 오류를 표준 포맷으로 매핑 (FastAPI에서 503으로 변환됨)
            raise UpstreamServiceError("법령 검색 서비스 호출 실패", detail=str(e)) from e
        except Exception:
            # 2차: 'search' 파라미터를 붙여 재시도 (1 또는 2만 허용)
            if search not in (1, 2):
                search = 1
            url2 = (
                f"{self.base_url}/lawSearch.do"
                f"?OC={self.oc}&target=law&type=JSON"
                f"&query={encoded_q}&display={size}&page={page}&search={search}"
            )
            resp2 = await self._get(url2)
            print("--- RETRY WITH 'search' ---")
            print(f"Request URL: {url2}")
            print(f"Upstream Content-Type: {resp2.headers.get('content-type','')}")
            print(f"Upstream Response Text: {resp2.text}")
            print("--- /RETRY ---")
            ctype2 = (resp2.headers.get("content-type") or "").lower()
            if "text/html" in ctype2 or "<html" in resp2.text.lower() or "페이지 접속 실패" in resp2.text:
                raise UpstreamServiceError(
                    "법령 검색 결과 처리 중 예외 발생",
                    detail="UPSTREAM_INVALID_HTML_200",
                )
            try:
                data2 = resp2.json()
            except Exception as je:
                raise UpstreamServiceError("법령 검색 결과 처리 중 예외 발생", detail=str(je)) from je
            container = data2.get("LawSearch", data2)
            items = container.get("law", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            return items, total
    async def get_law_detail(self, law_id: str) -> Dict:
        detail_url = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=JSON&ID={law_id}"
        try:
            resp = await self._get(detail_url, headers={"Accept": "application/json"})
            data = resp.json()
            # API 응답 구조가 가변적이므로 여러 키를 확인
            law_info = data.get("법령", {}).get("기본정보", data.get("law", {}))
            if not law_info:
                raise LawNotFoundError()

            mst = law_info.get("MST") or law_info.get("법령일련번호")
            title = (
                law_info.get("법령명_한글")
                or law_info.get("법령명한글")
                or law_info.get("LAW_NM")
                or ""
            )
            eff = law_info.get("시행일자") or law_info.get("EF_YD") or ""

            # HTML 원문 링크 구성 (MST 우선, 없으면 ID)
            if mst:
                # MST가 있으면 가능한 경우 efYd(시행일자)도 함께 붙여 정확 버전 링크
                ef_part = f"&efYd={eff}" if eff else ""
                src = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=HTML&MST={mst}{ef_part}"
            else:
                # ID만으로 접근 (efYd는 일반적으로 MST와 함께 제공되므로 생략)
                src = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=HTML&ID={law_id}"

            return {
                "law_id": law_id,
                "title": title,
                "effective_date": eff,
                "source_url": src,
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise LawNotFoundError() from e
            raise UpstreamServiceError("법령 상세 조회 서비스 호출 실패", detail=str(e)) from e
        except Exception as e:
            raise UpstreamServiceError("법령 상세 정보 처리 중 예외 발생", detail=str(e)) from e

    async def search_attachments(self, q: str, page: int = 1, size: int = 10) -> Tuple[List[Dict], int]:
        encoded_q = urllib.parse.quote(q.strip())
        # '별표, 서식(법령)정보 가이드.txt'에 따라 target=licbyl 로 설정
        json_url = f"{self.base_url}/lawSearch.do?OC={self.oc}&target=licbyl&type=JSON&query={encoded_q}&display={size}&page={page}"
        try:
            resp = await self._get(json_url, headers={"Accept": "application/json"})
            data = resp.json()
            container = data.get("licBylSearch", data) # 가이드에 명시된 응답 키
            items = container.get("licbyl", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            return items, total
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise UpstreamServiceError("별표/서식 검색 서비스 호출 실패", detail=str(e)) from e
        except Exception as e:
            raise UpstreamServiceError("별표/서식 검색 결과 처리 중 예외 발생", detail=str(e)) from e