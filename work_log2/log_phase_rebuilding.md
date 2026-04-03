# Phase Rebuilding: 코드 구조 리빌딩 — 작업 로그

## 작업일: 2026-04-03

## 목표
Phase B-2(프로젝트 관리) 진입 전에 누적된 코드 중복과 모놀리식 구조를 정리.
기능 변경 없이 순수 구조 리팩토링.

## 리빌딩 전 현황

| 항목 | 문제 |
|------|------|
| `main.py` | 1,210줄 모놀리식 — 45개 엔드포인트 전부 한 파일 |
| 수집기 4개 | save_to_db() 60-80% 중복, 날짜/키워드/상태 함수 각각 별도 구현 |
| 프론트엔드 JS | `escapeHtml()` 4곳 중복, 페이지네이션 4곳 중복 |
| 설정값 | 기본 비밀번호, 세션 시간 등 코드에 하드코딩 |

## 구현 내역

### Step 1: Backend Router 분리

**main.py 1,210줄 → 95줄**

| 파일 | prefix | 엔드포인트 | 내용 |
|------|--------|-----------|------|
| `routers/__init__.py` | - | - | 패키지 초기화 |
| `routers/auth.py` | /api/auth | 4개 | 로그인/로그아웃/me/비밀번호변경 |
| `routers/users.py` | /api/users | 5개 | 계정 CRUD + 비밀번호 초기화 |
| `routers/notices.py` | /api/notices | 6개 | 공고 조회/검색/통계/태그목록/상세/삭제 |
| `routers/tags.py` | /api/notice-tags | 3개 | 태그 조회/설정/해제 |
| `routers/settings.py` | /api/settings | 2개 | 표시 설정 조회/변경 |
| `routers/keywords.py` | /api/keywords | 7개 | 키워드 CRUD + 공통/출처별 |
| `routers/sources.py` | /api/sources | 7개 | 출처 CRUD + 수집실행 + 출처별 키워드 |
| `routers/collection.py` | /api | 3개 | 전체수집/스크래퍼수집/단건재시도 |
| `routers/organizations.py` | /api | 3개 | 나라장터 카테고리/기관목록 |

- 헬퍼 함수 이동: `_fetch_kstartup_detail()` → notices.py, `_build_scraper_url_map()` → sources.py, `_calc_days()` → collection.py
- `__import__("fastapi").HTTPException` 안티패턴 7건 → 정상 import로 변경
- threading lock / `_collecting_targets` → collection.py로 이동

### Step 2: 공유 유틸리티 (`backend/utils/`)

| 파일 | 함수 | 대체 대상 |
|------|------|----------|
| `utils/db.py` | `db_cursor(commit)`, `db_connection()` | conn/cursor/close 패턴 50회+ |
| `utils/text.py` | `clean_html()`, `clean_html_to_text()` | kstartup/_clean, ccei/_clean, mss_biz 인라인 |
| `utils/dates.py` | `format_date()` | nara/_format_datetime, kstartup/_format_date, ccei/_format_date (4종 통합) |
| `utils/keywords.py` | `match_keywords()`, `load_active_keywords()` | 4개 수집기 동일 패턴 |
| `utils/status.py` | `determine_status()` | 4개 수집기 동일 if/try/except 블록 |

### Step 3: Base Collector 클래스

**`collectors/base.py`** — 범용 UPSERT 및 수집 오케스트레이션

```python
class BaseCollector:
    source_name: str
    def collect_and_save(keywords, days, mode) -> dict  # 템플릿 메서드
    def fetch_announcements(keywords, days) -> list      # 서브클래스 구현
    def post_filter(notices) -> list                     # 옵션 훅
    def save_to_db(notices) -> (inserted, updated)       # 범용 UPSERT
```

| 수집기 | 변경 전 | 변경 후 | 감소 | 제거 항목 |
|--------|--------|--------|------|----------|
| mss_biz.py | 201줄 | 130줄 | -35% | save_to_db, keyword loading |
| ccei.py | 241줄 | 148줄 | -39% | save_to_db, _clean, _format_date, _clean_html_to_text |
| kstartup.py | 219줄 | 151줄 | -31% | save_to_db, _clean, _format_date |
| nara.py | 354줄 | 244줄 | -31% | save_to_db, _format_datetime |

- 하위 호환 유지: 각 수집기에 `_collector = XxxCollector()` + `collect_and_save()` 래퍼 → collect_all.py 변경 불필요
- 범용 save_to_db(): 표준 10개 필드 + dict 나머지 키를 동적 extra 필드로 처리

### Step 5: Frontend JS 모듈 추출

**`frontend/js/utils.js`** (신규) — 7개 공유 함수

| 함수 | 기존 중복 위치 |
|------|-------------|
| `escapeHtml()` | app.js, settings.js, source-list.js, auth.js(escapeHtmlNav) |
| `renderPaginationGeneric()` | app.js + bid-list/review-list/excluded-list 인라인 |
| `getSourceClass()` | app.js |
| `getTagClass()` | app.js |
| `statusBadgeHtml()` | 4곳 인라인 |
| `formatPrice()` | app.js |
| `parseAttachments()` | app.js + 2곳 인라인 |

- 7개 HTML 파일 모두 `<script src="/js/utils.js">` 추가 (auth.js 앞)
- auth.js의 `escapeHtmlNav()` → `escapeHtml()` 참조로 변경

### Step 7: Config 통합

**`config.py` 추가 항목:**
```python
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin1234")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD", "1234")
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "24"))
PORT = int(os.getenv("PORT", "8000"))
```

**`build_exe.spec` 업데이트:**
- hiddenimports에 `routers.*` 10개 + `utils.*` 6개 + `collectors.base` 추가

## 미완료 (코스메틱)
- Step 4: database.py 내부 재구성 (섹션 분리, 시드 데이터 함수화)
- Step 6: HTML 인라인 스크립트를 별도 JS 파일로 추출 (bid-list.js, review-list.js 등)

## 검증
- 전체 임포트 테스트 통과
- 45개 API 라우트 정상 등록 확인
- 서버 기동 (uvicorn) 정상
- 유틸리티 함수 단위 테스트 통과

## 새로 생성된 파일

```
backend/
├── routers/
│   ├── __init__.py
│   ├── auth.py
│   ├── users.py
│   ├── notices.py
│   ├── tags.py
│   ├── settings.py
│   ├── keywords.py
│   ├── sources.py
│   ├── collection.py
│   └── organizations.py
├── utils/
│   ├── __init__.py
│   ├── db.py
│   ├── text.py
│   ├── dates.py
│   ├── keywords.py
│   └── status.py
└── collectors/
    └── base.py

frontend/js/
└── utils.js
```

## 수정된 파일
- `backend/main.py` — 1,210줄 → 95줄 (라우터 include + 정적파일 서빙만)
- `backend/config.py` — 인증/세션 상수 추가
- `backend/collectors/mss_biz.py` — BaseCollector 상속으로 전환
- `backend/collectors/kstartup.py` — BaseCollector 상속으로 전환
- `backend/collectors/ccei.py` — BaseCollector 상속으로 전환
- `backend/collectors/nara.py` — BaseCollector 상속으로 전환
- `backend/auth.py` — escapeHtmlNav 참조 제거
- `frontend/js/app.js` — 중복 함수 제거, utils.js 참조
- `frontend/js/settings.js` — escapeHtml 제거
- `frontend/js/source-list.js` — escapeHtml 제거
- `frontend/js/auth.js` — escapeHtmlNav → escapeHtml 참조
- 7개 HTML 파일 — utils.js 스크립트 태그 추가
- `build_exe.spec` — hiddenimports 확장
