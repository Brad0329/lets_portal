import os
from dotenv import load_dotenv

load_dotenv()

DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY")

# 나라장터 입찰공고정보서비스
NARA_API_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# K-Startup 조회서비스
KSTARTUP_API_BASE = "http://apis.data.go.kr/B552735/kisedKstartupService01"

# DB 경로
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portal.db")
