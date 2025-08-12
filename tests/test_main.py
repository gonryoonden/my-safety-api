# tests/test_main.py

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from main import app

@pytest.fixture
def client(monkeypatch):
    """테스트를 위한 TestClient를 생성하고, 환경 변수를 모킹합니다."""
    monkeypatch.setenv("LAW_OC", "TEST_API_KEY")
    return TestClient(app)

# --- 테스트 헬퍼 함수 ---
def law_search_response_factory(items, total=None):
    """law.go.kr 검색 API의 응답 JSON을 생성하는 헬퍼"""
    if total is None:
        total = len(items)
    return {"LawSearch": {"law": items, "totalCnt": total}}

def law_detail_response_factory(law_id, name, eff_date, mst="12345"):
    """law.go.kr 상세 API의 응답 JSON을 생성하는 헬퍼"""
    return {"law": {"법령ID": law_id, "법령명한글": name, "시행일자": eff_date, "MST": mst}}

def attachment_search_response_factory(items, total=None):
    """별표/서식 검색 API의 응답 JSON을 생성하는 헬퍼"""
    if total is None:
        total = len(items)
    return {"licBylSearch": {"licbyl": items, "totalCnt": total}}

# --- 테스트 케이스 ---
@respx.mock
def test_get_law_detail_success(client: TestClient):
    """법령 상세 조회 성공 케이스 테스트"""
    law_id = "007363"
    # URL 스키마 통일 (HTTP)
    respx.get(url__regex=r"http://www.law.go.kr/DRF/lawService.do.*").mock(
        return_value=httpx.Response(200, json=law_detail_response_factory(
            law_id, "산업안전보건법", "20250101", "mst123"
        ))
    )
    response = client.get(f"/laws/{law_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["law_id"] == law_id
    assert data["title"] == "산업안전보건법"
    assert "mst123" in data["source_url"]

@respx.mock
def test_get_law_detail_not_found(client: TestClient):
    """법령 상세 조회 404 실패 케이스 테스트"""
    law_id = "999999"
    respx.get(url__regex=r"http://www.law.go.kr/DRF/lawService.do.*").mock(
        return_value=httpx.Response(404)
    )
    response = client.get(f"/laws/{law_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "LAW_NOT_FOUND"

@respx.mock
def test_search_laws_upstream_error(client: TestClient):
    """법령 검색 시 외부 API 500 오류 케이스 테스트"""
    respx.get(url__regex=r"http://www.law.go.kr/DRF/lawSearch.do.*").mock(
        return_value=httpx.Response(500)
    )
    response = client.get("/laws/search?q=test")
    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_ERROR"

@respx.mock
def test_search_laws_success(client: TestClient):
    """법령 검색 성공 케이스 테스트"""
    search_query = "산업안전"
    respx.get(url__regex=r"http://www.law.go.kr/DRF/lawSearch.do.*").mock(
        return_value=httpx.Response(200, json=law_search_response_factory(
            items=[
                {"법령ID": "123", "법령명한글": "산업안전보건법", "시행일자": "20250101"},
                {"법령ID": "456", "법령명한글": "산업안전보건법 시행령", "시행일자": "20250301"},
            ],
            total=2
        ))
    )
    response = client.get(f"/laws/search?q={search_query}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["law_id"] == "123"
    assert data["items"][0]["effective_date"] == "20250101"

@respx.mock
def test_search_laws_invalid_search_param(client: TestClient):
    """법령 검색 시 잘못된 search 매개변수 테스트"""
    response = client.get("/laws/search?q=test&search=3")  # 3은 유효하지 않은 값
    assert response.status_code == 422  # Validation Error

@respx.mock
def test_search_attachments_success(client: TestClient):
    """별표/서식 검색 성공 케이스 테스트"""
    search_query = "별표"
    respx.get(url__regex=r"http://www.law.go.kr/DRF/lawSearch.do.*target=licbyl.*").mock(
        return_value=httpx.Response(200, json=attachment_search_response_factory(
            items=[
                {
                    "법령ID": "123",
                    "법령명": "산업안전보건법",
                    "별표서식명": "별표 1",
                    "종류": "별표",
                    "번호": "1",
                },
            ],
            total=1
        ))
    )
    response = client.get(f"/attachments/search?q={search_query}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["law_id"] == "123"
    assert data["items"][0]["attachment_name"] == "별표 1"

@respx.mock 
def test_search_laws_retry_with_search_param(client: TestClient):
    """법령 검색 시 첫 번째 요청 실패 후 search 파라미터로 재시도 테스트"""
    search_query = "안전"
    
    # 첫 번째 요청(search 파라미터 없음)은 HTML 응답으로 실패
    respx.get(
        url__regex=r"http://www.law.go.kr/DRF/lawSearch.do\?OC=.*&target=law&type=JSON&query=.*&display=10&page=1$"
    ).mock(
        return_value=httpx.Response(
            200, 
            content="<html>페이지 접속 실패</html>",
            headers={"content-type": "text/html"}
        )
    )
    
    # 두 번째 요청(search 파라미터 포함)은 성공
    respx.get(
        url__regex=r"http://www.law.go.kr/DRF/lawSearch.do.*&search=1$"
    ).mock(
        return_value=httpx.Response(200, json=law_search_response_factory(
            items=[{"법령ID": "789", "법령명한글": "안전관리법", "시행일자": "20250201"}],
            total=1
        ))
    )
    
    response = client.get(f"/laws/search?q={search_query}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["law_id"] == "789"