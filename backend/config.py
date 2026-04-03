import os
import sys
from dotenv import load_dotenv

# ─── exe/개발 환경 자동 감지 ─────────────────────────
if getattr(sys, 'frozen', False):
    # PyInstaller exe로 실행 중 → exe 파일이 있는 폴더 기준
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 개발 환경 → backend/ 의 상위 폴더 (lets_portal/)
    BASE_DIR = os.path.join(os.path.dirname(__file__), "..")

# .env 로드 (BASE_DIR 기준)
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY")

# 나라장터 입찰공고정보서비스
NARA_API_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# K-Startup 조회서비스
KSTARTUP_API_BASE = "http://apis.data.go.kr/B552735/kisedKstartupService01"

# 경로들
DB_PATH = os.path.join(BASE_DIR, "data", "portal.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
COLLECTORS_DIR = os.path.join(BASE_DIR, "backend", "collectors") if not getattr(sys, 'frozen', False) else os.path.join(BASE_DIR, "collectors")

# ─── 인증/세션 기본값 ──────────────────────────────
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin1234")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD", "1234")
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "24"))
PORT = int(os.getenv("PORT", "8000"))
