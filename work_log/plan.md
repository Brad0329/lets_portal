# 입찰공고 포탈서비스 개발 계획

## 1. 프로젝트 개요

엑셀에 정리된 58개 입찰공고 사이트의 진행중인 입찰을 한 곳에서 검색하고, 원본 사이트로 바로 이동할 수 있는 웹 포탈 서비스

## 2. 데이터 소스 구조

### API 수집 (자동 수집 - 3개 API)

| API | 키 | 커버 범위 | 비고 |
|-----|-----|----------|------|
| 나라장터 입찰공고정보서비스 | data.go.kr 키 | 나라장터 1~5 (엑셀 49~53번) + 조달 관련 공공기관 | 키워드 검색 지원 (Sheet2의 85개 키워드 활용) |
| K-Startup 조회서비스 | data.go.kr 키 | 창업진흥원, K-Startup (엑셀 1번, 34번) | 사업공고/모집공고 |
| 기업마당(Bizinfo) API | bizinfo.go.kr 키 (별도 신청 필요) | 중기부, 소상공인진흥공단 등 다수 기관 통합 | 가장 넓은 커버리지 |

### 링크 기반 (수동 연결 - 나머지 기관)

- 엑셀의 나머지 ~50개 기관은 URL 링크 제공
- 기관별 카테고리/URL을 DB에 저장하여 바로가기 제공

## 3. 기술 스택

```
프론트엔드:  HTML + CSS + JavaScript (순수 또는 React)
백엔드:      Node.js (Express) 또는 Python (FastAPI)
DB:          SQLite (초기) → PostgreSQL (확장 시)
스케줄러:    node-cron 또는 APScheduler (API 정기 수집)
배포:        로컬 개발 → Vercel / Railway 등
```

### 권장: Python (FastAPI) + SQLite + Vanilla JS

- API 호출/파싱이 핵심이므로 Python requests가 편리
- FastAPI는 자동 API 문서 제공
- SQLite는 초기 개발에 설정 불필요
- 프론트엔드는 가볍게 시작

## 4. 개발 단계

### Phase 1: 기본 골격 (MVP)

#### 1-1. 프로젝트 구조 생성
```
lets_portal/
├── backend/
│   ├── main.py              # FastAPI 앱
│   ├── config.py            # API 키, 설정
│   ├── database.py          # SQLite 연결, 테이블 생성
│   ├── models.py            # 데이터 모델
│   ├── collectors/
│   │   ├── nara_collector.py    # 나라장터 API 수집
│   │   ├── kstartup_collector.py # K-Startup API 수집
│   │   └── bizinfo_collector.py  # 기업마당 API 수집 (추후)
│   ├── scheduler.py         # 정기 수집 스케줄러
│   └── requirements.txt
├── frontend/
│   ├── index.html           # 메인 페이지
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js           # 검색, 필터, 페이징
├── data/
│   └── portal.db            # SQLite DB
├── plan.md
└── .env                     # API 키 (git 제외)
```

#### 1-2. DB 테이블 설계

```sql
-- 입찰공고 (API로 수집된 데이터)
CREATE TABLE bid_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'nara', 'kstartup', 'bizinfo'
    title TEXT NOT NULL,            -- 공고명
    organization TEXT,              -- 발주기관
    category TEXT,                  -- 업무구분 (물품/용역/공사 등)
    bid_no TEXT,                    -- 공고번호
    start_date TEXT,                -- 공고일
    end_date TEXT,                  -- 마감일
    status TEXT,                    -- 진행상태 ('진행중', '마감')
    url TEXT,                       -- 원본 상세 URL
    keywords TEXT,                  -- 매칭된 키워드 (콤마 구분)
    collected_at TEXT,              -- 수집 시각
    UNIQUE(source, bid_no)
);

-- 기관 바로가기 (엑셀 데이터)
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,             -- 기관명
    category TEXT,                  -- 구분 (공공기관/나라장터)
    page_category TEXT,             -- 해당 카테고리 (알림마당-입찰공고 등)
    url TEXT NOT NULL,              -- 입찰공고 페이지 URL
    is_active INTEGER DEFAULT 1    -- 활성화 여부
);

-- 검색 키워드 (초기값: 엑셀 Sheet2의 85개, 이후 설정 페이지에서 추가/삭제)
CREATE TABLE keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    keyword_group TEXT,             -- 나라장터 1~5 그룹
    is_active INTEGER DEFAULT 1    -- 활성화 여부 (설정에서 ON/OFF)
);

-- ★ 초기화면 설정 (설정 페이지에서 관리)
CREATE TABLE display_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT
);

-- display_settings 초기값:
-- | setting_key       | setting_value | 설명                              |
-- |-------------------|---------------|-----------------------------------|
-- | status_filter     | 'ongoing'     | 'ongoing'=진행중만, 'all'=전체     |
-- | date_range_days   | '30'          | 최근 N일 이내 공고만 표시           |
-- | sort_order        | 'deadline'    | 'deadline'=마감임박순, 'latest'=최신순 |
-- | items_per_page    | '20'          | 페이지당 표시 건수                  |
```

#### 1-2a. 초기화면 데이터 흐름

```
[설정 페이지]                    [메인 페이지]
    │                                │
    ├─ 키워드 등록/삭제 ──→ keywords 테이블
    ├─ 기간 설정 (N일) ──→ display_settings     ──→  SELECT * FROM bid_notices
    ├─ 상태 (진행중/전체) ──→ display_settings         WHERE status = {status_filter}
    ├─ 정렬 순서 ──→ display_settings                  AND start_date >= date('now', '-{date_range_days} days')
    │                                                   AND keywords MATCH (active keywords)
    │                                                   ORDER BY {sort_order}
    │                                                   LIMIT {items_per_page}
    │                                │
    └── [저장] ──→ DB 반영 ──→ 메인 페이지 자동 반영
```

**MVP 기본값:** 키워드=Sheet2의 85개 전체 활성, 기간=30일, 상태=진행중만, 정렬=마감임박순

#### 1-3. API 수집기 개발

**나라장터 API** (최우선)
- 엔드포인트: `apis.data.go.kr/1230000/ad/BidPublicInfoService`
- Sheet2의 85개 키워드로 검색
- 진행중 입찰만 필터링
- 5개 그룹(나라장터 1~5) 키워드별 수집

**K-Startup API**
- 엔드포인트: `apis.data.go.kr/B552735/kisedKstartupService01`
- 모집중인 사업공고만 필터링

**기업마당 API** (별도 키 확보 후)
- 엔드포인트: `bizinfo.go.kr` API
- 지원사업 공고 수집

### Phase 2: 프론트엔드 (검색 포탈 UI)

#### 2-1. 메인 페이지 구성
```
┌──────────────────────────────────────────────────┐
│         입찰공고 포탈서비스              [⚙ 설정]    │
│                                                      │
│  🔍 [________________검색어________________] [검색]   │
│                                                      │
│  필터: [전체▼] [나라장터▼] [K-Startup▼] [기관▼]      │
│        [진행중만 ☑]  [마감임박순 ▼]                   │
├──────────────────────────────────────────────────┤
│  📋 검색결과 (총 342건)  ※ 설정 기준으로 자동 필터링  │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │ [나라장터] 2026년 스타트업 육성 용역 입찰       │    │
│  │ 발주기관: 중소벤처기업부 | 마감: 2026-04-05    │    │
│  │ 키워드: 스타트업, 육성                         │    │
│  │                            [원문보기 →]        │    │
│  └─────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────┐    │
│  │ [K-Startup] 2026년 창업도약패키지 모집공고     │    │
│  │ 기관: 창업진흥원 | 마감: 2026-04-10            │    │
│  │                            [원문보기 →]        │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  [1] [2] [3] ... [다음→]                             │
├──────────────────────────────────────────────────┤
│  📁 기관별 바로가기 (58개 기관)                       │
│                                                      │
│  [K-Startup] [강원정보문화산업진흥원] [경기대진TP]    │
│  [경기도경제과학진흥원] [경남문화예술진흥원] ...       │
│                                                      │
└──────────────────────────────────────────────────┘
```

#### 2-2. 주요 기능
- **통합 검색**: 제목, 기관명, 키워드로 전체 검색
- **소스 필터**: 나라장터 / K-Startup / 기업마당 선택
- **상태 필터**: 진행중 / 마감임박 / 전체 (기본값은 설정에 따름)
- **정렬**: 마감임박순 / 최신순 / 기관순 (기본값은 설정에 따름)
- **원문 링크**: 클릭 시 해당 입찰공고 사이트로 새 탭 이동
- **기관 바로가기**: 58개 기관 입찰공고 페이지 직접 링크
- **초기화면 로딩**: display_settings + active keywords 기준으로 자동 필터링

### Phase 3: 설정 페이지

#### 3-1. 설정 페이지 구성 (/settings)
```
┌──────────────────────────────────────────────────┐
│         ⚙ 초기화면 설정                [← 메인]     │
├──────────────────────────────────────────────────┤
│                                                      │
│  ■ 공고 상태 필터                                     │
│    (●) 진행중만 표시   ( ) 전체 (진행중+마감)          │
│                                                      │
│  ■ 조회 기간                                          │
│    최근 [30 ▼] 일 이내 공고 표시                      │
│    (선택: 7일 / 14일 / 30일 / 60일 / 90일 / 전체)    │
│                                                      │
│  ■ 정렬 순서                                          │
│    (●) 마감임박순   ( ) 최신등록순   ( ) 기관순        │
│                                                      │
│  ■ 페이지당 표시 건수                                  │
│    [20 ▼] 건  (선택: 10 / 20 / 50 / 100)             │
│                                                      │
├──────────────────────────────────────────────────┤
│                                                      │
│  ■ 검색 키워드 관리                                    │
│                                                      │
│  [+ 키워드 추가]  [일괄 ON] [일괄 OFF]                │
│                                                      │
│  그룹: 나라장터1                                       │
│  ☑ CEO  ☑ 귀촌  ☑ 농촌  ☑ 어촌  ☑ 어항              │
│  ☑ 코디네이터  ☑ 로컬크리에이터  ☑ 상권활성화 ...    │
│                                                      │
│  그룹: 나라장터2                                       │
│  ☑ IR  ☑ MICE  ☑ 벤처  ☑ 강좌  ☑ 국방 ...           │
│                                                      │
│  그룹: (추가 키워드)                                   │
│  ☑ [사용자가 직접 추가한 키워드들]                     │
│                                                      │
│            [저장]  [초기화 (기본값 복원)]               │
│                                                      │
└──────────────────────────────────────────────────┘
```

#### 3-2. 설정 저장 흐름
1. 사용자가 설정 변경 → [저장] 클릭
2. PUT /api/settings → display_settings 테이블 업데이트
3. PUT /api/keywords → keywords 테이블의 is_active 업데이트
4. 메인 페이지 복귀 시 변경된 설정 기준으로 리스트 재조회

### Phase 4: 자동화 및 고도화

#### 4-1. 정기 수집 스케줄러
- 매일 오전 9시, 오후 2시 자동 수집
- **활성화된 키워드(is_active=1)만** 수집 대상
- 신규 공고 감지 시 카운트 표시
- 수집 로그 관리

#### 4-2. 추가 기능 (선택)
- 마감임박 하이라이트 (D-3 이내 빨간색)
- 키워드 알림 기능 (관심 키워드 등록 → 신규 공고 알림)
- 엑셀 다운로드 (검색 결과)
- 기관별 공고 수 통계 대시보드

## 5. 개발 순서 (작업 체크리스트)

- [ ] **Step 1**: 프로젝트 구조 생성 + .env 설정 (API 키)
- [ ] **Step 2**: DB 스키마 생성 (display_settings 포함) + 엑셀 데이터 임포트 + 설정 초기값 삽입
- [ ] **Step 3**: 나라장터 API 수집기 개발 + 테스트
- [ ] **Step 4**: K-Startup API 수집기 개발 + 테스트
- [ ] **Step 5**: FastAPI 백엔드 (검색/필터 + 설정 CRUD API 엔드포인트)
- [ ] **Step 6**: 프론트엔드 메인 페이지 (설정 기반 초기 리스트 + 검색 + 기관 바로가기)
- [ ] **Step 7**: 프론트엔드 설정 페이지 (키워드 관리 + 조회조건 설정)
- [ ] **Step 8**: 정기 수집 스케줄러 연동
- [ ] **Step 9**: 통합 테스트 + 배포

## 6. 필요 사항

### 즉시 필요
- [x] data.go.kr API 키 (발급 완료)
- [x] 나라장터 API 활용신청 (승인 완료)
- [x] K-Startup API 활용신청 (승인 완료)
- [x] .env 파일에 API 키 입력 (DATA_GO_KR_KEY)

### 추후 필요
- [ ] 기업마당(Bizinfo) API 키 별도 신청
- [ ] 배포 환경 선택 (Vercel, Railway, 자체 서버 등)

## 7. 예상 결과

MVP 완성 시:
- 나라장터 + K-Startup에서 자동 수집된 **진행중 입찰공고**를 한 화면에서 검색
- 검색 결과에서 클릭하면 **원본 공고 사이트로 바로 이동**
- 58개 기관 **바로가기 링크** 제공
- 매일 2회 자동 업데이트
