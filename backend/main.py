"""
LETS 프로젝트 관리 시스템 - FastAPI 백엔드
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging
import os

from database import init_db
from routers import auth, users, notices, tags, settings, keywords, sources, collection, organizations, ai, extractor
from routers.extractor import cleanup_orphan_assets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 초기화 + orphan asset 정리"""
    init_db()
    logger.info("DB 초기화 완료")
    removed = cleanup_orphan_assets()
    if removed:
        logger.info("orphan asset 디렉토리 %d건 정리", removed)
    yield


app = FastAPI(
    title="LETS 프로젝트 관리 시스템",
    description="입찰공고 통합 검색 및 프로젝트 관리",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS (프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ─── 라우터 등록 ─────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(notices.router)
app.include_router(tags.router)
app.include_router(settings.router)
app.include_router(keywords.router)
app.include_router(sources.router)
app.include_router(collection.router)
app.include_router(organizations.router)
app.include_router(ai.router)
app.include_router(extractor.router)


# ─── 프론트엔드 정적파일 ──────────────────────────
from config import FRONTEND_DIR
frontend_dir = FRONTEND_DIR
if os.path.isdir(frontend_dir):
    # 명시적 HTML 페이지 라우트
    @app.get("/login.html")
    def login_page():
        return FileResponse(os.path.join(frontend_dir, "login.html"))

    @app.get("/settings.html")
    def settings_page():
        return FileResponse(os.path.join(frontend_dir, "settings.html"))

    @app.get("/dashboard.html")
    def dashboard_page():
        return FileResponse(os.path.join(frontend_dir, "dashboard.html"))

    @app.get("/review-list.html")
    def review_list_page():
        return FileResponse(os.path.join(frontend_dir, "review-list.html"))

    @app.get("/bid-list.html")
    def bid_list_page():
        return FileResponse(os.path.join(frontend_dir, "bid-list.html"))

    @app.get("/excluded-list.html")
    def excluded_list_page():
        return FileResponse(os.path.join(frontend_dir, "excluded-list.html"))

    @app.get("/source-list.html")
    def source_list_page():
        return FileResponse(os.path.join(frontend_dir, "source-list.html"))

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"\n  LETS 서버 시작: http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
