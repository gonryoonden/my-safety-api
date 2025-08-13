# main.py

from __future__ import annotations
from dotenv import load_dotenv; load_dotenv()
import asyncio
from typing import AsyncGenerator
from fastapi import FastAPI, Query, Request, Depends
from fastapi.responses import JSONResponse

# 우리가 분리한 모듈들을 임포트합니다.
from app.clients.law_client import LawClient, LawNotFoundError, UpstreamServiceError
from app.schemas import (
    ErrorResponse, LawDetail, LawSearchItem, SearchResponse,
    AttachmentItem, AttachmentSearchResponse
)

# --- FastAPI 앱 설정 ---
app = FastAPI(
    title="산업안전 법령 조회 API",
    version="1.0.0",
    description="대한민국 법령정보센터 Open API를 활용하여 산업안전 관련 법령을 조회하는 API입니다."
)

# --- 의존성 주입 (Dependency Injection) ---
async def get_law_client() -> AsyncGenerator[LawClient, None]:
    client = LawClient()
    try:
        yield client
    finally:
        await client.close()

# --- 예외 처리 핸들러 (Exception Handlers) ---
@app.exception_handler(LawNotFoundError)
async def handle_law_not_found(request: Request, exc: LawNotFoundError):
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(code="LAW_NOT_FOUND", message="해당 법령 ID를 찾을 수 없습니다.").model_dump(),
    )

@app.exception_handler(UpstreamServiceError)
async def handle_upstream_error(request: Request, exc: UpstreamServiceError):
    return JSONResponse(
        status_code=503,  # 503 Service Unavailable
        content=ErrorResponse(
            code="UPSTREAM_ERROR",
            message="법령 서비스 오류(잠시 후 재시도)",
            detail=exc.detail,
        ).model_dump(),
    )

@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            code="INVALID_PARAMETER",
            message="잘못된 매개변수입니다.",
            detail=str(exc),
        ).model_dump(),
    )

# --- API 라우트 (Endpoints) ---

@app.get("/debug/law-api")
async def debug_law_api(
    q: str = Query("산업안전", description="테스트할 검색어"),
    client: LawClient = Depends(get_law_client),
):
    """
    법령 API 연결 상태를 디버깅하는 엔드포인트
    """
    import httpx
    import urllib.parse
    import os
    
    # 환경 변수 확인
    oc = os.getenv("LAW_OC")
    base_url = os.getenv("LAW_BASE", "http://www.law.go.kr/DRF")
    
    # 직접 요청 테스트
    encoded_q = urllib.parse.quote(q, safe="", encoding="utf-8")
    test_url = f"{base_url}/lawSearch.do?OC={oc}&target=law&type=JSON&query={encoded_q}&display=5&page=1"
    
    masked_test_url = client._mask_oc_in_url(test_url)

    debug_info = {
        "environment": {
            "LAW_OC": oc[:4] + "****" if oc and len(oc) > 4 else "NOT_SET",
            "LAW_BASE": base_url,
        },
        "test_url": masked_test_url,
        "encoded_query": encoded_q,
        "original_query": q,
        "tests": {}
    }
    
    # 여러 가지 헤더 조합으로 테스트
    test_headers = [
        # 테스트 1: 기본 httpx 헤더
        {},
        
        # 테스트 2: 간단한 브라우저 헤더
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
        
        # 테스트 3: 완전한 브라우저 헤더 (크롬)
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        },
        
        # 테스트 4: 정부사이트 접근용 헤더
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "http://www.law.go.kr/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    ]
    
    for i, headers in enumerate(test_headers, 1):
        test_name = f"test_{i}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as test_client:
                response = await test_client.get(test_url, headers=headers)
                
                test_result = {
                    "headers_used": headers,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "content_length": len(response.text),
                    "response_preview": response.text[:300],
                    "is_json": False,
                    "parsed_data": None,
                }
                
                # JSON 파싱 시도
                try:
                    json_data = response.json()
                    test_result["is_json"] = True
                    test_result["parsed_data"] = json_data
                    test_result["success"] = True
                except Exception as parse_error:
                    test_result["json_parse_error"] = str(parse_error)
                    test_result["success"] = False
                
                debug_info["tests"][test_name] = test_result
                
        except Exception as e:
            debug_info["tests"][test_name] = {
                "error": str(e),
                "error_type": type(e).__name__,
                "success": False
            }
    
    # 클라이언트를 통한 요청도 테스트
    try:
        items, total = await client.search_laws(q, page=1, size=5)
        debug_info["client_request"] = {
            "success": True,
            "total_results": total,
            "items_count": len(items),
            "sample_items": items[:2] if items else [],
        }
    except Exception as client_error:
        debug_info["client_request"] = {
            "success": False,
            "error": str(client_error),
            "error_type": type(client_error).__name__,
        }
    
    return debug_info

@app.get("/laws/search", response_model=SearchResponse, summary="법령 검색")
async def search_laws(
    q: str = Query(..., description="검색어"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: int = Query(1, ge=1, le=2, description="1: 법령명, 2: 본문"),
    client: LawClient = Depends(get_law_client),
) -> SearchResponse:
    """
    법령 목록을 검색합니다.
    """
    items, total = await client.search_laws(q, page=page, size=size, search=search)

    # 외부 응답 키 차이 흡수: 우선 영문 키, 없으면 한글 키 폴백
    mapped = []
    for it in items:
        law_id = it.get("LAW_ID") or it.get("법령ID")
        title = it.get("LAW_NM") or it.get("법령명한글")
        eff = it.get("EF_YD") or it.get("시행일자")
        promulgation = it.get("PO_DT") or it.get("공포일자")  # 공포일자 추가
        
        mapped.append(
            LawSearchItem(
                law_id=law_id or "",
                title=title or "",
                effective_date=eff or "",
                promulgation_date=promulgation,
            )
        )

    return SearchResponse(items=mapped, page=page, size=size, total=total)

@app.get(
    "/laws/{law_id}",
    response_model=LawDetail,
    summary="법령 상세 조회",
    responses={
        404: {"model": ErrorResponse, "description": "법령을 찾을 수 없음"},
        503: {"model": ErrorResponse, "description": "상위 서비스(law.go.kr) 오류"},
    },
)
async def get_law_detail(
    law_id: str,
    client: LawClient = Depends(get_law_client),
) -> LawDetail:
    """
    주어진 법령 ID로 상세 정보를 조회합니다.
    """
    detail_data = await client.get_law_detail(law_id)
    return LawDetail(**detail_data)

@app.get(
    "/attachments/search", 
    response_model=AttachmentSearchResponse, 
    summary="별표/서식 검색"
)
async def search_attachments(
    q: str = Query(..., description="검색어"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    client: LawClient = Depends(get_law_client),
) -> AttachmentSearchResponse:
    """
    별표/서식을 검색합니다.
    """
    items, total = await client.search_attachments(q, page=page, size=size)
    
    mapped = []
    for it in items:
        # 실제 API 응답 구조에 맞게 키 매핑
        law_id = it.get("법령ID") or it.get("LAW_ID") or ""
        law_title = it.get("법령명") or it.get("LAW_NM") or ""
        attachment_name = it.get("별표서식명") or it.get("ATTACHMENT_NAME") or ""
        attachment_type = it.get("종류") or it.get("TYPE") or ""
        attachment_no = it.get("번호") or it.get("NO")
        ministry = it.get("소관부처") or it.get("MINISTRY")
        promulgation_date = it.get("공포일자") or it.get("PO_DT")
        html_link = it.get("HTML링크") or it.get("HTML_LINK")
        file_link = it.get("파일링크") or it.get("FILE_LINK")
        pdf_link = it.get("PDF링크") or it.get("PDF_LINK")
        
        mapped.append(
            AttachmentItem(
                law_id=law_id,
                law_title=law_title,
                attachment_name=attachment_name,
                attachment_type=attachment_type,
                attachment_no=attachment_no,
                ministry=ministry,
                promulgation_date=promulgation_date,
                html_link=html_link,
                file_link=file_link,
                pdf_link=pdf_link,
            )
        )
    
    return AttachmentSearchResponse(items=mapped, page=page, size=size, total=total)

# --- 앱 실행 (로컬 개발용) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)