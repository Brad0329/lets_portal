# Phase C: AI 공고 분석 — 작업 로그

## C-1: 문서 파싱 모듈 (2026-04-16)

### 결정사항

1. **pdfplumber 선택 (vs PyPDF2)** — 표(table) 추출 내장 지원. PyPDF2는 텍스트만 추출 가능하고 표 파싱이 없음.
2. **HWPX는 lxml으로 직접 파싱** — HWPX는 ZIP 안에 `Contents/sectionN.xml` 파일이 있는 구조. 별도 라이브러리 불필요, lxml(기존 설치됨)만으로 충분.
3. **HWP(구형)는 pywin32 COM 자동화** — 한/글 프로그램이 설치된 Windows에서만 동작. 미설치 환경에서는 에러 메시지 반환 후 스킵. 납품 환경(사내 PC)에는 한/글이 있을 수 있으므로 시도는 해둠.
4. **표 → 마크다운 변환 공통화** — `_table_to_markdown()` 함수 하나로 PDF/HWPX/DOCX 표를 모두 처리.

### 외부 제약

- **중기부(mss.go.kr) SSL 다운로드 실패** — 테스트 시 ConnectionResetError 발생. 실 운영에서는 세션/쿠키 필요할 수 있음 (B-1에서 이미 대응한 패턴 참고).
- **HWP COM 자동화 클래스 문자열** — `HWPFrame.HwpObject`로 Dispatch. 한/글이 미설치된 환경에서는 "잘못된 클래스 문자열" 에러 발생 (정상 동작).

### 테스트 결과

| 포맷 | 테스트 파일 | 결과 | 비고 |
|------|-----------|------|------|
| PDF | 나라장터 제안요청서 (9페이지, 313KB) | 성공 — 9,397자 추출 | 표 포함 정상 |
| HWPX | K-Startup 브랜드 공고 (35KB) | 성공 — 1,097자 추출 | |
| DOCX | 테스트 생성 파일 (표 포함) | 성공 — 표 마크다운 변환 정상 | |
| HWP | 나라장터 제안요청서 (228KB) | 실패 — 한/글 미설치 | 설계대로 스킵 |

### 신규 의존성

- `pdfplumber` — PDF 텍스트+표 추출
- `python-docx` — DOCX 파싱
- `lxml` — 기존 설치됨, HWPX XML 파싱에 활용

## C-2: 프로필 항목 확정 + UI (2026-04-16)

### 결정사항

1. **프로필 항목은 실제 공고 파싱 결과 기반 확정** — 나라장터 PDF 12건 파싱 후 평가기준 키워드 빈도 분석.
   - 참가자격(83%), 배점(75%), 수행능력(58%), 사업이해도(58%), 수행방법(50%) 등이 반복 출현.
2. **유연한 key-value 구조 (`company_profile` 테이블)** — 고정 스키마 대신 category + field_key 방식. 항목 추가/삭제 자유로움.
3. **JSON 배열 필드** — 사업실적(`project_history`), 인력현황(`staff_list`)은 `field_type=json`으로 배열 저장. UI에서 테이블+행 추가/삭제.
4. **API는 `routers/ai.py`에 통합** — 프로필/분석/크레딧 모두 `/api/ai/` 하위로.

### 실패한 접근

- **`_table_to_markdown()` None 셀 에러** — pdfplumber가 병합 셀 등에서 None 반환. `(cell or "")` 처리 추가로 해결. 초기 12건 중 5건 실패 → 수정 후 전건 성공.

### 프로필 항목 (16개 필드, 6개 카테고리)

| 카테고리 | 항목 | field_type |
|---------|------|-----------|
| 기본정보 | 회사명, 대표자, 설립연도, 업종, 소재지, 중소기업 해당 | text/number/boolean |
| 사업실적 | 수행실적 (사업명/발주처/금액/기간/역할) | json |
| 인력현황 | 투입인력 (이름/자격증/경력/전문분야) | json |
| 재무상태 | 연매출, 신용등급, 자본금 | text |
| 기술력 | 보유기술/방법론, 특허/인증 | textarea |
| 참여제한 | 지역제한, 컨소시엄, 하도급 | text |

## C-3: AI 분석 엔진 (2026-04-16)

### 결정사항

1. **`.env` 키 이름은 `CLAUDE_API_KEY` 사용** — 설계 문서의 `ANTHROPIC_API_KEY`가 아닌 사용자가 이미 저장한 이름 존중. `analyzer.py`에서 양쪽 다 체크.
2. **PDF → Claude base64 직접 전달 우선** — PDF는 텍스트 추출 대신 base64로 직접 보내는 게 품질 최상. 30MB 이하일 때만 직접 전달, 초과 시 텍스트 추출 후 전송.
3. **간이 모드는 Sonnet만 사용** — 첨부 없는 공고는 파싱 단계 스킵, Sonnet 1회로 상/중/하 판단.
4. **프롬프트 파일 기반** — `backend/prompts/` 디렉토리에 3개 `.md` 파일. 코드 수정 없이 프롬프트 튜닝 가능.

### 파일 구조

```
backend/ai/
├── __init__.py
├── base.py          — BaseAIClient + AIResponse 데이터클래스
├── claude_client.py — analyze_document, analyze_document_pdf, match_profile
├── analyzer.py      — run_analysis() 오케스트레이터
└── cost.py          — calculate_cost() 순수 함수

backend/prompts/
├── parse_document.md  — 평가기준/자격요건/일정 구조화 추출
├── match_profile.md   — 항목별 점수/근거/보완 + 종합 의견
└── match_simple.md    — 적합도 상/중/하 판단
```

## C-4: 분석 결과 저장 + UI (2026-04-16)

### 결정사항

1. **ai_analyses 테이블** — notice_id + analysis_seq UNIQUE로 차수 관리. full/simple 모드 구분.
2. **ai_credits 테이블** — 충전/차감 원장 방식 (balance 컬럼으로 잔액 즉시 확인).
3. **ai_config 테이블** — 모델/환율 설정 3개 (model_parsing, model_matching, exchange_rate).
4. **bid_notices 확장** — ai_status, ai_match_rate, ai_recommendation, attachment_dir 4개 컬럼 추가.
5. **검토요청 리스트에 AI 열 추가** — 미분석: [분석] 버튼, 분석완료: 매칭률% (색상 코딩), 클릭 시 상세 모달.

### 실제 분석 테스트 결과

| 항목 | 값 |
|------|-----|
| 공고 | 2026 지역애니메이션 콘텐츠 제작지원사업 (제주콘텐츠진흥원) |
| 모드 | full (PDF 첨부 있음) |
| 파싱 모델 | Haiku — 평가기준 4항목 추출 (기획력 30, 사업성 20, 제작역량 30, 예산적정성 20) |
| 매칭 모델 | Sonnet — 매칭률 18% (비추천) |
| 비용 | 98.7원 (설계 예상 ~100원과 일치) |
| 소요 시간 | ~20초 (다운로드 + Haiku + Sonnet) |
| 판단 정확성 | 정확 — 교육컨설팅 회사 vs 애니메이션 제작 공고 |

### 첨부파일 다운로드 전략 변경 (C-4 이후 개선)

**변경 전:** 모든 PDF/HWPX/DOCX/HWP 파일을 전부 다운로드 → 토큰 낭비
**변경 후:** 3단계 선별 전략

1. **키워드 매칭 우선** — 파일명에 `제안요청`, `과업지시`, `사업안내`, `평가기준` 등 16개 키워드 포함 시 해당 파일만 다운로드
2. **폴백** — 키워드 매칭 파일이 없으면 전체 다운로드
3. **ZIP 처리** — ZIP 다운로드 → 압축 해제 → 내부 파일에 같은 키워드 로직 적용

**이유:** 공고 첨부파일 7~8개 중 분석에 필요한 건 제안요청서/과업지시서 1~2개. 나머지(서식, 계약서, 참고자료)는 토큰만 소비.

### 신규 의존성

- `anthropic` — Claude API SDK
