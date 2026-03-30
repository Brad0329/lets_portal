# Phase A.3: 개별 기관 스크래핑 확장 — 작업 로그

## 작업일: 2026-03-29 ~ 03-30

## 목표
API가 없는 입찰공고 사이트를 HTML 스크래핑/JSON API로 수집.
하나의 "일괄 수집" 버튼으로 전체 기관을 한 번에 수집.

## 수집 전략
1. 최근 1개월 공고만 스크래핑 (페이지 1~3)
2. 공통 키워드로 매칭 (제목 기준)
3. 매칭된 공고만 bid_notices DB에 저장
4. 날짜 없는 공지/안내글은 수집에서 제외

## 구현 내역

### 1. 범용 스크래퍼 프레임워크 (신규)
- **파일:** `backend/collectors/generic_scraper.py`
- `requests` + `BeautifulSoup4` 기반 HTML 스크래핑
- CCEI 입찰공고 JSON API 수집 (`scrape_ccei_allim`)
- JSON 설정(CSS 셀렉터, URL 패턴)으로 다양한 사이트 대응
- offset 기반 페이지네이션 지원 (`offset_size` 설정)
- 사이트별 parser 선택 지원 (html.parser/lxml)
- 주요 함수:
  - `scrape_site(config, days)` — 단일 사이트 HTML 스크래핑
  - `scrape_ccei_allim(region, name, days)` — CCEI 입찰공고 JSON API
  - `_parse_date(text)` — 다양한 날짜 형식 파싱 (yyyy.MM.dd, yy.MM.dd, yyyyMMdd, 한국어, 기간)
  - `_match_keywords(notices, keywords)` — 제목 기준 키워드 매칭
  - `save_to_db(notices)` — bid_notices UPSERT
  - `collect_all_scrapers(mode)` — 38개 일괄 실행

### 2. 스크래퍼 설정 파일 (신규)
- **파일:** `backend/collectors/scraper_configs.json`
- 31개 기관별 설정: list_url, CSS 셀렉터, 페이지네이션, 인코딩 등
- 사이트 HTML 구조 분석 후 셀렉터 개별 조정 완료

### 3. DB 변경
- **파일:** `backend/database.py`
- `collect_sources` 테이블에 38개 행 추가 (`collector_type="scraper"`)
  - HTML 스크래핑 31개 + CCEI 입찰공고 7개
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

## 추가 작업 (03-30)

### 날짜 파싱 개선
- `_parse_date()` 확장: 5가지 형식 지원 (yyyy.MM.dd, yy.MM.dd, yyyyMMdd, 한국어, 기간)
- 5개 실패 사이트 셀렉터 수정 (gica, gnto, jbba, ctp, keiti)
- 파싱 성공률: 21% → 64%
- 날짜 없는 공지글은 수집에서 제외 (오늘 날짜 대체 → skip으로 변경)

### 3개 기관 추가 (△ → 정상)
- **경기대진테크노파크**: div 기반 구조 (div.colgroup.noti)
- **세종테크노파크**: Gnuboard 패턴 (td.td_subject/td.td_datetime)
- **한국발명진흥회**: offset 기반 페이지네이션 (pager.offset)

### CCEI 입찰공고 7개 지역 추가
- JSON API 방식: POST `/{region}/allim/allimList.json`
- 7개 지역: 경기/경남/대구/부산/세종/인천/충북
- `scrape_ccei_allim()` 함수로 구현

## 최종 테스트 결과
- **38개 사이트 전체 성공 (실패 0)**
- 소요시간: 약 50~60초
- 수집 63건 → 키워드 매칭 45건 → DB 저장 45건

## 사이트 검증 결과 종합

| 구분 | 개수 | 상태 |
|------|------|------|
| HTML 스크래핑 | 31개 | ✅ 구현 완료 |
| CCEI 입찰공고 JSON | 7개 | ✅ 구현 완료 |
| **합계** | **38개** | **일괄 수집 가능** |
| 제외 (입찰 아님) | 4개 | 대전기업정보포털, 부산창업포탈, 건국대, 인천TP |
| 추가 조치 필요 | 4개 | 경남TP(URL변경), 대전정보문화(SSL), 전주정보문화(SSL+URL), 한국예탁결제원(SPA) |
| URL 변경 필요 | 2개 | 제주콘텐츠진흥원, 소상공인시장진흥공단(실효성 낮음) |
| JS 렌더링 보류 | 1개 | 한국지식재산보호원 |

검증 상세는 `work_log2/site_verification.xlsx`에 정리

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
- [ ] 추가 조치 필요 4개 사이트 (경남TP URL변경, SSL 사이트 2개, 한국예탁결제원 SPA)
- [ ] 제주콘텐츠진흥원 URL 변경
- [ ] 한국지식재산보호원 JS 렌더링 대응
- [ ] 키워드 매칭 ON/OFF 옵션 (출처별)
- [ ] 스크래핑 에러 알림 (사이트 개편 감지)
- [ ] Phase E에서 자동 스케줄러 연동
