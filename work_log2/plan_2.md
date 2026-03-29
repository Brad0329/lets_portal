# LETS 프로젝트 관리 시스템 확장 계획 (Plan 2)

## 1. 프로젝트 방향

기존: 입찰공고 조회/검색 포탈 (단일 페이지)
확장: **LETS 프로젝트 관리 시스템** — 공고 조회 → 입찰 관리 → 제안서 작성 비즈니스 전체 흐름 커버

## 2. 메뉴 구조

```
LETS 프로젝트 관리 시스템
├── 대시보드                  (각 메뉴 요약 카드 — 클릭 시 해당 리스트 이동)
├── 공고수집 출처              (출처별 수집 관리 — 키워드 설정, 개별 수집 실행)
├── 공고 중인 사업리스트       (현재 메인 — 제외 태그 제외하여 표시)
├── 입찰 예정 공고 리스트      (입찰대상 태그)
├── 입찰 준비/관리            (입찰 실무 — 체크리스트, 제안서 등)
├── 기관 정보                (기관 상세 정보 관리)
├── 제외된 공고 리스트         (제외 태그 — 복원 가능)
└── 설정                    (조회조건, 계정 관리)
```

### 대시보드 구성
```
┌──────────────┐  ┌──────────────┐
│ 📋 공고 중인 사업 │  │ 📌 입찰 예정 공고 │
│    334건       │  │     12건       │
│   (클릭→이동)   │  │   (클릭→이동)   │
└──────────────┘  └──────────────┘
┌──────────────┐  ┌──────────────┐
│ 📝 입찰 준비/관리│  │ 🏢 기관 정보     │
│  준비중 3건     │  │    58개        │
│  제출완료 2건   │  │  최근갱신 3/28  │
│   (클릭→이동)   │  │   (클릭→이동)   │
└──────────────┘  └──────────────┘
```

## 3. 로그인/권한

### 인증 방식
- ID/비밀번호 로그인
- 관리자가 계정 생성 → 실무자에게 제공
- 비로그인 시 접근 불가

### 역할 및 권한

**기본 권한:**

| 권한 항목 | 관리자 | 실무자(기본) |
|---------|-------|-----------|
| 공고 조회 | O | O |
| 입찰 준비/제안서 | O | O |
| 입찰예정/제외 | O | X |
| 표시 설정 | O | X |
| 키워드 관리 | O | X |
| 기관 목록 | O | X |
| 계정 관리 | O | X (관리자 전용) |
| 내 정보 수정 | O | O |

- **관리자**: 전체 시스템 관리 + 입찰 대상 선정/제외 판단 + 계정 생성
- **실무자**: 관리자가 선정한 입찰 건의 준비/제안서 작성
- 관리자가 실무자별로 추가 권한 부여 가능:
  - **입찰예정/제외** — 공고를 입찰 대상으로 선정하거나 제외 처리
  - **표시 설정** — 공고 조회 기간, 정렬 순서, 페이지당 건수 등 변경
  - **키워드 관리** — 수집 키워드 추가/삭제/ON·OFF
  - **기관 목록** — 기관 정보 조회 및 수정

### 계정 생성 흐름

1. **관리자**가 계정 생성: ID + 이름 입력, 기본 비밀번호 '1234' 자동 설정, 추가 권한 체크
2. **실무자** 첫 로그인 → 비밀번호 변경 강제 (변경 전 다른 기능 접근 불가)
3. 비밀번호 변경 완료 → 정상 업무 시작

### 설정 메뉴 구조

```
설정
├── 표시 설정        (기존 — 조회기간, 정렬, 페이지당 건수)
├── 키워드 관리      (기존 — 키워드 ON/OFF, 추가/삭제)
├── 계정 관리        (관리자 전용)
│   ├── 계정 생성 (ID/이름/권한 체크 → 기본PW '1234')
│   ├── 계정 목록 (수정/비밀번호 초기화/삭제)
│   └── 권한 설정 (실무자별 추가 권한 부여)
├── 기관 목록        (기존)
└── 내 정보 수정     (모든 사용자 — 비밀번호 변경)
```

## 4. 확장 기능 상세

### 기능 A: 입찰 예정 공고 관리

#### 워크플로우
```
(태그 없음) → 검토요청(실무자) → 입찰대상 또는 제외(관리자)
```

#### 태그 시스템
- `notice_tags` 테이블 (공고 1건당 태그 1개, UPSERT 방식)
- 유효 태그: `검토요청`, `입찰대상`, `제외`, `낙찰`, `유찰`
- 태그 설정 시 설정자(tagged_by), 메모, 일시 기록

#### 역할별 권한
- **실무자**: 모달에서 `검토요청` 버튼만 표시, 본인 검토요청 태그 해제 가능
- **관리자(perm_bid_tag)**: `검토요청` + `입찰대상` + `제외` 전체 버튼, 모든 태그 해제 가능

#### 페이지 구성
- **검토요청 공고리스트** (`review-list.html`): 검토요청 태그 공고 — 요청자 표시
- **입찰 예정 공고리스트** (`bid-list.html`): 입찰대상 태그 공고
- **제외된 공고리스트** (`excluded-list.html`): 제외 태그 공고 — 복원 버튼
- **공고 중인 사업리스트**: 제외 태그 공고 자동 숨김

#### 네비게이션 메뉴
```
대시보드 | 공고수집 출처 | 공고 중인 사업 | 검토요청 | 입찰 예정 | 제외 공고 | 설정
          (관리자/keyword)  (모든 사용자)    (모든)    (관리자)    (관리자)   (권한별)
```

#### 대시보드 카드
```
공고 중인 사업 | 검토요청 공고 | 입찰 예정 공고 | 제외된 공고 | 전체 공고
```

- 입찰 진행 상태 관리 (입찰대상 → 준비중 → 제출완료 → 낙찰/유찰) — Phase B에서 확장

### 기능 B: 입찰 준비 페이지
- 입찰 예정 리스트에서 '입찰 준비' 버튼 → 해당 입찰 관리 페이지
- 체크리스트 (필요 서류, 마감일 등)
- 파일 관리 (관련 문서 업로드/다운로드)
- 메일 발송 (제안서 등 첨부 발송)
- 발송 이력 조회 (해당 입찰 건의 메일 목록)
- 투입 인력/예산 계획 (추후)
- 입찰 이력 관리 (추후)

### 메일 발송 기능
- 서버 SMTP 방식 (Gmail/네이버 등 — 소규모 충분, 추후 SendGrid 등 전환 가능)
- 제안서 파일 옆 [메일 보내기] 버튼 → 받는 사람, 제목, 내용 입력 + 파일 자동 첨부
- 발송 시 DB에 이력 저장: 발송자, 받는 사람, 제목, 내용, 첨부파일, 발송일시, 입찰건 ID
- **열람 권한:**
  - 발송한 본인: 자기가 보낸 메일만 조회
  - 관리자: 전체 메일 발송 이력 조회
- **조회 위치:**
  - 입찰 준비 페이지 내 '발송 이력' 탭 → 해당 입찰 건의 메일 목록
  - 관리자: 전체 발송 이력 조회 가능

### 파일 저장 구조
- 초기: 서버 로컬 저장 → 추후 클라우드 스토리지(S3 등) 전환 가능
- DB `proposals` 테이블에 파일 메타 정보(파일명, 경로, 업로드자, 일시, 유형) 저장
- 실제 파일은 입찰 건별 폴더에 저장

```
data/
├── portal.db
└── proposals/
    └── {입찰건 ID}/
        ├── 예시_제안서.pdf          (업로드한 참고 제안서)
        ├── AI_초안_v1.docx         (AI 생성)
        ├── 최종_제안서.pdf          (실무자 업로드)
        └── 기타_첨부파일.xlsx       (관련 문서)
```

### 기능 C: 제안서 관리
- **방법 1 — 직접 업로드**: 실무자가 작성한 제안서 파일 업로드
- **방법 2 — AI 생성 (옵션)**: 예시 제안서 + 공고 내용 → Claude API로 초안 생성
- Claude API 연동 (API 키 필요)
- **입력 포맷**: PDF, DOCX 지원 (hwp는 PDF 변환 후 업로드 안내)
- **AI 처리**: 예시 제안서 텍스트 추출 + 공고 사업개요 → Claude API로 초안 생성
- **출력 포맷**: DOCX(편집용) + PDF(제출용) 다운로드
- 모델 선택: Sonnet 추천 (비용 효율), 품질 부족 시 Opus 전환

### AI 제안서 생성 비용 (참고)

| 모델 | 입력 (100만 토큰) | 출력 (100만 토큰) | 제안서 1건 예상 비용 |
|------|---------------|---------------|----------------|
| Sonnet 4 | $3 | $15 | 약 30~70원 |
| Opus 4 | $15 | $75 | 약 150~350원 |

- 월 20건 기준 Sonnet: 약 1,000~1,500원
- 입력 파일이 크거나 재생성 시 비용 증가

### AI 프롬프트 전략
- **시스템 프롬프트** (고정): 제안서 작성 전문가 역할 정의, 출력 형식/품질 기준
- **사용자 프롬프트** (자동 조합): 공고 정보 + 첨부자료 텍스트 + 예시 제안서 텍스트
- 프롬프트는 별도 파일(`backend/prompts/proposal.md`)로 관리
- 실제 공고/제안서로 테스트하며 반복 개선

### 기능 D: 기관 정보 DB (추후)
- 기존 organizations 테이블 확장 또는 별도 테이블
- 담당자 연락처, 과거 발주 이력, 참고 정보 등 저장

## 5. 개발 단계 (안)

### Phase 0: 기반 작업 ✅
- [x] 로그인/인증 시스템 (ID/PW, 세션 관리)
- [x] 사용자 테이블 + 역할(관리자/실무자)
- [x] 관리자 계정 생성 기능 (설정 페이지)
- [x] 메뉴 구조 변경 (상단 네비게이션 바)
- [x] 대시보드 페이지

### Phase A: 입찰 예정 공고 관리 ✅
- [x] 태그 테이블 설계 + API (notice_tags)
- [x] 검토요청 워크플로우: 실무자→검토요청, 관리자→입찰대상/제외
- [x] 모달에 역할별 태그 버튼 (실무자=검토요청, 관리자=전체)
- [x] 검토요청 공고 리스트 페이지
- [x] 입찰 예정 공고 리스트 페이지
- [x] 제외된 공고 리스트 페이지 (복원 기능)
- [x] 공고 리스트에서 제외 공고 숨김
- [x] 대시보드 카드 5개 + 네비게이션 메뉴 6개

### Phase A.2: 공고수집 출처 관리 ✅

#### 배경
- 기존: "수집 실행" 버튼 하나로 3개 출처 일괄 수집 → 느리고 비직관적
- 변경: 출처별 독립 관리 — 개별 수집, 출처별 키워드, 진행 상태 표시
- 추가: 창조경제혁신센터(CCEI) 4번째 출처 — 통합사이트 JSON API(`/service/business_list.json`) 활용

#### UI 구성 (`source-list.html`)

```
공고수집 출처
┌─────────────────────────────────────────────────────────┐
│ 📌 공통 키워드 (모든 출처에 적용)                          │
│ 교육, 컨설팅, 홍보, ESG, ...           [+추가] [관리]     │
├─────────────────────────────────────────────────────────┤
│                                          [+ 출처 추가]   │
├─────────────────────────────────────────────────────────┤
│ 나라장터                    마지막 수집: 03/29 10:30      │
│ [수집] [████████████ 100%]  583건 수집됨                  │
│ 추가 키워드: 입찰, 용역, ...            [+추가] [관리]     │
├─────────────────────────────────────────────────────────┤
│ K-Startup                  마지막 수집: 03/29 10:28      │
│ [수집]                      262건 수집됨                  │
│ 추가 키워드: (없음)                     [+추가]           │
├─────────────────────────────────────────────────────────┤
│ 중소벤처기업부               마지막 수집: 03/29 10:29      │
│ [수집]                      57건 수집됨                   │
│ 추가 키워드: (없음)                     [+추가]           │
├─────────────────────────────────────────────────────────┤
│ 창조경제혁신센터(CCEI)        마지막 수집: 03/29 10:31      │
│ [수집]                      124건 수집됨                  │
│ 추가 키워드: 창업, 스타트업, ...         [+추가] [관리]     │
└─────────────────────────────────────────────────────────┘
```

#### 출처(Source) 테이블

```sql
CREATE TABLE collect_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,          -- 출처명 (나라장터, K-Startup, 중소벤처기업부, 창조경제혁신센터)
    collector_type TEXT NOT NULL,       -- 수집기 타입 (nara, kstartup, mss_biz, ccei)
    is_active INTEGER DEFAULT 1,       -- 활성/비활성
    last_collected_at TEXT,             -- 마지막 수집 일시
    last_collected_count INTEGER,       -- 마지막 수집 건수
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### 키워드 테이블 변경

```sql
-- 기존 keywords 테이블에 source_id 추가
ALTER TABLE keywords ADD COLUMN source_id INTEGER REFERENCES collect_sources(id);
-- source_id가 NULL → 공통 키워드 (모든 출처에 적용)
-- source_id가 값 있음 → 해당 출처 전용 추가 키워드
```

#### 키워드 로드 로직

```
출처별 수집 시 사용할 키워드
= 공통 키워드 (source_id IS NULL)
+ 해당 출처 전용 키워드 (source_id = {id})
```

#### 출처별 수집 API

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/sources` | GET | 출처 목록 (수집 상태 포함) |
| `/api/sources` | POST | 출처 추가 (관리자) |
| `/api/sources/{id}` | PUT | 출처 수정 (관리자) |
| `/api/sources/{id}` | DELETE | 출처 삭제 (관리자) |
| `/api/sources/{id}/collect` | POST | 개별 출처 수집 실행 (관리자) |
| `/api/keywords/common` | GET | 공통 키워드 목록 |
| `/api/keywords/common` | POST | 공통 키워드 추가 |
| `/api/keywords/{kw_id}` | DELETE | 키워드 삭제 (공통/출처 무관) |
| `/api/sources/{id}/keywords` | GET | 출처 전용 추가 키워드 목록 |
| `/api/sources/{id}/keywords` | POST | 출처에 추가 키워드 등록 |

#### 수집 실행 흐름

```
[수집] 버튼 클릭 (출처별)
  → POST /api/sources/{id}/collect
  → 공통 키워드 + 해당 출처 전용 키워드 로드
  → 수집 실행 (진행률 반환)
  → last_collected_at, last_collected_count 갱신
  → 결과 표시
```

#### 기존 코드 변경 사항
- `collect_all()` → 출처별 `collect_by_source(source_id)` 로 분리
- 각 수집기(nara, kstartup, mss_biz, ccei)는 키워드를 파라미터로 받도록 유지
- 창조경제혁신센터(CCEI) 수집기 신규 작성: `ccei.creativekorea.or.kr/service/business_list.json` POST 호출
- 기존 설정 페이지의 키워드 관리 → 출처 관리 페이지 상단 공통 키워드 영역으로 이동
- 공고 중인 사업 페이지에서 "수집 실행" 버튼 제거
- 네비게이션: 대시보드 옆에 "공고수집 출처" 메뉴 추가

#### 구현 항목
- [x] `collect_sources` 테이블 생성 + 초기 데이터 (나라장터, K-Startup, 중소벤처기업부, 창조경제혁신센터)
- [x] `keywords` 테이블에 `source_id` 컬럼 추가 + 기존 키워드를 공통(source_id=NULL)으로 마이그레이션
- [x] 출처 관리 API (CRUD + 수집 실행)
- [x] 공통 키워드 API + 출처별 추가 키워드 API
- [x] `source-list.html` 페이지 (출처 목록 + 키워드 + 수집 버튼 + 진행바)
- [x] 출처별 수집 실행 + 진행 상태 표시
- [x] 네비게이션 메뉴 추가
- [x] 기존 "수집 실행" 버튼 제거
- [x] 창조경제혁신센터(CCEI) 수집기 구현 (`/service/business_list.json` POST, content+apply_url 포함)
- [x] 대시보드에 출처별 수집 상태 표시
- [x] 나라장터 수집 모드 분리: 빠른수집(daily, 최근2일) / 전체수집(full, 설정기간)
- [x] 출처 필터 동적 로드 (하드코딩 제거 → collect_sources 테이블 참조)

### Phase A.3: 개별 기관 스크래핑 확장 (50개 기관)

#### 배경
- 58개 수집 대상 기관 중 완전 커버는 8개(나라장터5 + K-Startup1 + 중기부2)뿐
- 나머지 50개 기관은 API가 없어 HTML 스크래핑이 필요
- API 없는 기관의 입찰정보를 한 곳에서 보여주는 것이 시스템 경쟁력

#### 부분 커버 — CCEI 입찰공고 (7개)
현재 CCEI 수집기는 `business_list.json`(지원사업공고)만 수집. 아래 기관의 입찰공고(`allim_list.do`)는 별도 스크래핑 필요.

| # | 기관명 | URL |
|---|--------|-----|
| 1 | 경기창조경제혁신센터 | https://ccei.creativekorea.or.kr/gyeonggi/allim/allim_list.do?div_code=2 |
| 2 | 경남창조경제혁신센터 | https://ccei.creativekorea.or.kr/gyeongnam/allim/allim_list.do?div_code=2 |
| 3 | 대구창조경제혁신센터 | https://ccei.creativekorea.or.kr/daegu/allim/allim_list.do?div_code=2 |
| 4 | 부산창조경제혁신센터 | https://ccei.creativekorea.or.kr/busan/allim/allim_list.do?div_code=2 |
| 5 | 세종창조경제혁신센터 | https://ccei.creativekorea.or.kr/sejong/custom/notice_list.do |
| 6 | 인천창조경제혁신센터 | https://ccei.creativekorea.or.kr/incheon/custom/notice_list.do |
| 7 | 충북창조경제혁신센터 | https://ccei.creativekorea.or.kr/chungbuk/custom/notice_list.do |

#### 별도 스크래퍼 필요 (43개)

| # | 기관명 | URL |
|---|--------|-----|
| 8 | 강원관광재단 | https://www.gwto.or.kr/www/selectBbsNttList.do?bbsNo=3&key=23 |
| 9 | 강원정보문화산업진흥원 | https://www.gica.or.kr/Home/H40000/H40200/boardList |
| 10 | 건국대학교 | https://www.konkuk.ac.kr/konkuk/2243/subview.do |
| 11 | 경기대진테크노파크 | https://gdtp.or.kr/board/announcement |
| 12 | 경기도경제과학진흥원 | https://www.gbsa.or.kr/board/bid_info.do |
| 13 | 경기도일자리재단 | https://www.gjf.or.kr/main/pst/list.do?pst_id=nara_market_bid |
| 14 | 경남관광재단 | https://gnto.or.kr/sub04/sub04_01.php |
| 15 | 경남문화예술진흥원 | http://gcaf.or.kr/bbs/board.php?bo_table=sub3_7&me_code=a030 |
| 16 | 경남콘텐츠코리아랩 | https://www.gnckl.or.kr/bbs/board.php?bo_table=notice3 |
| 17 | 경남테크노파크 | http://account.more.co.kr/contract/orderalim.php |
| 18 | 광주정보문화산업진흥원 | https://www.gicon.or.kr/board.es?mid=a10205000000&bid=0020 |
| 19 | 국토연구원 | https://www.krihs.re.kr/board.es?mid=a10602000000&bid=0012 |
| 20 | 대전기업정보포털 | https://www.dips.or.kr/pbanc?nPage=1&mid=a10201000000 |
| 21 | 대전정보문화산업진흥원 | https://www.dicia.or.kr/sub.do?menuIdx=MENU_000000000000100 |
| 22 | 부산창업포탈 | https://busanstartup.kr/biz_sup?mcode=biz02&deleteYn=N&busi_code=820 |
| 23 | 서울테크노파크 | http://seoultp.or.kr/user/nd26539.do |
| 24 | 세종테크노파크 | https://sjtp.or.kr/bbs/board.php?bo_table=notice01 |
| 25 | 소상공인시장진흥공단 | https://semas.or.kr/web/main/index.kmdc |
| 26 | 신용보증기금 | https://alio.go.kr/occasional/bidList.do |
| 27 | 원광대학교 | https://intra.wku.ac.kr/services/contract/cntrc.jsp |
| 28 | 인천테크노파크 | https://www.itp.or.kr/intro.asp?tmid=14 |
| 29 | 전남정보문화산업진흥원 | https://www.jcia.or.kr/cf/information/notice/tender/self.do |
| 30 | 전라북도경제통상진흥원 | http://www.jbba.kr/bbs/board.php?bo_table=sub05_06_02 |
| 31 | 전라북도콘텐츠융합진흥원 | https://www.jcon.or.kr/board/list.php?bbsId=BBSMSTR_000000000003 |
| 32 | 전주정보문화산업진흥원 | https://www.jica.or.kr/2016/inner.php?sMenu=A4000 |
| 33 | 정보통신산업진흥원 | https://www.nipa.kr/home/2-3 |
| 34 | 제주관광공사 | https://ijto.or.kr/korean/Bd/list.php?btable=tender_info |
| 35 | 제주콘텐츠진흥원 | https://ofjeju.kr/communication/notifications.htm |
| 36 | 창업진흥원 | https://www.kised.or.kr/board.es?mid=a10303000000&bid=0005 |
| 37 | 충남문화관광재단 | https://www.cacf.or.kr/site/board/index.php?table_nm=tbl_culture |
| 38 | 충남테크노파크 | https://www.ctp.or.kr/community/bid.do |
| 39 | 충청북도과학기술혁신원 | http://www.cbist.or.kr/home/sub.do?mncd=118 |
| 40 | 충청북도기업진흥원 | http://www.cba.ne.kr/home/sub.php?menukey=140&cate=00000010 |
| 41 | 포항테크노파크 | https://www.ptp.or.kr/main/board/index.do?menu_idx=114&manage_idx=3 |
| 42 | 한국관광공사 | https://touraz.kr/publicTenderList |
| 43 | 한국디자인진흥원 | http://www.kidp.or.kr/?menuno=1012 |
| 44 | 한국발명진흥회 | https://www.kipa.org/ |
| 45 | 한국보육진흥원 | https://www.kcpi.or.kr/kcpi/cyberpr/tender.do |
| 46 | 한국산업기술진흥원 | https://www.kiat.or.kr/front/board/boardContentsListPage.do?board_id=77 |
| 47 | 한국예탁결제원 | https://www.ksd.or.kr/ko/about-ksd/ksd-news/bid-notice |
| 48 | 한국지식재산보호원 | https://www.koipa.re.kr/home/board/brdList.do?menu_cd=000041 |
| 49 | 한국콘텐츠진흥원 | https://www.kocca.kr/kocca/tender/list.do?menuNo=204106&cate=01 |
| 50 | 한국환경산업기술원 | https://www.keiti.re.kr/site/keiti/ex/board/List.do?cbIdx=277 |

#### 구현 전략

**범용 스크래퍼 프레임워크**
- 50개를 개별로 만들지 않고, 설정(config) 기반 범용 스크래퍼를 설계
- 각 사이트의 HTML 구조를 JSON 설정으로 정의 (CSS 셀렉터, URL 패턴)
- `collect_sources` 테이블에 `scraper_config` 컬럼 추가 또는 별도 설정 파일

```json
{
  "list_url": "https://example.or.kr/board/list.php?bo_table=bid",
  "list_selector": "table.board_list tbody tr",
  "title_selector": "td.title a",
  "date_selector": "td.date",
  "link_pattern": "/board/view.php?no={id}",
  "pagination": "?page={page}",
  "encoding": "utf-8"
}
```

**단계적 접근**
- 1단계: 범용 스크래퍼 프레임워크 구현
- 2단계: URL 패턴이 유사한 사이트 그룹별 스크래퍼 설정 작성 (PHP 게시판, board.es 등)
- 3단계: 특수 사이트 개별 대응
- 4단계: CCEI 입찰공고 스크래퍼 (allim_list.do, 7개 센터 통합)

**키워드 매칭 방식**
- 스크래핑 대상은 이미 특정 기관의 입찰공고이므로 키워드 매칭 없이 전체 수집도 가능
- 옵션: 키워드 필터 ON/OFF 설정 (출처별)

#### 구현 항목
- [ ] 범용 스크래퍼 프레임워크 설계 (설정 기반 HTML 파싱)
- [ ] `collect_sources`에 scraper_config 지원 추가
- [ ] CCEI 입찰공고 스크래퍼 (allim_list.do — 7개 센터)
- [ ] PHP 게시판 공통 스크래퍼 (board.php 패턴 — 5~6개 사이트)
- [ ] board.es 공통 스크래퍼 (4~5개 사이트)
- [ ] 기타 개별 사이트 스크래퍼 순차 구현
- [ ] 키워드 매칭 ON/OFF 옵션 (출처별)
- [ ] 스크래핑 에러 알림 (사이트 개편 감지)

### Phase B: 입찰 준비 페이지
- [ ] 입찰 준비 페이지 UI
- [ ] 체크리스트 기능
- [ ] 파일 업로드/관리 (직접 업로드)

### Phase C: AI 제안서 생성
- [ ] Claude API 연동
- [ ] PDF/DOCX 텍스트 추출
- [ ] 제안서 초안 생성 기능
- [ ] DOCX/PDF 출력

### Phase D: 기관 정보 DB
- [ ] 기관 상세 정보 테이블 확장
- [ ] 기관 정보 관리 UI

### Phase E: 스마트 수집 시스템 (자동화 + 효율화)

#### 현재 상태
- 나라장터: PPSSrch 엔드포인트로 전환 완료 → 키워드별 API 호출 방식 (bidNtceNm 파라미터)
- 기존 APScheduler 자동 수집 코드 제거됨 (Phase E에서 재설계)
- 현재는 **수동 수집만 가능** ("수집 실행" 버튼)

#### 개요
PPSSrch 키워드별 호출 방식 기반으로, 자동 수집 + 변경 감지를 설계.
기존 전체 다운로드 방식 대비 API 호출량이 대폭 줄었으므로 자동 수집 부담도 감소.

#### 수집 전략

| 구분 | 동작 | 대상 | 소요시간(예상) | 실행 주기 |
|------|------|------|---------|----------|
| 자동 - 신규 수집 | 최근 1~2일 신규 공고 (키워드별 PPSSrch) | 전체 출처 | ~30초 | 매일 새벽 (스케줄러) |
| 자동 - 변경 감지 | DB에서 `status=ongoing` 공고만 API로 최신 정보 갱신 | 나라장터 | ~1~2분 | 매일 새벽 (신규 수집 후) |
| 수동 - 전체 수집 | 설정된 기간 전체 재수집 (키워드별 PPSSrch) | 전체 출처 | ~1~3분 | 필요시 (수집 실행 버튼) |

#### 변경 감지가 필요한 이유
- 나라장터 공고는 수정/변경공고로 업데이트될 수 있음
  - 마감일 연장, 추정가격 변경, 첨부파일 추가, 변경공고 사유 등
- 진행중(`ongoing`) 공고만 대상이므로 이미 마감된 공고는 건너뜀 → 효율적

#### 구현 항목
- [x] 수집 모드 분리: `mode=daily` (최근2일) / `mode=full` (전체) — Phase A.2에서 구현
- [ ] 나라장터 변경 감지: DB의 ongoing 공고 bid_no 목록 → API로 최신 정보 조회 → 변경분만 UPDATE
- [x] K-Startup/중기부/CCEI도 동일 패턴 적용 — Phase A.2에서 구현
- [ ] 스케줄러 구현 (APScheduler 재도입 또는 OS cron)
- [ ] 수집 이력 테이블: 수집 일시, 소요시간, 신규/업데이트/변경 건수 기록
- [ ] 대시보드에 "마지막 자동 수집" 시간 + 스케줄 표시
- [ ] 설정 페이지에서 자동 수집 주기 설정 (관리자)

#### 사용자 업무 가이드

**일반 사용자 (실무자)**
- 별도 조작 필요 없음 — 매일 출근하면 새 공고가 자동으로 올라와 있음
- 변경된 공고(마감연장, 가격변경 등)도 자동 반영
- 공고 목록 확인 → 상세 보기 → 검토요청 → 일상 업무 시작

**관리자**
- 평소: 자동 수집에 의존, 별도 조작 불필요
- 급할 때: "수집 실행" 버튼 → 전체 재수집 (최신 공고 즉시 반영)
- 수집 상태 확인: 대시보드에서 "마지막 수집 시간" 확인 가능
- 키워드/기관 변경 후: "수집 실행" 버튼으로 즉시 반영 권장

## 6. 기술 스택 추가 (예상)

```
인증:         JWT 또는 세션 기반 (FastAPI 내장)
비밀번호:     bcrypt 해싱
AI:          Claude API (Anthropic SDK)
파일 파싱:    PyPDF2/pdfplumber (PDF), python-docx (DOCX)
파일 생성:    python-docx (DOCX) → docx2pdf (PDF 변환)
```

## 7. 미정/논의 필요 사항

- [ ] Phase B 입찰 준비 페이지 상세 범위
- [ ] Claude API 모델 선택 (Sonnet vs Opus)
- [ ] AI 제안서 생성 시 프롬프트 전략
- [ ] 기관 정보 DB에 어떤 정보를 저장할지
- [ ] 입찰 이력/통계 기능 범위
- [ ] 프론트엔드 프레임워크 변경 여부 (Vanilla JS 유지 vs React 전환)

## 8. 롤백 방법 (기존 Phase 3 상태로 복원)

Plan 2 확장 작업이 실패하거나 중단할 경우, 아래 방법으로 기존 상태로 복원 가능.

**백업 브랜치:** `phase3-backup` (커밋 `4f7a96e`)

```bash
# 방법 1: master를 phase3-backup 시점으로 되돌리기
git reset --hard phase3-backup
git push --force origin master

# 방법 2: 새 브랜치에서 기존 상태 확인만
git checkout phase3-backup
```

**기존 계획 문서:** `work_log/plan.md` (Phase 1~5 원본 계획)
**기존 작업 로그:** `work_log/log_phase1.md`, `log_phase2.md`, `log_phase3.md`
