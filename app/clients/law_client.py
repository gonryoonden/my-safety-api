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
    DEFAULT_BASE = "http://www.law.go.kr/DRF"

    def __init__(self, oc: Optional[str] = None, base_url: Optional[str] = None):
        self.oc = oc or os.getenv("LAW_OC")
        if not self.oc:
            raise ValueError("LAW_OC 환경 변수가 설정되어야 합니다.")
        self.base_url = base_url or os.getenv("LAW_BASE", self.DEFAULT_BASE)
        
                # --- 👇 이 부분을 아래 코드로 교체하세요 👇 ---
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            # 테스트 4에서 성공한 헤더 조합을 적용합니다.
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
                "Referer": "http://www.law.go.kr/", # 가장 중요한 해결의 열쇠!
            }
        )
        # --- 👆 여기까지 교체 👆 ---
        
    async def close(self):
        await self._client.aclose()

    async def _make_request_with_fallback(self, base_url: str, params: Dict[str, str]) -> httpx.Response:
        """여러 헤더 조합을 시도하여 요청을 보냅니다."""
        
        # 시도할 헤더 조합들 (성공 확률 높은 순서)
        header_combinations = [
            # 1. 완전한 브라우저 헤더 + Referer
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
                "Accept-Encoding": "gzip, deflate",
                "Referer": "http://www.law.go.kr/",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0"
            },
            
            # 2. 최소한의 브라우저 헤더
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "http://www.law.go.kr/"
            },
            
            # 3. IE 헤더 (정부 사이트에서 종종 필요)
            {
                "User-Agent": "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 10.0; Win64; x64; Trident/4.0)",
                "Accept": "text/html, application/xhtml+xml, */*",
                "Accept-Language": "ko-KR",
                "Referer": "http://www.law.go.kr/"
            }
        ]
        
        # URL 구성
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        full_url = f"{base_url}?{query_string}"
        
        last_error = None
        
        for i, headers in enumerate(header_combinations, 1):
            try:
                logger.info(f"헤더 조합 {i} 시도: {full_url}")
                
                # 새로운 클라이언트로 요청 (헤더 덮어쓰기 방지)
                async with httpx.AsyncClient(
                    timeout=30.0, 
                    follow_redirects=True,
                    http2=False
                ) as temp_client:
                    response = await temp_client.get(full_url, headers=headers)
                    
                    # HTML 응답이 아닌 경우 성공으로 간주
                    content_type = (response.headers.get("content-type") or "").lower()
                    
                    if response.status_code == 200 and "text/html" not in content_type:
                        logger.info(f"헤더 조합 {i} 성공!")
                        return response
                    
                    # JSON 응답인지 확인
                    if "application/json" in content_type:
                        logger.info(f"헤더 조합 {i}에서 JSON 응답 수신")
                        return response
                        
                    logger.warning(f"헤더 조합 {i} 실패: HTML 응답 (Content-Type: {content_type})")
                    
            except Exception as e:
                logger.warning(f"헤더 조합 {i} 실패: {str(e)}")
                last_error = e
                continue
        
        # 모든 조합이 실패한 경우
        raise UpstreamServiceError(
            "모든 헤더 조합을 시도했으나 JSON 응답을 받을 수 없습니다",
            detail=f"마지막 오류: {str(last_error) if last_error else 'ALL_ATTEMPTS_FAILED'}"
        )

    def _validate_json_response(self, response: httpx.Response) -> Dict:
        """응답의 JSON 유효성을 검사하고 파싱합니다."""
        if not response.text or response.text.strip() == "":
            raise UpstreamServiceError(
                "법령 서비스에서 빈 응답을 반환했습니다",
                detail="EMPTY_RESPONSE"
            )
        
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type or "<html" in response.text.lower():
            # HTML 응답 세부 분석
            text_lower = response.text.lower()
            if any(keyword in text_lower for keyword in ["인증", "권한", "허가", "승인"]):
                error_detail = "AUTHENTICATION_ERROR - API 키를 확인하세요"
            elif any(keyword in text_lower for keyword in ["접속", "차단", "제한"]):
                error_detail = "ACCESS_BLOCKED - IP 또는 요청이 차단됨"
            else:
                error_detail = f"HTML_RESPONSE - Content-Type: {content_type}"
            
            raise UpstreamServiceError(
                "법령 서비스에서 HTML 응답을 반환했습니다",
                detail=error_detail
            )
        
        try:
            return response.json()
        except json.JSONDecodeError as e:
            preview = response.text[:300] if len(response.text) > 300 else response.text
            raise UpstreamServiceError(
                "JSON 파싱 실패",
                detail=f"JSON_PARSE_ERROR: {str(e)} | Preview: {preview}"
            )

    async def search_laws(
        self,
        q: str,
        page: int = 1,
        size: int = 10,
        search: int = 1,
    ) -> Tuple[List[Dict], int]:
        if search not in (1, 2):
            raise ValueError("search must be 1 (법령명) or 2 (본문)")

        # UTF-8 인코딩
        encoded_q = quote(q.strip(), safe="", encoding="utf-8")
        
        # 기본 파라미터
        params = {
            "OC": self.oc,
            "target": "law",
            "type": "JSON",
            "query": encoded_q,
            "display": str(size),
            "page": str(page)
        }
        
        try:
            # 1차 시도: search 파라미터 없이
            response = await self._make_request_with_fallback(
                f"{self.base_url}/lawSearch.do", 
                params
            )
            data = self._validate_json_response(response)
            
            container = data.get("LawSearch", data)
            items = container.get("law", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            
            return items, total
            
        except UpstreamServiceError as e:
            # 2차 시도: search 파라미터 추가
            logger.warning(f"1차 시도 실패, 2차 시도 중: {e.detail}")
            
            params_with_search = {**params, "search": str(search)}
            
            try:
                response = await self._make_request_with_fallback(
                    f"{self.base_url}/lawSearch.do", 
                    params_with_search
                )
                data = self._validate_json_response(response)
                
                container = data.get("LawSearch", data)
                items = container.get("law", [])
                if isinstance(items, dict):
                    items = [items]
                total = int(container.get("totalCnt", 0))
                
                return items, total
                
            except Exception as e2:
                raise UpstreamServiceError(
                    "법령 검색 실패 (1차, 2차 모두 실패)",
                    detail=f"1차: {e.detail} | 2차: {str(e2)}"
                )

    async def get_law_detail(self, law_id: str) -> Dict:
        params = {
            "OC": self.oc,
            "target": "law",
            "type": "JSON",
            "ID": law_id
        }
        
        try:
            response = await self._make_request_with_fallback(
                f"{self.base_url}/lawService.do",
                params
            )
            
            if response.status_code == 404:
                raise LawNotFoundError()
                
            data = self._validate_json_response(response)
            
            law_info = data.get("법령", {}).get("기본정보", data.get("law", {}))
            if not law_info:
                raise LawNotFoundError()

            mst = law_info.get("MST") or law_info.get("법령일련번호")
            title = (
                law_info.get("법령명_한글") or
                law_info.get("법령명한글") or
                law_info.get("LAW_NM") or ""
            )
            eff = law_info.get("시행일자") or law_info.get("EF_YD") or ""

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

        except LawNotFoundError:
            raise
        except Exception as e:
            if isinstance(e, UpstreamServiceError):
                raise
            raise UpstreamServiceError("법령 상세 조회 실패", detail=str(e)) from e

    async def search_attachments(self, q: str, page: int = 1, size: int = 10) -> Tuple[List[Dict], int]:
        encoded_q = quote(q.strip(), safe="", encoding="utf-8")
        
        params = {
            "OC": self.oc,
            "target": "licbyl",
            "type": "JSON",
            "query": encoded_q,
            "display": str(size),
            "page": str(page)
        }
        
        try:
            response = await self._make_request_with_fallback(
                f"{self.base_url}/lawSearch.do",
                params
            )
            data = self._validate_json_response(response)
            
            container = data.get("licBylSearch", data)
            items = container.get("licbyl", [])
            if isinstance(items, dict):
                items = [items]
            total = int(container.get("totalCnt", 0))
            return items, total
            
        except Exception as e:
            if isinstance(e, UpstreamServiceError):
                raise
            raise UpstreamServiceError("별표/서식 검색 실패", detail=str(e)) from e