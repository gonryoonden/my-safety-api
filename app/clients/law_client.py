# app/clients/law_client.py

from __future__ import annotations
import os
import urllib.parse
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
import logging
import json

# 로깅 설정
logger = logging.getLogger(__name__)

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
    DEFAULT_BASE = "http://www.law.go.kr/DRF"  # 가이드 준수: DRF는 http 권장

    def __init__(self, oc: Optional[str] = None, base_url: Optional[str] = None):
        self.oc = oc or os.getenv("LAW_OC")
        if not self.oc:
            raise ValueError("LAW_OC 환경 변수가 설정되어야 합니다.")
        self.base_url = base_url or os.getenv("LAW_BASE", self.DEFAULT_BASE)
        
        # 브라우저 유사 헤더로 WAF/콘텐츠 협상 이슈 회피
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=15.0),
            follow_redirects=True,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/91.0.4472.124 Safari/537.36"),
                "Accept": "application/json, text/html, */*",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Connection": "close",
            },
            http2=False,
        )
        
    async def close(self):
        await self._client.aclose()

    def _validate_json_response(self, response: httpx.Response) -> Dict:
        """응답의 JSON 유효성을 검사하고 파싱합니다."""
        # 응답이 비어있는지 확인
        if not response.text or response.text.strip() == "":
            raise UpstreamServiceError(
                "법령 서비스에서 빈 응답을 반환했습니다",
                detail="EMPTY_RESPONSE"
            )
        
        # Content-Type 확인
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type or "<html" in response.text.lower():
            # HTML 응답인 경우 오류 메시지 추출 시도
            error_detail = "HTML_RESPONSE"
            if "페이지 접속 실패" in response.text or "오류" in response.text:
                error_detail = "ACCESS_DENIED_OR_ERROR_PAGE"
            elif "인증" in response.text or "권한" in response.text:
                error_detail = "AUTHENTICATION_ERROR"
            
            raise UpstreamServiceError(
                "법령 서비스에서 HTML 오류 페이지를 반환했습니다",
                detail=error_detail
            )
        
        # JSON 파싱 시도
        try:
            return response.json()
        except json.JSONDecodeError as e:
            # JSON 파싱 실패시 응답 내용의 일부를 포함
            preview = response.text[:200] if len(response.text) > 200 else response.text
            raise UpstreamServiceError(
                "법령 서비스 응답을 JSON으로 파싱할 수 없습니다",
                detail=f"JSON_PARSE_ERROR: {str(e)} | Response preview: {preview}"
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(
            lambda exc: (
                isinstance(exc, httpx.RequestError) or
                (isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))
            )
        ),
    )
    async def _get(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        try:
            response = await self._client.get(url, headers=headers or {})
            
            if response.status_code == 429:
                raise httpx.HTTPStatusError(
                    "Rate limit exceeded", request=response.request, response=response
                )
            elif response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error: HTTP {response.status_code}", request=response.request, response=response
                )
                
            response.raise_for_status()
            return response
            
        except httpx.RequestError as e:
            logger.error(f"Request failed for URL {url}: {str(e)}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for URL {url}")
            raise

    async def search_laws(
        self,
        q: str,
        page: int = 1,
        size: int = 10,
        search: int = 1,  # 1: 법령명, 2: 본문
    ) -> Tuple[List[Dict], int]:
        # 유효성 검사
        if search not in (1, 2):
            raise ValueError("search must be 1 (법령명) or 2 (본문)")

        # 한글 인코딩 - EUC-KR도 시도해볼 수 있도록 준비
        encoded_q = quote(q.strip(), safe="", encoding="utf-8")
        
        # 1차: 'search' 미포함 시도
        url1 = (
            f"{self.base_url}/lawSearch.do"
            f"?OC={self.oc}&target=law&type=JSON"
            f"&query={encoded_q}&display={size}&page={page}"
        )
        
        logger.info(f"Attempting primary search: {url1}")
        
        try:
            resp = await self._get(url1)
            data = self._validate_json_response(resp)
            
            container = data.get("LawSearch", data)
            items = container.get("law", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            
            logger.info(f"Primary search successful: {total} results found")
            return items, total
            
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"Primary search failed with network error: {str(e)}")
            raise UpstreamServiceError("법령 검색 서비스 호출 실패", detail=str(e)) from e
        except UpstreamServiceError as e:
            # HTML 응답이나 파싱 오류인 경우 2차 시도
            logger.warning(f"Primary search failed: {e.detail}")
            
            # 2차: 'search' 파라미터를 붙여 재시도
            url2 = (
                f"{self.base_url}/lawSearch.do"
                f"?OC={self.oc}&target=law&type=JSON"
                f"&query={encoded_q}&display={size}&page={page}&search={search}"
            )
            
            logger.info(f"Attempting secondary search: {url2}")
            
            try:
                resp2 = await self._get(url2)
                data2 = self._validate_json_response(resp2)
                
                container = data2.get("LawSearch", data2)
                items = container.get("law", [])
                if isinstance(items, dict):
                    items = [items]
                total = int(container.get("totalCnt", 0))
                
                logger.info(f"Secondary search successful: {total} results found")
                return items, total
                
            except Exception as e2:
                logger.error(f"Secondary search also failed: {str(e2)}")
                # 원래 오류를 다시 발생시키되, 추가 정보 포함
                if isinstance(e2, UpstreamServiceError):
                    e2.detail = f"Primary: {e.detail} | Secondary: {e2.detail}"
                    raise e2
                else:
                    raise UpstreamServiceError(
                        "법령 검색 결과 처리 중 예외 발생", 
                        detail=f"Primary: {e.detail} | Secondary: {str(e2)}"
                    ) from e2

    async def get_law_detail(self, law_id: str) -> Dict:
        detail_url = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=JSON&ID={law_id}"
        
        logger.info(f"Fetching law detail: {detail_url}")
        
        try:
            resp = await self._get(detail_url)
            data = self._validate_json_response(resp)
            
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
                ef_part = f"&efYd={eff}" if eff else ""
                src = f"{self.base_url}/lawService.do?OC={self.oc}&target=law&type=HTML&MST={mst}{ef_part}"
            else:
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
        except UpstreamServiceError:
            raise
        except Exception as e:
            raise UpstreamServiceError("법령 상세 정보 처리 중 예외 발생", detail=str(e)) from e

    async def search_attachments(self, q: str, page: int = 1, size: int = 10) -> Tuple[List[Dict], int]:
        encoded_q = urllib.parse.quote(q.strip(), safe="", encoding="utf-8")
        json_url = f"{self.base_url}/lawSearch.do?OC={self.oc}&target=licbyl&type=JSON&query={encoded_q}&display={size}&page={page}"
        
        logger.info(f"Searching attachments: {json_url}")
        
        try:
            resp = await self._get(json_url)
            data = self._validate_json_response(resp)
            
            container = data.get("licBylSearch", data)
            items = container.get("licbyl", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            return items, total
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise UpstreamServiceError("별표/서식 검색 서비스 호출 실패", detail=str(e)) from e
        except UpstreamServiceError:
            raise
        except Exception as e:
            raise UpstreamServiceError("별표/서식 검색 결과 처리 중 예외 발생", detail=str(e)) from e