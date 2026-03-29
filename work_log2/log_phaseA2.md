# Phase A.2: 공고수집 출처 관리 — 작업 로그

## 작업일: 2026-03-29

## 목표
- 기존 "수집 실행" 버튼 하나로 3개 출처 일괄 수집 → 출처별 독립 관리로 전환
- 4번째 출처(창조경제혁신센터) 추가
- 키워드를 공통 + 출처별 추가 구조로 변경
- 나라장터 수집 속도 개선 (수집 모드 분리)

## 완료된 작업

### 1. DB 스키마 변경 (`backend/database.py`)
- `collect_sources` 테이블 생성 (id, name, collector_type, is_active, last_collected_at, last_collected_count)
- 초기 데이터 4건: 나라장터(nara), K-Startup(kstartup), 중소벤처기업부(mss_biz), 창조경제혁신센터(ccei)
- `keywords` 테이블에 `source_id` 컬럼 추가 (NULL=공통, 값=출처 전용)

### 2. 출처 관리 API (`backend/main.py`)
- `GET /api/sources` — 출처 목록
- `POST /api/sources` — 출처 추가 (admin)
- `PUT /api/sources/{id}` — 출처 수정 (admin)
- `DELETE /api/sources/{id}` — 출처 삭제 (admin)
- `POST /api/sources/{id}/collect?mode=daily|full` — 개별 출처 수집 실행
- `/source-list.html` 정적 라우트 추가

### 3. 키워드 API 변경 (`backend/main.py`)
- `GET /api/keywords/common` — 공통 키워드 목록
- `POST /api/keywords/common` — 공통 키워드 추가
- `GET /api/sources/{id}/keywords` — 출처 전용 추가 키워드
- `POST /api/sources/{id}/keywords` — 출처에 추가 키워드 등록
- 기존 `/api/keywords` 엔드포인트는 하위호환 유지

### 4. CCEI 수집기 신규 작성 (`backend/collectors/ccei.py`)
- 엔드포인트: `https://ccei.creativekorea.or.kr/service/business_list.json` (POST)
- 응답 구조: `data.result.list` (처음 `data.list`로 작성 → 디버깅 후 수정)
- 날짜 형식: `yyyy.MM.dd` → `yyyy-MM-dd` 변환
- sdate/edate 파라미터 제거 (sPtime=now만으로 현재 프로그램 필터)
- content: HTML → 텍스트 변환(`_clean_html_to_text`), 최대 1000자 저장
- apply_url: content 텍스트에서 URL 추출
- 페이지 사이즈 5건, bid_no = `CCEI-{seq}`

### 5. 수집기 리팩토링 (`backend/collectors/`)
- 모든 수집기에 `keywords` 파라미터 추가 (None이면 기존처럼 DB에서 로드)
- 모든 수집기에 `mode` 파라미터 추가 (daily=최근2일, full=설정기간)
- `collect_all.py`에 `collect_by_source(source_id, mode)` 함수 추가
- `COLLECTOR_MAP` 딕셔너리로 collector_type → 수집기 함수 매핑
- `_load_keywords_for_source()`: 공통 + 출처 전용 키워드 합산 로드

### 6. 프론트엔드 — source-list.html + source-list.js (신규)
- 상단: 출처별 카드 (수집 버튼, 진행바, 수집 결과, 추가 키워드)
- 하단: 공통 키워드 영역 (칩 형태, ON/OFF 토글, 추가/삭제)
- 나라장터만 [빠른수집][전체수집] 2개 버튼, 나머지는 [수집] 1개
- 수집 중 indeterminate 애니메이션 진행바
- 수집 완료 후 결과 메시지 보존 (`collectResults` 객체)
- 마지막 수집 시간: SQLite datetime → ISO 변환 후 파싱

### 7. 네비게이션 메뉴 추가 (`frontend/js/auth.js`)
- "📡 공고수집 출처" 메뉴 추가 (대시보드 다음 위치)
- 권한: admin 또는 perm_keyword

### 8. 기존 코드 정리
- `index.html`: 수집 실행 버튼 제거, 출처 필터를 하드코딩에서 동적 로드로 변경
- `app.js`: `runCollect()` 함수 제거, `loadSourceFilter()` 추가
- `settings.html`: 키워드 관리/수집 실행 섹션을 source-list.html 링크로 대체
- `dashboard.html`: 출처별 수집 시간 표시 (collect_sources 데이터 병합)

### 9. 나라장터 수집 속도 개선
- `mode` 파라미터: daily(최근 2일) / full(설정 전체기간) 분리
- API 호출 간 딜레이: 0.2초 → 0.5초 (rate limit 방지)
- 429 재시도: 1회 → 최대 3회, 점진적 대기 (3초, 6초, 9초)

## 변경 파일 목록

| 파일 | 작업 |
|------|------|
| `backend/database.py` | collect_sources 테이블, keywords.source_id 추가 |
| `backend/main.py` | 출처 API, 키워드 API, 수집 mode 파라미터 |
| `backend/collectors/collect_all.py` | collect_by_source(), COLLECTOR_MAP, _load_keywords_for_source() |
| `backend/collectors/nara.py` | keywords/mode 파라미터, 429 재시도 개선 |
| `backend/collectors/kstartup.py` | keywords/mode 파라미터 |
| `backend/collectors/mss_biz.py` | keywords/mode 파라미터 |
| `backend/collectors/ccei.py` | **신규** — 창조경제혁신센터 수집기 |
| `frontend/source-list.html` | **신규** — 출처 관리 페이지 |
| `frontend/js/source-list.js` | **신규** — 출처 관리 JS |
| `frontend/js/auth.js` | 네비게이션 메뉴 추가 |
| `frontend/js/app.js` | 수집 버튼 제거, 출처 필터 동적 로드 |
| `frontend/index.html` | 수집 버튼 제거, 출처 필터 동적화 |
| `frontend/dashboard.html` | 출처별 수집 시간 표시 |
| `frontend/settings.html` | 키워드/수집 섹션 링크로 대체 |

## 디버깅 이슈

### CCEI API 응답 구조
- 처음 `data.get("list")` → 실제는 `data.get("result", {}).get("list")`
- `total` → `result.size`
- 날짜 형식 `yyyy.MM.dd` (`.`으로 구분) → `_format_date()`에 처리 추가

### CCEI sdate/edate 파라미터
- sdate/edate를 보내면 0건 반환 → 제거하고 sPtime=now만 사용

### CCEI apply_url HTML 잔여물
- raw HTML에서 URL 추출 시 `&lt;` 등 섞임 → 텍스트 변환 후 추출로 수정

### 나라장터 429 API quota exceeded
- 테스트 반복으로 일일 API 한도 초과 → 내일 리셋 후 확인 필요
- 코드는 정상, rate limit 처리 개선 완료

## 미완료 / 후속 작업
- 나라장터 빠른수집/전체수집 실제 동작 테스트 (API 한도 리셋 후)
- Phase E: 스케줄러 (자동 수집), 변경 감지
