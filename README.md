# 산업안전 법령 조회 API (FastAPI)

대한민국 법령정보센터 Open API를 활용하여 산업안전 관련 법령을 검색하고 상세 정보를 조회하는 FastAPI 기반의 API입니다.

## 주요 기능

-   **법령 검색**: 키워드를 기반으로 법령을 검색하고, 페이지네이션된 결과를 반환합니다.
-   **법령 상세 조회**: 특정 법령 ID를 사용하여 상세 정보(시행일자, 원문 URL 등)를 제공합니다.
-   **안정적인 외부 호출**: `httpx`와 `tenacity`를 사용하여 외부 API 호출 시 타임아웃 및 재시도 로직을 적용했습니다.

## 요구 사항

-   Python 3.11 이상
-   `LAW_OC` 환경 변수 (법령정보센터 인증키)

## 설치 및 실행 방법

### 1. 저장소 복제 및 가상환경 설정

```bash
git clone [https://github.com/gonryoonden/my-safety-api.git](https://github.com/gonryoonden/my-safety-api.git)
cd my-safety-api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
