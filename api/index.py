# Vercel(Serverless) -> FastAPI(ASGI) 브리지
# Vercel은 /api/*.py 를 서버리스 엔트리로 인식합니다.
from main import app as app  # FastAPI 인스턴스를 그대로 노출
