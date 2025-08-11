# tests/test_main.py

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

# 테스트 대상인 main.py의 app 객체를 임포트합니다.
from main import app

@pytest.fixture
def client(monkeypatch):
    """테스트를 위한 TestClient를 생성하고, 환경 변수를 모킹합니다."""
    monkeypatch.setenv("LAW_OC", "TEST_API_KEY") # 테스트용 가짜 키
    return TestClient(app)

# --- 테스트 헬퍼 함수 ---
def law_search_response_factory(items, total=None):
    """law.go.kr 검색 API의 응답 JSON을 생성하는 헬퍼"""
    if total is None:
        total = len(items)
    return {"law": items, "totalCount": total}

def law_detail_response_factory(law_id, name, eff_date, mst="12345"):
    """law.go.kr 상세 API의 응답 JSON을 생성하는 헬퍼"""
    return {"law": {"LAW_ID": law_id, "LAW_NM": name, "EFYD": eff_date, "MST": mst}}


# --- 테스트 케이스 ---
@respx.mock
def test_get_law_detail_success(client: TestClient):
    """법령 상세 조회 성공 케이스 테스트"""
    # 외부 API 호출을 가로채서 미리 정의된 응답을 반환하도록 설정
    law_id = "007363"
    respx.get(f"https://www.law.go.kr/DRF/lawService.do?OC=TEST_API_KEY&target=law&type=JSON&ID={law_id}").mock(
        return_value=httpx.Response(200, json=law_detail_response_factory(
            law_id, "산업안전보건법", "2025-01-01", "mst123"
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

    assert response.status_code == 503 # 우리는 503으로 응답하기로 정의했음
    assert response.json()["code"] == "UPSTREAM_ERROR"
    