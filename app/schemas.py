# app/schemas.py

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, AnyHttpUrl

class LawSearchItem(BaseModel):
    """검색 결과에 포함되는 개별 법령 항목"""
    law_id: str = Field(..., description="법령 고유 ID")
    title: str = Field(..., description="법령명")
    effective_date: str = Field(..., description="시행일자")
    promulgation_date: Optional[str] = None  # 신규 필드

class SearchResponse(BaseModel):
    """법령 검색 API의 응답 모델"""
    items: List[LawSearchItem]
    page: int = Field(..., ge=1, description="현재 페이지 번호")
    size: int = Field(..., ge=1, description="페이지 당 항목 수")
    total: int = Field(..., ge=0, description="전체 항목 수")

class LawDetail(BaseModel):
    """개별 법령의 상세 정보 모델"""
    law_id: str = Field(..., description="법령 고유 ID")
    title: str = Field(..., description="법령명")
    effective_date: str = Field(..., description="시행일자")
    source_url: AnyHttpUrl = Field(..., description="법령 원문 URL")

class ErrorResponse(BaseModel):
    """API 오류 응답 모델"""
    code: str = Field(..., description="기계가 읽을 수 있는 오류 코드")
    message: str = Field(..., description="사람이 읽을 수 있는 오류 메시지")
    detail: Optional[str] = Field(None, description="오류에 대한 추가 상세 정보")