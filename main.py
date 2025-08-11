# main.py

from __future__ import annotations
import asyncio
from fastapi import FastAPI, Query, Request, Depends
from fastapi.responses import JSONResponse

# 우리가 분리한 모듈들을 임포트합니다.
from app.clients.law_client import LawClient, LawNotFoundError, UpstreamServiceError
from app.schemas import ErrorResponse, LawDetail, LawSearchItem, SearchResponse

# --- FastAPI 앱 설정 ---
app = FastAPI(
    title="산업안전 법령 조회 API",
    version="1.0.0",
    description="대한민국 법령정보센터 Open API를 활용하여 산업안전 관련 법령을 조회하는 API입니다."
)

# --- 의존성 주입 (Dependency Injection) ---
# 앱 전체에서 공유할 LawClient 인스턴스를 생성합니다.
# 이렇게 하면 API 요청마다 클라이언트를 새로 만들지 않아 효율적입니다.
async def get_law_client() -> LawClient:
    client = LawClient()
    try:
        yield client
    finally:
        await client.close()

# --- 예외 처리 핸들러 (Exception Handlers) ---
# 프로젝트 전역에서 발생하는 특정 오류를 잡아 표준화된 JSON 형식으로 반환합니다.

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

# --- API 라우트 (Endpoints) ---

@app.get(
    "/laws/search",
    response_model=SearchResponse,
    summary="법령 검색",
    responses={
        503: {"model": ErrorResponse, "description": "상위 서비스(law.go.kr) 오류"},
    },
)
async def search_laws(
    q: str = Query(..., description="검색할 법령명 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    size: int = Query(10, ge=1, le=100, description="페이지 당 결과 수"),
    client: LawClient = Depends(get_law_client),
) -> SearchResponse:
    """
    주어진 키워드(q)로 법령을 검색하고, 페이지네이션된 결과를 반환합니다.
    """
    items, total = await client.search_laws(q, page=page, size=size)

    # 검색된 각 법령의 상세 정보를 비동기적으로 가져와 시행일자를 보강합니다.
    async def fetch_effective_date(law_id: str):
        try:
            detail = await client.get_law_detail(law_id)
            return detail.get("effective_date")
        except (LawNotFoundError, UpstreamServiceError):
            return None

    tasks = [fetch_effective_date(str(item.get("LAW_ID"))) for item in items]
    effective_dates = await asyncio.gather(*tasks)

    search_items = [
        LawSearchItem(
            law_id=str(item.get("LAW_ID")),
            title=str(item.get("LAW_NM")),
            effective_date=eff_date,
        )
        for item, eff_date in zip(items, effective_dates)
    ]

    return SearchResponse(items=search_items, page=page, size=size, total=total)


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
    