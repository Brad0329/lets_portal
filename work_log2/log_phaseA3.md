# Phase A.3: 개별 기관 스크래핑 확장 — 작업 로그

## 작업일: 2026-03-29 ~ 03-30 (추가 작업 03-30 오후)

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
- POST 페이지네이션 지원 (`post_data`, `page_param_key` 설정)
- JSON POST 지원 (`post_json` 설정) + 부분 HTML 파싱 (`grid_selector` 설정)
- 세션 쿠키 초기화 지원 (`session_init_url` 설정)
- JS 링크 변환 지원 (`link_js_regex`, `link_template` 설정)
- 사이트별 parser 선택 지원 (html.parser/lxml)
- 주요 함수:
  - `scrape_site(config, days)` — 단일 사이트 HTML 스크래핑
  - `scrape_ccei_allim(region, name, days)` — CCEI 입찰공고 JSON API
  - `_parse_date(text)` — 다양한 날짜 형식 파싱 (yyyy.MM.dd, yy.MM.dd, yyyyMMdd, 한국어, 기간)
  - `_match_keywords(notices, keywords)` — 제목 기준 키워드 매칭
  - `save_to_db(notices)` — bid_notices UPSERT
  - `collect_all_scrapers(mode)` — 49개 일괄 실행

### 2. 스크래퍼 설정 파일 (신규)
- **파일:** `backend/collectors/scraper_configs.json`
- 39개 기관별 설정: list_url, CSS 셀렉터, 페이지네이션, 인코딩 등
- 사이트 HTML 구조 분석 후 셀렉터 개별 조정 완료

### 3. DB 변경
- **파일:** `backend/database.py`
- `collect_sources` 테이블에 49개 행 추가 (`collector_type="scraper"`)
  - HTML 스크래핑 39개 + CCEI 입찰공고 7개 + 한국예탁결제원 JSON 1개
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

### 제외 사이트 3개 재검증 → 복구 추가 (03-30 오후)
- **인천테크노파크**: 사이트 정상 확인 (이전 검증 시 일시 장애), POST 페이지네이션 + 세션 쿠키 필요 → 수집 19건/매칭 12건
- **건국대학교**: SSO 리다이렉트 후 로그인 없이 정상 접근 가능, K2Web CMS 구조 → 수집 23건/매칭 6건
- **대전기업정보포털**: 지원사업 공고이지만 사실상 입찰공고 성격, GET 페이지네이션 → 수집 30건/매칭 29건
- `generic_scraper.py`에 POST 페이지네이션, 세션 초기화, JS 링크 변환 기능 추가

### 경남테크노파크 복구 (추가 조치 → 구현 완료)
- 기존 URL(more.co.kr) 서버 다운 → 신규 URL `https://www.gntp.or.kr/biz/apply` 확인
- JSON POST API (`/biz/apply2`) + `#gridData` 부분 HTML 파싱 방식
- `generic_scraper.py`에 `post_json`, `grid_selector` 기능 추가 → 수집 20건/매칭 19건

### 추가 조치 3개 사이트 복구 (추가 조치 → 구현 완료)
- **대전정보문화산업진흥원**: SSL verify=False로 접근, board.es 구조 → 수집 1건
- **전주정보문화산업진흥원**: URL `/2016/` → `/2025/` 변경, SSL verify=False → 수집 1건/매칭 1건
- **한국예탁결제원**: React SPA → JSON API `/ko/api/content?menuId=KR_ABT_070300` 발견, `scrape_ksd()` 전용 함수 구현 → 수집 3건

### 제주콘텐츠진흥원 URL 변경 → 구현 완료
- 기존 URL(공지사항) → 신규 URL `https://ofjeju.kr/bussiness/businessinfo/business.htm` (사업신청)
- 카드형 레이아웃 (`div.app-list`) — 날짜가 리스트에 없음
- `skip_no_date: false` 옵션 추가 (오늘 날짜 대체) → 수집 12건/매칭 11건

## 수집 UX 개선 (03-30 추가)

### 일괄 수집 UX 개선
- 경과 시간 타이머 표시 (수집중 실시간 카운트)
- 수집 완료 시 결과 요약 한 줄 표시: `완료 — 48/48개 성공 | 수집 63건, 매칭 45건, 신규 3건 (73초)`
- 수집 시작 시 기관 목록 자동 펼침

### 수집 시간 통일
- 기존: 각 기관별 스크래핑 완료 시점(`datetime('now')`) → 48개 시간 제각각
- 변경: 버튼 누른 시점(`batch_time`)을 전달하여 모든 기관 동일 시간 기록

### 기관 목록에 URL 표시
- API(`/api/sources`)에서 scraper 출처에 `site_url` 필드 추가
- `scraper_configs.json` + CCEI/KSD/부산 하드코딩에서 URL 매핑 생성
- 기관명 아래에 도메인 링크 표시 (클릭 시 새 탭)

### 기관 목록 건수 클릭 → 공고 리스트 필터 이동
- 건수 클릭 시 `/index.html?source=기관명`으로 이동
- `app.js`에서 URL 파라미터 `?source=` 감지 → 출처 필터 자동 설정

### 서버 측 중복 수집 방지
- `threading.Lock` + `_collecting_targets` set으로 동시 실행 차단
- 수집 중 재요청 시 409 응답: "이미 수집이 진행 중입니다"
- 개별 출처 수집도 동일하게 보호

### JS 링크 → 실제 URL 변환 수정
- **건국대학교**: `javascript:jf_artclView('konkuk','sptBid','4159')` → `https://www.konkuk.ac.kr/bid/konkuk/4159/sptBidView`
  - `link_js_regex`/`link_template` 다중 그룹(`{1}`,`{2}`,`{3}`) 지원 추가
- **한국지식재산보호원**: `javascript:pageviewform('6782')` → `https://www.koipa.re.kr/home/board/brdDetail.do?menu_cd=000042&num=6782`
- **부산창업포탈**: 리스트 URL(`/biz_sup?busi_code=`) → 상세 URL(`/biz_sup/{busi_code}?mcode=biz02`)

## UI/UX 추가 개선 (03-30 추가)

### 네비게이션 사이드바 전환
- 상단 가로 메뉴 → 좌측 세로 사이드바(200px 고정)로 변경
- 메뉴 순서 조정: 공고수집 출처를 맨 하단으로 이동
- 사용자 정보/로그아웃을 사이드바 하단에 배치
- 반응형: 768px 이하에서 56px 아이콘 전용 모드

### 수집 날짜 범위 입력 방식
- 기존 "빠른수집/전체수집" 버튼 → `[시작일] ~ [종료일] [수집]`으로 통합
- API 출처 4개 + 스크래퍼 일괄 수집 모두 동일 UI
- 기본값 오늘, 백엔드에서 start_date → days로 변환
- 4개 수집기(nara/kstartup/mss/ccei) + 스크래퍼 모두 `days` 파라미터 직접 수용

### 스크래퍼 실패 기관 재시도
- 일괄 수집 후 실패 기관은 빨간 테두리 + "수집실패 [재시도]" 표시
- 재시도 클릭 → `/api/scraper/{기관명}/collect` 단건 API 호출
- `collect_single_by_name()` 함수로 기관명 기반 단건 수집 지원

### 기타 UI 개선
- 검토요청/입찰예정 페이지: 검색창 삭제 (필터만 유지)
- 공고 중인 사업: 기본 정렬을 입찰공고일 최신순으로 변경
- 대시보드 출처별 현황: "진행중 N건" 클릭 → 해당 출처 공고 리스트로 이동

## 최종 테스트 결과
- **48개 사이트 전체 성공 (실패 0)**
- 소요시간: 약 70~80초
- 수집 63건 → 키워드 매칭 45건 → DB 저장 45건 (03-30 기준)

## 사이트 검증 결과 종합

| 구분 | 개수 | 상태 |
|------|------|------|
| HTML 스크래핑 | 39개 | ✅ 구현 완료 |
| CCEI 입찰공고 JSON | 7개 | ✅ 구현 완료 |
| 한국예탁결제원 JSON | 1개 | ✅ 구현 완료 |
| 부산창업포탈 JSON | 1개 | ✅ 구현 완료 |
| **합계** | **48개** | **일괄 수집 가능** |
| URL 변경 필요 | 1개 | 소상공인시장진흥공단(실효성 낮음) |

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

## 버그 수정 및 개선 (03-31)

### 날짜 표시 UTC → 로컬 시간 수정
- **프론트엔드 (source-list.js)**: `new Date().toISOString().slice(0,10)` → `getFullYear()/getMonth()/getDate()` 로컬 시간 기준으로 변경
  - 수집 날짜 입력 기본값이 오전 9시 전에 어제로 표시되던 문제 수정 (2곳)
- **백엔드 (collect_all.py, generic_scraper.py)**: `datetime('now')` → `datetime('now','localtime')` 변경
  - `last_collected_at` 수집 시간이 UTC로 저장되어 9시간 느리게 표시되던 문제 수정 (2곳)

### 스크래퍼 중복 수집 수정
- **원인**: `hash()` 함수는 Python 실행마다 다른 값 반환 (Python 3.3+ 보안 해시 랜덤화)
  - 동일 공고(제목+링크)도 수집할 때마다 다른 `bid_no` 생성 → UNIQUE 제약 우회되어 중복 등록
- **수정**: `hash()` → `hashlib.md5()` (결정적 해시)로 변경
  - `bid_no = f"SCR-{source_key}-{abs(hash(title + link)) % 1000000:06d}"` (변경 전)
  - `bid_no = f"SCR-{source_key}-{hashlib.md5((title+link).encode()).hexdigest()[:10]}"` (변경 후)
- **영향 범위**: 스크래퍼 48개 출처만 해당 (API 4개 출처는 공식 ID 사용으로 문제 없음)
- 기존 중복 데이터 68건 삭제 후 재수집으로 검증 완료

### 공고 리스트 2차 정렬 추가
- 공고 중인 사업 리스트: 1차 입찰공고일 최신순 + **2차 키워드 개수 내림차순**
  - 같은 날짜 공고 중 키워드가 많이 매칭된 공고가 상위 노출
  - SQL로 계산: `LENGTH(keywords) - LENGTH(REPLACE(keywords, ',', '')) + 1`
  - 별도 컬럼 추가 없이 기존 콤마 구분 문자열에서 실시간 계산

### 키워드 리빌딩 (85개 → 69개)
- 나라장터 API 호출 최적화를 위해 중복/포함 관계 키워드 정리
- 삭제 16건: 띄어쓰기 중복 3건, 짧은 키워드에 포함되는 긴 키워드 13건
- API 호출 255회 → 207회 (약 19% 감소)
- 상세: `work_log2/Keyword_rebuilding.md`

## 향후 작업
- [ ] 키워드 매칭 ON/OFF 옵션 (출처별)
- [ ] 스크래핑 에러 알림 (사이트 개편 감지)
- [ ] Phase E에서 자동 스케줄러 연동
