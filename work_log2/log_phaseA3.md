# Phase A.3: 개별 기관 스크래핑 확장 — 작업 로그

## 작업일: 2026-03-29

## 목표
API가 없는 28개 입찰공고 사이트를 HTML 스크래핑으로 수집.
하나의 "일괄 수집" 버튼으로 28개 기관을 한 번에 스크래핑.

## 수집 전략
1. 최근 1개월 공고만 스크래핑 (페이지 1~3)
2. 공통 키워드로 매칭 (제목 기준)
3. 매칭된 공고만 bid_notices DB에 저장

## 구현 내역

### 1. 범용 스크래퍼 프레임워크 (신규)
- **파일:** `backend/collectors/generic_scraper.py`
- `requests` + `BeautifulSoup4` 기반
- JSON 설정(CSS 셀렉터, URL 패턴)으로 다양한 사이트 대응
- 주요 함수:
  - `scrape_site(config, days)` — 단일 사이트 스크래핑
  - `_match_keywords(notices, keywords)` — 제목 기준 키워드 매칭
  - `save_to_db(notices)` — bid_notices UPSERT
  - `collect_all_scrapers(mode)` — 28개 일괄 실행

### 2. 스크래퍼 설정 파일 (신규)
- **파일:** `backend/collectors/scraper_configs.json`
- 28개 기관별 설정: list_url, CSS 셀렉터, 페이지네이션, 인코딩 등
- 사이트 HTML 구조 분석 후 셀렉터 조정 완료

### 3. DB 변경
- **파일:** `backend/database.py`
- `collect_sources` 테이블에 28개 행 추가 (`collector_type="scraper"`)
- INSERT OR IGNORE로 중복 방지

### 4. 수집 로직 연동
- **파일:** `backend/collectors/collect_all.py`
- `collect_all_scrapers` import 추가
- `collect_by_source()`: scraper 타입은 일괄 수집 안내
- `collect_all()`: API 출처 수집 후 스크래퍼 일괄 실행

### 5. API 엔드포인트
- **파일:** `backend/main.py`
- `POST /api/collect?target=scrapers` — 스크래퍼 일괄 수집 전용
- `POST /api/collect` (기존) — 전체 수집 시 스크래퍼도 포함

### 6. 프론트엔드 UI
- **파일:** `frontend/source-list.html`, `frontend/js/source-list.js`
- 기존 4개 출처 카드 아래에 **"개별 기관 입찰공고 (스크래핑)"** 섹션 추가
- 주황색 영역, 일괄 수집 버튼 1개
- 기관 목록 접기/펼치기 (각 기관별 최근 수집 시각 표시)
- 수집 완료 후 성공/실패/수집/매칭/신규 건수 표시
- scraper 타입 출처는 기존 개별 카드에서 제외 (별도 섹션으로 분리)

## 테스트 결과
- 28개 사이트 전체 스크래핑 성공 (실패 0)
- 소요시간: 약 50~60초
- 수집 358건 → 키워드 매칭 136건 → DB 저장 136건
- 날짜 파싱: 28건 성공, 108건 오늘 날짜 대체 (사이트별 HTML 구조 차이)

## 사이트 검증 결과
- **정상 (28개):** 입찰공고 확인, 스크래퍼 구현 완료
- **직접 확인 필요 (16개):** 별도 확인 후 추가 예정
- **접속 불가 (5개):** SSO/SSL/404 등 → 보류
- **JS SPA (1개):** 한국예탁결제원 → 보류
- 검증 결과는 `work_log2/site_verification.xlsx`에 정리

## 파일 목록

| 파일 | 작업 |
|------|------|
| `backend/collectors/generic_scraper.py` | 신규 |
| `backend/collectors/scraper_configs.json` | 신규 |
| `backend/collectors/collect_all.py` | 수정 |
| `backend/database.py` | 수정 |
| `backend/main.py` | 수정 |
| `frontend/source-list.html` | 수정 |
| `frontend/js/source-list.js` | 수정 |
| `work_log2/site_verification.xlsx` | 신규 (검증 결과) |
| `work_log2/log_phaseA3.md` | 신규 (작업 로그) |

## 향후 작업
- [ ] △ 직접 확인 필요 16개 사이트 검증 후 추가
- [ ] 날짜 파싱 실패 사이트 개별 파서 개선
- [ ] JS SPA 사이트 대응 (headless browser 등)
- [ ] Phase E에서 자동 스케줄러 연동
