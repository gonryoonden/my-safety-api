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
    if total is None:
        total = len(items)
    return {"law": items, "totalCnt": total}

def law_detail_response_factory(law_id, name, eff_date, mst="12345"):
    return {"law": {"법령ID": law_id, "법령명한글": name, "시행일자": eff_date, "MST": mst}}

# --- 테스트 케이스 ---
@respx.mock
def test_get_law_detail_success(client: TestClient):
    """법령 상세 조회 성공 케이스 테스트"""
    law_id = "007363"
    respx.get(f"https://www.law.go.kr/DRF/lawService.do?OC=TEST_API_KEY&target=law&type=JSON&ID={law_id}").mock(
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
    respx.get(f"https://www.law.go.kr/DRF/lawService.do?OC=TEST_API_KEY&target=law&type=JSON&ID={law_id}").mock(
        return_value=httpx.Response(404)
    )
    response = client.get(f"/laws/{law_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "LAW_NOT_FOUND"

@respx.mock
def test_search_laws_upstream_error(client: TestClient):
    """법령 검색 시 외부 API 500 오류 케이스 테스트"""
    respx.get("https://www.law.go.kr/DRF/lawSearch.do").mock(
        return_value=httpx.Response(500)
    )
    response = client.get("/laws/search?q=test")
    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_ERROR"

@respx.mock
def test_search_laws_success(client: TestClient):
    """법령 검색 성공 케이스 테스트"""
    search_query = "산업안전"
    respx.get(f"https://www.law.go.kr/DRF/lawSearch.do?OC=TEST_API_KEY&target=law&type=JSON&query={search_query}&display=10&page=1").mock(
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