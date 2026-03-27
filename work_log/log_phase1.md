# Phase 1 작업 로그

## 기간
2026-03-27

## 목표
백엔드 API 수집기 개발 + FastAPI 서버 + 프론트엔드 기본 화면

---

## 완료 항목

### Step 1-2: 프로젝트 구조 + DB (이전 세션에서 완료)
- 프로젝트 디렉토리 구조 생성
- config.py: API 키 로드, 엔드포인트 URL 설정
- database.py: SQLite DB 초기화, 엑셀 임포트 기능
- DB 테이블 4개: bid_notices, organizations, keywords, display_settings
- 엑셀 데이터 임포트: 기관 58건, 키워드 85건, 설정 4건

### Step 3: K-Startup API 수집기 (`collectors/kstartup.py`)
- 엔드포인트: `https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01`
- 응답형식: JSON
- 진행중 공고 필터 (`rcrt_prgs_yn=Y`)
- 키워드 매칭 (제목 + 내용 + 대상)
- 날짜 필터 (최근 N일)
- **결과: 전체 27,953건 중 키워드 매칭 282건 수집**

### Step 4: 중소벤처기업부 사업공고 수집기 (`collectors/mss_biz.py`)
- 엔드포인트: `http://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2`
- 응답형식: XML
- 기간 필터 (startDate, endDate)
- 키워드 매칭 (제목 + 내용)
- 상태 판단: 마감일 기준 ongoing/closed
- **결과: 73건 중 키워드 매칭 64건 수집**

### Step 5: 나라장터 API 수집기 (`collectors/nara.py`)
- 엔드포인트: `https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServc`
- 용역/물품/공사 3개 엔드포인트 지원
- 코드 작성 완료
- **⚠️ API 서버 500 에러 발생 — 서버 복구 후 테스트 필요**

### Step 6: FastAPI 백엔드 (`backend/main.py`)
- `GET /api/notices` — 공고 목록 (검색 + 필터 + 정렬 + 페이지네이션)
- `GET /api/notices/stats` — 소스별 통계
- `GET /api/settings` — 표시 설정 조회
- `PUT /api/settings/{key}` — 설정 변경
- `GET /api/keywords` — 키워드 목록
- `PUT /api/keywords/{id}/toggle` — 키워드 활성/비활성
- `GET /api/organizations` — 기관 목록
- `POST /api/collect` — 수동 수집 실행

### Step 7: 프론트엔드 (`frontend/`)
- index.html + css/style.css + js/app.js
- 통계 바 (전체/진행중/마지막수집)
- 검색 입력 + 출처/상태/정렬 필터
- 공고 테이블 (출처뱃지, 링크, 상태뱃지, 키워드태그)
- 페이지네이션
- 수집 실행 버튼

---

## 발견사항 / 이슈

### API 키 관련
- data.go.kr 인증키 1개로 모든 활용신청 API 공용 사용
- .env에 Decoding 키 저장, requests params로 전달 (자동 인코딩)

### 승인된 API 5개 (data.go.kr)
1. 창업진흥원_정부지원사업_주관기관_정보
2. 중소벤처기업부_사업공고 ✅ 작동
3. 한국지역정보개발원_입찰정보 조회 서비스 (404 에러 — 엔드포인트 확인 필요)
4. 창업진흥원_K-Startup ✅ 작동
5. 조달청_나라장터 입찰공고정보서비스 (500 에러 — 서버 장애)

### 나라장터 API 서버 장애
- 모든 엔드포인트(용역/물품/공사), 모든 파라미터 조합에서 500 에러
- 잘못된 키로 테스트해도 동일 500 → 서버 자체 문제
- 코드는 작성 완료, 서버 복구 시 자동 작동 예상

---

## DB 현황 (Phase 1 종료 시점)
| 테이블 | 건수 |
|--------|------|
| organizations | 58건 |
| keywords | 85건 |
| display_settings | 4건 |
| bid_notices | 346건 (K-Startup 282 + 중기부 64) |

---

## 파일 구조
```
lets_portal/
├── .env                     # API 키
├── .gitignore
├── ●입찰 공고(...).xlsx     # 기관/키워드 원본
├── backend/
│   ├── config.py            # 환경변수 + API URL
│   ├── database.py          # DB 초기화 + 엑셀 임포트
│   ├── models.py            # 데이터 모델
│   ├── main.py              # FastAPI 서버
│   ├── requirements.txt
│   └── collectors/
│       ├── __init__.py
│       ├── kstartup.py      # K-Startup 수집기
│       ├── mss_biz.py       # 중소벤처기업부 수집기
│       ├── nara.py          # 나라장터 수집기
│       └── collect_all.py   # 전체 수집 오케스트레이터
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── data/
│   └── portal.db            # SQLite DB
└── work_log/
    ├── plan.md
    ├── log_phase0.md
    └── log_phase1.md
```
