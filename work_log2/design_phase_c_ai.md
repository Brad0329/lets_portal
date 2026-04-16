# Phase C: AI 공고 분석 — 설계 문서

## 1. 목표

검토요청된 공고의 첨부파일(제안요청서, 사업안내서 등)을 파싱하여 평가기준/자격요건 등 핵심 정보를 추출하고, 회사 프로필과 비교하여 **입찰 적합도 매칭 점수**를 산출한다.

---

## 2. 전체 흐름

```
검토요청 리스트
  └─ [AI 분석] 버튼 클릭
       │
       ├─ 1) 첨부파일 다운로드 → data/attachments/{notice_id}/
       │
       ├─ 2) 문서 파싱 (Haiku) → 평가기준/자격요건/배점 구조화 추출
       │      PDF: Claude API 직접 전달 (base64)
       │      HWPX: hwpxskill → 마크다운 텍스트 → Haiku
       │      DOCX: python-docx → 텍스트 → Haiku
       │      HWP(구형): 변환 시도 → 실패 시 스킵
       │
       ├─ 3) 매칭 분석 (Sonnet) → 프로필 vs 평가기준 → 항목별 점수/근거/보완
       │
       └─ 4) 결과 DB 저장 + 화면 표시
              비용 차감 (크레딧)

[프로필 수정 후 재분석] 버튼
  └─ 팝업: 프로필 수정 → 재분석 실행 → 2차 분석 결과 저장 (변경 프로필 비고 표시)
```

---

## 3. 문서 파싱 모듈 (독립 패키지 구조)

### 3-1. 설계 원칙

- **이 프로젝트 안에서 먼저 개발** (`backend/utils/file_parser.py`)
- 안정화 후 **독립 패키지로 분리** → 외부 프로젝트(bidwatch 등)에서 재사용
- 인터페이스를 처음부터 독립 패키지 수준으로 설계

### 3-2. 인터페이스

```python
# backend/utils/file_parser.py

def extract_text(file_path: str) -> ParseResult:
    """확장자 판별 → 적절한 파서 호출 → 결과 반환"""

@dataclass
class ParseResult:
    text: str           # 추출된 텍스트 (마크다운)
    format: str         # 원본 포맷 (pdf/hwpx/docx/hwp)
    page_count: int     # 페이지 수 (알 수 있는 경우)
    raw_bytes: bytes    # 원본 바이너리 (PDF→Claude 직접 전달용)
    success: bool       # 파싱 성공 여부
    error: str          # 실패 시 에러 메시지
```

### 3-3. 포맷별 처리

| 포맷 | 파서 | AI 전달 방식 | 의존성 |
|------|------|------------|--------|
| PDF | pdfplumber (텍스트 추출) | base64로 Claude에 직접 전달 (최상 품질) | pdfplumber |
| HWPX | hwpxskill (XML 직접 파싱) | 마크다운 텍스트로 프롬프트 삽입 | lxml |
| DOCX | python-docx | 텍스트로 프롬프트 삽입 | python-docx |
| HWP(구형) | pywin32 → PDF 변환 시도 | 변환 성공 시 PDF 경로, 실패 시 스킵 | pywin32 (Windows만) |

### 3-4. 독립 패키지 분리 시 구조 (향후)

```
lets_doc_parser/
├── __init__.py          # from .parser import extract_text, ParseResult
├── parser.py            # extract_text() 진입점 + ParseResult
├── pdf_parser.py        # extract_pdf()
├── hwpx_parser.py       # extract_hwpx() — hwpxskill 활용
├── hwp_parser.py        # extract_hwp() — 변환 시도
├── docx_parser.py       # extract_docx()
└── pyproject.toml
```

---

## 4. AI 분석 엔진 (다중 모델, 교체 가능 구조)

### 4-1. 설계 원칙

- **모델 교체/추가 가능한 구조** — Claude 외 다른 AI(GPT, Gemini 등) 추가 대비
- 문서 파싱과 매칭 분석에 **각각 다른 모델** 지정 가능
- bidwatch 이식 시 설정만 바꾸면 동작

### 4-2. 추상 인터페이스

```python
# backend/ai/base.py

class BaseAIClient:
    """AI 클라이언트 추상 인터페이스"""
    
    def analyze_document(self, document_text: str, prompt: str) -> dict:
        """문서 파싱 — 평가기준/자격요건 구조화 추출"""
        raise NotImplementedError
    
    def analyze_document_pdf(self, pdf_bytes: bytes, prompt: str) -> dict:
        """PDF 직접 전달 분석 (지원 모델만)"""
        raise NotImplementedError
    
    def match_profile(self, criteria: dict, profile: dict, prompt: str) -> MatchResult:
        """매칭 분석 — 프로필 vs 평가기준 → 점수"""
        raise NotImplementedError


# backend/ai/claude_client.py

class ClaudeClient(BaseAIClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        ...

# 향후 확장 예시
# backend/ai/openai_client.py
# class OpenAIClient(BaseAIClient): ...
```

### 4-3. 모델 배정

| 단계 | 기본 모델 | 설정 키 | 비용 |
|------|----------|---------|------|
| 문서 파싱 | Haiku 4.5 | `ai_model_parsing` | $1/$5 per 1M |
| 매칭 분석 | Sonnet 4.6 | `ai_model_matching` | $3/$15 per 1M |

설정 테이블 또는 config에서 모델 변경 가능.

### 4-4. 프롬프트 관리

```
backend/prompts/
├── parse_document.md      # 문서 파싱용 시스템 프롬프트
├── match_profile.md       # 매칭 분석용 시스템 프롬프트
└── match_simple.md        # 간이 모드 (평가기준 없을 때)
```

- 프롬프트를 파일로 분리 → 코드 수정 없이 프롬프트 튜닝 가능
- bidwatch 이식 시 프롬프트만 교체 가능

---

## 5. 회사 프로필

### 5-1. 설계 순서

```
1단계: 문서 파싱 모듈 개발
  ↓
2단계: 실제 공고 첨부파일 파싱 → 평가기준 패턴 분석
  ↓
3단계: 패턴 분석 결과로 프로필 항목 확정
  ↓
4단계: 프로필 입력 UI + DB 설계
```

프로필 필드는 2단계에서 실제 공고를 분석한 후 확정.
아래는 공공입찰 평가기준에서 예상되는 **후보 항목**:

### 5-2. 프로필 후보 항목 (2단계 분석 후 확정)

| 카테고리 | 항목 예시 |
|---------|---------|
| **기본 정보** | 회사명, 설립연도, 업종, 대표자, 소재지 |
| **사업 실적** | 유사사업 수행 이력 (건명, 발주처, 금액, 기간), 수상/인증 이력 |
| **인력 현황** | 기술인력 보유 (자격증, 경력 연수), PM 경력, 전문분야별 인력 수 |
| **재무 상태** | 연매출, 신용등급, 자본금 |
| **기술력** | 보유 기술/특허, 전문 분야, 방법론 |
| **참여 제한** | 지역 제한 가능 여부, 중소기업 해당 여부, 컨소시엄 가능 여부 |

### 5-3. DB 테이블

```sql
CREATE TABLE company_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,       -- 카테고리 (기본정보, 사업실적, ...)
    field_key TEXT NOT NULL,      -- 항목 키
    field_label TEXT NOT NULL,    -- 표시명
    field_value TEXT DEFAULT '',  -- 입력값
    field_type TEXT DEFAULT 'text', -- text, textarea, number, date, json
    sort_order INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

- 고정 스키마 대신 **유연한 key-value 구조** → 항목 추가/삭제가 자유로움
- `field_type=json`으로 사업실적 같은 배열 데이터도 저장 가능
- bidwatch 이식 시 동일 구조 사용

### 5-4. 프로필 수정 팝업 (재분석용)

- 분석 결과 화면에서 [프로필 수정 후 재분석] 버튼
- 팝업: 현재 프로필 표시 → 수정 → [재분석] 클릭
- 재분석 시 **변경된 항목을 비고에 기록** + 분석 차수(1차/2차/...) 증가
- 재분석 완료 후 **"프로필에 반영하시겠습니까?"** 확인 → 승인 시 원본 프로필 업데이트, 거부 시 해당 분석에만 적용

---

## 6. 비용 관리 (크레딧 시스템)

### 6-1. 충전/차감 방식

```sql
CREATE TABLE ai_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,          -- 'charge' 또는 'usage'
    amount REAL NOT NULL,        -- 충전: +금액(원), 사용: -금액(원)
    balance REAL NOT NULL,       -- 거래 후 잔액
    description TEXT,            -- '관리자 충전 10,000원' / 'AI분석: 공고 #123 (파싱+매칭)'
    notice_id INTEGER,           -- usage인 경우 관련 공고 ID
    analysis_id INTEGER,         -- usage인 경우 관련 분석 ID
    model_used TEXT,             -- 사용 모델 (haiku-4.5, sonnet-4.6)
    tokens_input INTEGER,        -- 입력 토큰 수
    tokens_output INTEGER,       -- 출력 토큰 수
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 6-2. 흐름

```
설정 > AI 비용 관리
  ├── 현재 잔액: 8,500원
  ├── [충전] 버튼 → 금액 입력 → 잔액 증가
  ├── 사용 이력 테이블 (일시, 공고명, 모델, 토큰, 비용)
  └── 월별 사용 요약

AI 분석 실행 시:
  1. 잔액 확인 → 부족 시 "잔액 부족" 알림
  2. 분석 실행
  3. 실제 사용 토큰 기반 비용 산출 → 차감
```

### 6-3. 비용 산출

```python
def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """토큰 수 → 원화 비용 (환율 적용)"""
    PRICING = {
        "haiku-4.5":  {"input": 1.00, "output": 5.00},   # per 1M tokens (USD)
        "sonnet-4.6": {"input": 3.00, "output": 15.00},
    }
    # ... USD 계산 → KRW 변환 (설정에서 환율 관리)
```

- 환율은 설정에서 관리 (기본값 1,400원)
- 모델별 단가도 설정 테이블에 저장 → 가격 변동 시 코드 수정 없이 대응

---

## 7. 분석 결과 저장 (차수 관리)

### 7-1. DB 테이블

```sql
CREATE TABLE ai_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL REFERENCES bid_notices(id),
    analysis_seq INTEGER NOT NULL DEFAULT 1,  -- 분석 차수 (1차, 2차, ...)
    
    -- 파싱 결과
    parsed_criteria TEXT,         -- JSON: 추출된 평가기준/배점
    parsed_requirements TEXT,     -- JSON: 자격요건
    parsed_summary TEXT,          -- 공고 요약 (텍스트)
    
    -- 매칭 결과
    total_score REAL,             -- 총 매칭 점수
    total_max_score REAL,         -- 총 배점
    match_rate REAL,              -- 매칭률 (%)
    match_detail TEXT,            -- JSON: 항목별 점수/근거/보완사항
    match_recommendation TEXT,    -- AI 종합 의견 (입찰 추천/비추천/조건부)
    
    -- 간이 모드 (평가기준 없을 때)
    simple_grade TEXT,            -- 상/중/하
    simple_reason TEXT,           -- 판단 근거
    
    -- 메타
    profile_snapshot TEXT,        -- JSON: 분석 당시 프로필 스냅샷
    profile_changes TEXT,         -- JSON: 이전 차수 대비 변경사항 (2차부터)
    model_parsing TEXT,           -- 파싱에 사용한 모델
    model_matching TEXT,          -- 매칭에 사용한 모델
    cost_krw REAL,               -- 이 분석의 비용 (원)
    
    created_at TEXT DEFAULT (datetime('now','localtime')),
    
    UNIQUE(notice_id, analysis_seq)
);
```

### 7-2. 분석 차수 흐름

```
[AI 분석] 버튼 (1차)
  → ai_analyses: notice_id=123, analysis_seq=1, profile_snapshot={현재 프로필}
  → 결과 표시

[프로필 수정 후 재분석] 버튼 (2차)
  → 팝업: 프로필 수정
  → ai_analyses: notice_id=123, analysis_seq=2, 
    profile_snapshot={수정된 프로필}, 
    profile_changes={"사업실적": "3건→5건", "기술인력": "PM 1명 추가"}
  → 1차/2차 결과 비교 표시
```

### 7-3. UI 표시

```
공고: [ESG 컨설팅 용역 입찰]
────────────────────────────────
📊 1차 분석 (2026-04-16)          매칭률: 68%
| 항목          | 배점 | 예상 | 근거           | 보완          |
|--------------|-----|-----|---------------|--------------|
| 유사사업 실적   | 30  | 24  | ESG 3건 보유   | 교육 실적 추가  |
| 투입인력       | 25  | 15  | PM 충족        | 기술사 미보유   |
| ...          |     |     |               |              |
AI 의견: 조건부 추천 — 기술사 확보 시 경쟁력 있음

────────────────────────────────
📊 2차 분석 (2026-04-16)          매칭률: 82% ▲14%
변경사항: 투입인력 — "기술사 1명 추가"
| 항목          | 배점 | 예상 | 근거           | 보완          |
|--------------|-----|-----|---------------|--------------|
| 유사사업 실적   | 30  | 24  | (동일)         |              |
| 투입인력       | 25  | 22  | 기술사 확보     | -            |
| ...          |     |     |               |              |
AI 의견: 추천 — 상위 경쟁 가능

                              [프로필 수정 후 재분석]
```

---

## 8. 간이 모드 (평가기준 미첨부 공고)

첨부파일이 없거나 평가기준이 추출되지 않은 공고에 대해:

- 공고 제목/내용/자격요건/예산 등 **DB에 있는 정보만으로** 판단
- 매칭률(%) 대신 **적합도 등급**: 상/중/하
- 판단 근거 텍스트 제공
- 비용: 매칭 분석 1회만 (파싱 단계 스킵) → 약 60원

---

## 9. 첨부파일 다운로드/저장

### 9-1. 실행 시점

- [AI 분석] 버튼 클릭 시 → 첨부파일 다운로드 → 파싱 → 분석
- 이미 다운로드된 파일은 재사용 (metadata.json 확인)

### 9-2. 저장 구조

```
data/attachments/{notice_id}/
├── 제안요청서.pdf
├── 사업안내서.hwpx
├── 사업안내서.md          ← HWPX에서 텍스트 추출본
├── 평가기준.docx
├── 평가기준.md            ← DOCX에서 텍스트 추출본
└── metadata.json          ← 파일 목록, 처리 상태, 일시
```

### 9-3. metadata.json 예시

```json
{
  "notice_id": 123,
  "downloaded_at": "2026-04-16 10:30:00",
  "files": [
    {
      "filename": "제안요청서.pdf",
      "original_url": "https://...",
      "size_bytes": 1048576,
      "format": "pdf",
      "parsed": true,
      "parsed_at": "2026-04-16 10:30:05"
    },
    {
      "filename": "사업안내서.hwpx",
      "original_url": "https://...",
      "size_bytes": 524288,
      "format": "hwpx",
      "parsed": true,
      "extracted_md": "사업안내서.md",
      "parsed_at": "2026-04-16 10:30:08"
    }
  ]
}
```

---

## 10. API 키 관리

- `.env` 파일에 `ANTHROPIC_API_KEY` 저장
- `config.py`에서 로드: `ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")`
- 키 미설정 시 AI 분석 버튼 비활성화 + "API 키를 설정해주세요" 안내

---

## 11. API 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/ai/analyze/{notice_id}` | POST | AI 분석 실행 (다운로드→파싱→매칭) |
| `/api/ai/analyses/{notice_id}` | GET | 공고의 분석 결과 목록 (전체 차수) |
| `/api/ai/analyses/{analysis_id}` | GET | 분석 결과 상세 |
| `/api/ai/profile` | GET | 회사 프로필 조회 |
| `/api/ai/profile` | PUT | 회사 프로필 수정 |
| `/api/ai/credits` | GET | 잔액 + 사용 이력 |
| `/api/ai/credits/charge` | POST | 크레딧 충전 (관리자) |
| `/api/ai/config` | GET | AI 설정 (모델, 환율 등) |
| `/api/ai/config` | PUT | AI 설정 변경 (관리자) |

---

## 12. 파일 구조 (신규)

```
backend/
├── ai/
│   ├── __init__.py
│   ├── base.py              ← BaseAIClient 추상 인터페이스
│   ├── claude_client.py     ← Claude API 구현 (Haiku/Sonnet)
│   ├── analyzer.py          ← 분석 오케스트레이터 (다운로드→파싱→매칭→저장)
│   └── cost.py              ← 비용 산출/차감 로직
├── utils/
│   └── file_parser.py       ← 문서 파싱 모듈 (향후 독립 패키지 분리)
├── prompts/
│   ├── parse_document.md    ← 문서 파싱 프롬프트
│   ├── match_profile.md     ← 매칭 분석 프롬프트
│   └── match_simple.md      ← 간이 모드 프롬프트
└── routers/
    └── ai.py                ← AI 관련 API 라우터
```

---

## 13. bidwatch 이식 고려사항

### 13-1. 분리 가능한 모듈

| 모듈 | 이식 방법 | 의존성 |
|------|----------|--------|
| `utils/file_parser.py` | 독립 패키지 (`lets_doc_parser`) | lxml, pdfplumber, python-docx |
| `ai/base.py` + `claude_client.py` | 독립 패키지 (`lets_ai_client`) | anthropic SDK |
| `prompts/*.md` | 파일 복사 | 없음 |
| `ai/analyzer.py` | 프로젝트별 커스터마이징 | file_parser + ai_client |

### 13-2. 인터페이스 규약

bidwatch 이식 시 변경되는 것:
- DB 스키마 (PostgreSQL 등으로 변경 가능)
- 프론트엔드 (React 등)
- 인증 체계

변경되지 않는 것:
- `extract_text(file_path) → ParseResult` 인터페이스
- `BaseAIClient.analyze_document()` / `match_profile()` 인터페이스
- 프롬프트 파일 구조
- 크레딧 산출 로직 (`calculate_cost()`)

### 13-3. 설계 원칙

- AI 클라이언트는 **DB를 직접 접근하지 않음** → analyzer.py가 중간 계층
- 파일 파서는 **파일 경로만 받고 결과만 반환** → 프레임워크 무관
- 프롬프트는 **파일 기반** → 코드 수정 없이 교체
- 비용 산출은 **순수 함수** → DB 없이 단독 테스트 가능

---

## 14. 구현 순서

```
C-1: 문서 파싱 모듈
  - [ ] utils/file_parser.py (ParseResult, extract_text 진입점)
  - [ ] PDF 파서 (pdfplumber)
  - [ ] HWPX 파서 (hwpxskill 활용)
  - [ ] DOCX 파서 (python-docx)
  - [ ] HWP 변환 시도 (pywin32, 실패 시 스킵)
  - [ ] 실제 공고 첨부파일로 테스트

C-2: 실제 공고 분석 → 프로필 항목 확정
  - [ ] 공고 10~20건 첨부파일 파싱
  - [ ] AI로 평가기준 패턴 분석 (어떤 항목이 반복되는지)
  - [ ] 프로필 입력 항목 확정
  - [ ] company_profile 테이블 생성 + 설정 UI

C-3: AI 분석 엔진
  - [ ] ai/base.py (BaseAIClient 인터페이스)
  - [ ] ai/claude_client.py (Haiku/Sonnet 구현)
  - [ ] prompts/*.md (파싱/매칭/간이 프롬프트)
  - [ ] ai/analyzer.py (오케스트레이터)
  - [ ] ai/cost.py (비용 산출)

C-4: 분석 결과 저장 + UI
  - [ ] ai_analyses 테이블 생성
  - [ ] ai_credits 테이블 생성
  - [ ] routers/ai.py (API 엔드포인트)
  - [ ] 검토요청 리스트에 [AI 분석] 버튼
  - [ ] 분석 결과 표시 UI (차수별 비교)
  - [ ] [프로필 수정 후 재분석] 팝업
  - [ ] 크레딧 충전/사용이력 UI (설정 페이지)

C-5: 안정화
  - [ ] 다양한 공고 유형으로 테스트
  - [ ] 프롬프트 튜닝
  - [ ] 에러 처리 (다운로드 실패, 파싱 실패, API 실패)
  - [ ] bidwatch 이식 대비 모듈 분리 검증
```

---

## 15. 비용 참고

### 1건당 예상 비용 (Haiku + Sonnet 조합)

| 단계 | 모델 | 입력 토큰 | 출력 토큰 | 비용 (USD) | 비용 (KRW) |
|------|------|----------|----------|-----------|-----------|
| 문서 파싱 | Haiku 4.5 | ~15,000 | ~2,000 | $0.025 | ~35원 |
| 매칭 분석 | Sonnet 4.6 | ~5,000 | ~2,000 | $0.045 | ~63원 |
| **합계** | | | | **~$0.07** | **~100원** |

- 첨부파일 대용량/다수: 200~500원
- 간이 모드 (파싱 스킵): ~60원
- 재분석: 매칭만 재실행 → ~60원

### 월간 예상

| 월 분석 건수 | 비용 |
|------------|------|
| 10건 | 1,000~5,000원 |
| 30건 | 3,000~15,000원 |
| 50건 | 5,000~25,000원 |

---

## 16. 프롬프트 설계 (초안)

### 16-1. 문서 파싱 프롬프트 (`prompts/parse_document.md`)

```markdown
당신은 공공입찰 공고 문서를 분석하는 전문가입니다.

아래 문서에서 다음 정보를 구조화하여 JSON으로 추출하세요.
추출할 수 없는 항목은 null로 표시하세요.

## 추출 항목

1. **사업 개요** (business_summary)
   - 사업명, 사업 목적, 사업 기간, 사업 예산

2. **평가 기준** (evaluation_criteria) — 배열
   - 평가 항목명, 배점, 세부 기준 (있는 경우)

3. **자격 요건** (requirements) — 배열
   - 필수 자격, 우대 사항, 제한 사항

4. **제출 서류** (required_documents) — 배열
   - 서류명, 필수/선택

5. **일정** (schedule)
   - 공고일, 제안서 마감일, 발표일, 사업 시작일

6. **기타 핵심 정보** (additional)
   - 컨소시엄 가능 여부, 하도급 제한, 지역 제한 등

## 응답 형식
반드시 아래 JSON 구조로 응답하세요. 설명 텍스트 없이 JSON만 출력합니다.

{
  "business_summary": {
    "name": "", "purpose": "", "period": "", "budget": ""
  },
  "evaluation_criteria": [
    {"item": "", "score": 0, "detail": ""}
  ],
  "requirements": [
    {"type": "필수|우대|제한", "description": ""}
  ],
  "required_documents": [
    {"name": "", "mandatory": true}
  ],
  "schedule": {
    "announcement_date": "", "deadline": "", "result_date": "", "start_date": ""
  },
  "additional": {
    "consortium": null, "subcontract_limit": null, "region_limit": null
  }
}
```

### 16-2. 매칭 분석 프롬프트 (`prompts/match_profile.md`)

```markdown
당신은 입찰 경쟁력 분석 전문가입니다.

아래 [평가기준]과 [회사 프로필]을 비교하여,
각 평가 항목별로 우리 회사가 받을 수 있는 예상 점수와 근거를 분석하세요.

## 분석 규칙
- 각 항목의 배점 대비 현실적인 예상 점수를 산출
- 근거는 프로필의 구체적 데이터를 인용하여 작성
- 보완사항은 점수를 높이기 위한 실행 가능한 조언
- 종합 의견은 "추천" / "조건부 추천" / "비추천" 중 하나 + 이유

## 평가기준
{criteria_json}

## 회사 프로필
{profile_json}

## 응답 형식
반드시 아래 JSON 구조로 응답하세요.

{
  "items": [
    {
      "item": "평가항목명",
      "max_score": 30,
      "expected_score": 24,
      "rationale": "근거 설명",
      "improvement": "보완사항 (없으면 빈 문자열)"
    }
  ],
  "total_max_score": 100,
  "total_expected_score": 68,
  "match_rate": 68.0,
  "recommendation": "추천|조건부 추천|비추천",
  "summary": "종합 의견 텍스트"
}
```

### 16-3. 간이 모드 프롬프트 (`prompts/match_simple.md`)

```markdown
당신은 입찰 적합도 판단 전문가입니다.

아래 [공고 정보]와 [회사 프로필]을 비교하여,
이 공고가 우리 회사에 적합한지 판단하세요.

평가기준이 별도로 제공되지 않았으므로, 공고 내용에서 유추되는 요구사항과
회사의 역량을 대략적으로 비교합니다.

## 공고 정보
- 제목: {title}
- 기관: {organization}
- 예산: {budget}
- 내용: {content}
- 자격요건: {requirements}

## 회사 프로필
{profile_json}

## 응답 형식
{
  "grade": "상|중|하",
  "reason": "판단 근거 (3~5문장)",
  "strengths": ["강점1", "강점2"],
  "weaknesses": ["약점1", "약점2"],
  "recommendation": "추천|조건부 추천|비추천"
}
```

---

## 17. UI 화면 설계

### 17-1. 검토요청 리스트 — [AI 분석] 버튼 추가

```
검토요청 공고리스트
┌──────────────────────────────────────────────────────────────┐
│ 출처    │ 제목              │ 기관      │ 마감   │ 상태  │ AI  │
├──────────────────────────────────────────────────────────────┤
│ 나라장터 │ ESG 컨설팅 용역    │ 환경부    │ 04-30 │ 진행중│ [분석] │
│  📎 제안요청서.pdf, 사업안내서.hwpx                               │
│  💬 검토사유: ESG 관련 우리 전문분야...  [입찰예정] [제외]          │
├──────────────────────────────────────────────────────────────┤
│ K-Startup│ 스타트업 교육      │ 창업진흥원 │ 05-15 │ 진행중│ [분석] │
│  📎 첨부파일 없음                                                 │
│  💬 교육 컨설팅 적합 여부 확인 필요   [입찰예정] [제외]              │
├──────────────────────────────────────────────────────────────┤
│ 나라장터 │ 데이터 분석 사업    │ 통계청    │ 04-25 │ 진행중│ 68%  │
│  📎 평가기준.docx                                                 │
│  💬 데이터 분석 역량 보유        [입찰예정] [제외]                   │
│  📊 AI분석: 매칭률 68% (조건부 추천) — 클릭하여 상세 보기           │
└──────────────────────────────────────────────────────────────┘
```

- 미분석: [분석] 버튼 표시
- 분석 완료: 매칭률 % 또는 등급(상/중/하) 표시 + 클릭 시 상세
- 분석 중: 스피너 + "분석 중..." 표시

### 17-2. AI 분석 결과 화면 (모달 또는 별도 페이지)

```
┌──────────────────────────────────────────────────────────────┐
│ 🏢 ESG 컨설팅 용역 입찰 — AI 분석 결과                          │
│ 기관: 환경부 | 예산: 50,000,000원 | 마감: 2026-04-30             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 📊 1차 분석 (2026-04-16 10:30)         매칭률: 68%              │
│ ┌────────────┬──────┬──────┬──────────────┬─────────────┐     │
│ │ 평가항목    │ 배점 │ 예상 │ 근거          │ 보완         │     │
│ ├────────────┼──────┼──────┼──────────────┼─────────────┤     │
│ │ 유사사업실적 │  30  │  24  │ ESG 3건 보유  │ 교육실적 추가 │     │
│ │ 투입인력    │  25  │  15  │ PM 충족       │ 기술사 미보유  │     │
│ │ 사업이해도  │  25  │  18  │ 방법론 보유    │ -            │     │
│ │ 가격       │  20  │  15  │ 평균 수준      │ -            │     │
│ └────────────┴──────┴──────┴──────────────┴─────────────┘     │
│ 🤖 AI 의견: 조건부 추천 — 기술사 확보 시 경쟁력 있음              │
│ 💰 분석 비용: 95원 (Haiku 파싱 32원 + Sonnet 매칭 63원)          │
│                                                              │
│ ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ───         │
│                                                              │
│ 📊 2차 분석 (2026-04-16 14:20)         매칭률: 82% ▲14%        │
│ 변경사항: 투입인력 — "기술사(정보관리) 1명 추가"                   │
│ ┌────────────┬──────┬──────┬──────────────┬─────────────┐     │
│ │ 평가항목    │ 배점 │ 예상 │ 근거          │ 보완         │     │
│ ├────────────┼──────┼──────┼──────────────┼─────────────┤     │
│ │ 유사사업실적 │  30  │  24  │ (동일)        │              │     │
│ │ 투입인력    │  25  │  22  │ 기술사 확보    │ -            │     │
│ │ 사업이해도  │  25  │  18  │ (동일)        │ -            │     │
│ │ 가격       │  20  │  15  │ (동일)        │ -            │     │
│ └────────────┴──────┴──────┴──────────────┴─────────────┘     │
│ 🤖 AI 의견: 추천 — 상위 경쟁 가능                                │
│                                                              │
│               [프로필 수정 후 재분석]     [닫기]                  │
└──────────────────────────────────────────────────────────────┘
```

### 17-3. 프로필 수정 팝업 (재분석용)

```
┌──────────────────────────────────────────────────────────────┐
│ 📝 프로필 수정 후 재분석                              [X]       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ [기본 정보]                                                   │
│ 회사명:    [LETS교육컨설팅          ]                          │
│ 설립연도:  [2018                    ]                          │
│ 소재지:    [서울특별시               ]                          │
│                                                              │
│ [사업 실적]                                          [+ 추가]  │
│ ┌──────────┬──────────┬──────────┬────────┐                   │
│ │ 사업명    │ 발주처    │ 금액     │ 기간   │  [삭제]           │
│ │ ESG교육   │ 환경부    │ 3000만원 │ 6개월  │  [삭제]           │
│ │ ESG컨설팅 │ 산업부    │ 5000만원 │ 8개월  │  [삭제]           │
│ │ (신규)    │          │          │        │  [삭제]           │
│ └──────────┴──────────┴──────────┴────────┘                   │
│                                                              │
│ [인력 현황]                                          [+ 추가]  │
│ ┌──────────┬──────────┬──────────┐                            │
│ │ 이름/직급 │ 자격증    │ 경력     │  [삭제]                    │
│ │ 김PM     │ PMP      │ 15년     │  [삭제]                    │
│ │ 이기술사  │ 정보관리  │ 10년     │  [삭제]    ← 신규 추가     │
│ └──────────┴──────────┴──────────┘                            │
│                                                              │
│ [재무 상태]                                                   │
│ 연매출:    [8억                     ]                          │
│ 신용등급:  [A                       ]                          │
│                                                              │
│ ... (접힘/펼침 가능)                                           │
│                                                              │
│              [재분석 실행]          [취소]                      │
└──────────────────────────────────────────────────────────────┘

재분석 완료 후:
┌──────────────────────────────────────┐
│ 재분석 완료! 매칭률: 68% → 82%       │
│                                      │
│ 변경사항을 프로필에 반영하시겠습니까?   │
│                                      │
│     [프로필에 반영]    [이번만 적용]   │
└──────────────────────────────────────┘
```

### 17-4. 설정 > AI 비용 관리

```
┌──────────────────────────────────────────────────────────────┐
│ 🤖 AI 비용 관리                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 현재 잔액: 8,500원                [충전]                       │
│                                                              │
│ ── 이번 달 요약 ──                                            │
│ 총 사용: 1,500원 (15건)                                       │
│ 파싱(Haiku): 525원 / 매칭(Sonnet): 975원                      │
│                                                              │
│ ── 사용 이력 ──                                               │
│ ┌──────────┬──────────────────┬────────┬───────┬──────┐      │
│ │ 일시      │ 공고             │ 유형    │ 모델   │ 비용  │      │
│ ├──────────┼──────────────────┼────────┼───────┼──────┤      │
│ │ 04-16 14:20│ ESG컨설팅 용역  │ 재분석  │Sonnet │ 63원  │      │
│ │ 04-16 10:30│ ESG컨설팅 용역  │ 전체   │H+S    │ 95원  │      │
│ │ 04-15 16:00│ 데이터분석 사업  │ 전체   │H+S    │ 120원 │      │
│ │ 04-15 09:00│ 관리자 충전     │ 충전   │ -     │+10,000│      │
│ └──────────┴──────────────────┴────────┴───────┴──────┘      │
│                                                              │
│ ── AI 설정 ──                                                 │
│ 파싱 모델:  [Haiku 4.5  ▼]                                    │
│ 매칭 모델:  [Sonnet 4.6 ▼]                                    │
│ 환율 ($/₩): [1400           ]                                 │
│                                      [저장]                   │
└──────────────────────────────────────────────────────────────┘
```

### 17-5. 설정 > 회사 프로필

```
┌──────────────────────────────────────────────────────────────┐
│ 🏢 회사 프로필                                  마지막 수정: 04-16│
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ ▼ 기본 정보                                                   │
│   회사명:    [LETS교육컨설팅           ]                        │
│   설립연도:  [2018                     ]                        │
│   업종:     [교육서비스/컨설팅          ]                        │
│   소재지:    [서울특별시                ]                        │
│   중소기업:  [예 ▼]                                             │
│                                                              │
│ ▼ 사업 실적                                          [+ 추가]  │
│   (테이블: 사업명/발주처/금액/기간/역할)                          │
│                                                              │
│ ▼ 인력 현황                                          [+ 추가]  │
│   (테이블: 이름/직급/자격증/경력연수/전문분야)                     │
│                                                              │
│ ▼ 재무 상태                                                   │
│   연매출:    [8억                      ]                        │
│   신용등급:  [A                        ]                        │
│                                                              │
│ ▼ 기술력/역량                                                  │
│   (textarea: 보유기술, 방법론, 특허 등)                           │
│                                                              │
│ ▶ 참여 제한 (접힘)                                              │
│ ▶ 우대 가점 요소 (접힘)                                         │
│                                                              │
│                              [저장]                           │
└──────────────────────────────────────────────────────────────┘
```

---

## 18. API 요청/응답 상세

### 18-1. POST `/api/ai/analyze/{notice_id}` — AI 분석 실행

**Request:**
```
POST /api/ai/analyze/123
(body 없음 — notice_id로 공고 + 첨부파일 + 프로필 자동 조합)
```

**Response (성공):**
```json
{
  "success": true,
  "analysis_id": 45,
  "analysis_seq": 1,
  "notice_id": 123,
  "match_rate": 68.0,
  "recommendation": "조건부 추천",
  "summary": "기술사 확보 시 경쟁력 있음",
  "cost_krw": 95,
  "credit_balance": 8405,
  "items": [
    {
      "item": "유사사업 실적",
      "max_score": 30,
      "expected_score": 24,
      "rationale": "ESG 컨설팅 3건 보유",
      "improvement": "교육 분야 실적 추가 필요"
    }
  ],
  "parsed_files": [
    {"filename": "제안요청서.pdf", "parsed": true},
    {"filename": "사업안내서.hwpx", "parsed": true}
  ]
}
```

**Response (잔액 부족):**
```json
{
  "success": false,
  "error": "credit_insufficient",
  "message": "잔액이 부족합니다. (잔액: 50원, 예상 비용: ~100원)",
  "credit_balance": 50
}
```

**Response (첨부파일 없음 → 간이 모드):**
```json
{
  "success": true,
  "analysis_id": 46,
  "mode": "simple",
  "grade": "중",
  "reason": "교육 컨설팅 분야 적합하나 예산 규모가 소규모",
  "strengths": ["교육 전문 인력 보유", "유사 실적 있음"],
  "weaknesses": ["소규모 사업이라 수익성 낮음"],
  "recommendation": "조건부 추천",
  "cost_krw": 60,
  "credit_balance": 8345
}
```

### 18-2. GET `/api/ai/analyses/{notice_id}` — 분석 결과 목록

**Response:**
```json
{
  "notice_id": 123,
  "notice_title": "ESG 컨설팅 용역 입찰",
  "analyses": [
    {
      "analysis_id": 45,
      "analysis_seq": 1,
      "match_rate": 68.0,
      "recommendation": "조건부 추천",
      "summary": "기술사 확보 시 경쟁력 있음",
      "profile_changes": null,
      "cost_krw": 95,
      "created_at": "2026-04-16 10:30:00"
    },
    {
      "analysis_id": 47,
      "analysis_seq": 2,
      "match_rate": 82.0,
      "recommendation": "추천",
      "summary": "상위 경쟁 가능",
      "profile_changes": {"투입인력": "기술사(정보관리) 1명 추가"},
      "cost_krw": 63,
      "created_at": "2026-04-16 14:20:00"
    }
  ]
}
```

### 18-3. GET `/api/ai/profile` — 회사 프로필 조회

**Response:**
```json
{
  "categories": [
    {
      "category": "기본정보",
      "fields": [
        {"key": "company_name", "label": "회사명", "value": "LETS교육컨설팅", "type": "text"},
        {"key": "established", "label": "설립연도", "value": "2018", "type": "number"},
        {"key": "location", "label": "소재지", "value": "서울특별시", "type": "text"},
        {"key": "is_sme", "label": "중소기업", "value": "true", "type": "boolean"}
      ]
    },
    {
      "category": "사업실적",
      "fields": [
        {
          "key": "project_history",
          "label": "수행실적",
          "value": "[{\"name\":\"ESG교육\",\"client\":\"환경부\",\"amount\":\"3000만원\",\"period\":\"6개월\"}]",
          "type": "json"
        }
      ]
    }
  ],
  "updated_at": "2026-04-16 14:20:00"
}
```

### 18-4. PUT `/api/ai/profile` — 프로필 수정

**Request:**
```json
{
  "fields": [
    {"key": "company_name", "value": "LETS교육컨설팅"},
    {"key": "project_history", "value": "[{...}, {...}]"}
  ],
  "apply_to_master": true  // true: 원본 반영, false: 이번 분석에만 적용
}
```

**Response:**
```json
{
  "success": true,
  "updated_count": 2,
  "changes": {"company_name": "변경없음", "project_history": "1건 추가"}
}
```

### 18-5. POST `/api/ai/credits/charge` — 크레딧 충전

**Request:**
```json
{
  "amount": 10000,
  "description": "관리자 충전"
}
```

**Response:**
```json
{
  "success": true,
  "charged": 10000,
  "balance": 18500
}
```

### 18-6. GET `/api/ai/credits` — 잔액 + 사용이력

**Response:**
```json
{
  "balance": 8500,
  "monthly_usage": 1500,
  "monthly_count": 15,
  "history": [
    {
      "id": 30,
      "type": "usage",
      "amount": -63,
      "balance": 8500,
      "description": "AI분석: ESG컨설팅 용역 (재분석 매칭)",
      "notice_id": 123,
      "model_used": "sonnet-4.6",
      "tokens_input": 5200,
      "tokens_output": 1800,
      "created_at": "2026-04-16 14:20:00"
    },
    {
      "id": 29,
      "type": "charge",
      "amount": 10000,
      "balance": 8563,
      "description": "관리자 충전",
      "created_at": "2026-04-15 09:00:00"
    }
  ]
}
```

---

## 19. DB 스키마 상세

### 19-1. 테이블 관계

```
bid_notices (기존)
  │ 1
  │
  ├──── N  ai_analyses (분석 결과, 차수별)
  │         │
  │         └──── 1  ai_credits (usage 레코드 — analysis_id 참조)
  │
  └──── (첨부파일은 파일시스템 + metadata.json)

company_profile (독립 — 회사 전역 데이터)

ai_credits (독립 — 충전/사용 원장)

ai_config (독립 — 모델/환율 설정)
```

### 19-2. 신규 테이블 DDL

```sql
-- 회사 프로필 (유연한 key-value)
CREATE TABLE IF NOT EXISTS company_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    field_key TEXT NOT NULL UNIQUE,
    field_label TEXT NOT NULL,
    field_value TEXT DEFAULT '',
    field_type TEXT DEFAULT 'text',  -- text, textarea, number, date, boolean, json
    sort_order INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- AI 분석 결과 (차수 관리)
CREATE TABLE IF NOT EXISTS ai_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL REFERENCES bid_notices(id),
    analysis_seq INTEGER NOT NULL DEFAULT 1,

    -- 파싱 결과
    parsed_criteria TEXT,
    parsed_requirements TEXT,
    parsed_summary TEXT,

    -- 매칭 결과 (일반 모드)
    total_score REAL,
    total_max_score REAL,
    match_rate REAL,
    match_detail TEXT,          -- JSON
    match_recommendation TEXT,

    -- 간이 모드
    simple_grade TEXT,
    simple_reason TEXT,

    -- 메타
    mode TEXT DEFAULT 'full',   -- full / simple
    profile_snapshot TEXT,
    profile_changes TEXT,
    model_parsing TEXT,
    model_matching TEXT,
    cost_krw REAL DEFAULT 0,
    tokens_total INTEGER DEFAULT 0,

    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(notice_id, analysis_seq)
);

-- AI 크레딧 (충전/사용 원장)
CREATE TABLE IF NOT EXISTS ai_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('charge', 'usage')),
    amount REAL NOT NULL,
    balance REAL NOT NULL,
    description TEXT,
    notice_id INTEGER,
    analysis_id INTEGER,
    model_used TEXT,
    tokens_input INTEGER,
    tokens_output INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- AI 설정 (모델, 환율 등)
CREATE TABLE IF NOT EXISTS ai_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ai_config 초기값
INSERT OR IGNORE INTO ai_config (key, value, description) VALUES
    ('model_parsing', 'claude-haiku-4-20250414', '문서 파싱 모델'),
    ('model_matching', 'claude-sonnet-4-20250514', '매칭 분석 모델'),
    ('exchange_rate', '1400', '환율 (USD → KRW)'),
    ('pricing_haiku_input', '1.00', 'Haiku 입력 단가 ($/1M tokens)'),
    ('pricing_haiku_output', '5.00', 'Haiku 출력 단가 ($/1M tokens)'),
    ('pricing_sonnet_input', '3.00', 'Sonnet 입력 단가 ($/1M tokens)'),
    ('pricing_sonnet_output', '15.00', 'Sonnet 출력 단가 ($/1M tokens)');
```

### 19-3. bid_notices 확장 컬럼

```sql
-- AI 분석 상태 (기존 테이블에 컬럼 추가)
ALTER TABLE bid_notices ADD COLUMN ai_status TEXT;          -- null/analyzing/done/failed
ALTER TABLE bid_notices ADD COLUMN ai_match_rate REAL;      -- 최신 매칭률 (리스트 표시용)
ALTER TABLE bid_notices ADD COLUMN ai_recommendation TEXT;  -- 최신 추천 (리스트 표시용)
ALTER TABLE bid_notices ADD COLUMN attachment_dir TEXT;      -- 첨부파일 저장 경로
```

### 19-4. 인덱스

```sql
CREATE INDEX IF NOT EXISTS idx_ai_analyses_notice ON ai_analyses(notice_id);
CREATE INDEX IF NOT EXISTS idx_ai_credits_type ON ai_credits(type);
CREATE INDEX IF NOT EXISTS idx_ai_credits_notice ON ai_credits(notice_id);
```

---

## 20. 에러 처리 시나리오

### 20-1. 첨부파일 다운로드 실패

```
원인: URL 만료, 서버 차단, 네트워크 오류
처리:
  1. metadata.json에 실패 기록 (error 필드)
  2. 다운로드 가능한 파일만으로 분석 진행
  3. 전체 실패 시 → 간이 모드로 전환 (DB 정보만 활용)
  4. UI에 "일부 첨부파일 다운로드 실패 — 간이 분석으로 진행됨" 안내
```

### 20-2. 문서 파싱 실패

```
원인: 암호화된 PDF, 손상된 HWPX, 이미지 PDF (스캔본)
처리:
  1. 해당 파일 스킵, 다른 파일로 분석 계속
  2. 모든 파일 파싱 실패 → 간이 모드 전환
  3. metadata.json에 파싱 실패 원인 기록
  4. UI에 "문서 파싱 실패 — 원본 문서를 직접 확인해주세요" 안내
```

### 20-3. Claude API 실패

```
원인: API 키 오류, 요금 부족, rate limit, 네트워크 오류
처리:
  1. API 키 오류 (401) → "API 키를 확인해주세요" + 설정 페이지 링크
  2. Rate limit (429) → 3회 재시도 (3초, 6초, 12초 간격)
  3. 네트워크/서버 오류 (5xx) → 2회 재시도 후 실패 처리
  4. 실패 시 크레딧 차감하지 않음
  5. ai_status = 'failed', 에러 메시지 저장
```

### 20-4. 잔액 부족

```
처리:
  1. 분석 실행 전 예상 비용 산출 (파싱+매칭 토큰 추정)
  2. 잔액 < 예상 비용 → 즉시 거부 + "잔액 부족" 안내
  3. 분석 도중 (파싱 완료, 매칭 시작 전) 잔액 재확인 → 부족 시 파싱 결과만 저장
```

### 20-5. 프로필 미등록

```
처리:
  1. 프로필이 비어있으면 → "회사 프로필을 먼저 등록해주세요" 안내 + 설정 링크
  2. 파싱만 실행 (평가기준 추출)은 프로필 없이도 가능
  3. 매칭 분석은 프로필 필수 → 프로필 없으면 파싱 결과만 표시
```

---

## 21. bidwatch 이식 경계

### 21-1. 공통 모듈 (이식 대상)

```
변경 없이 그대로 가져감:
├── utils/file_parser.py      ← 파일 경로 → ParseResult (프레임워크 무관)
├── ai/base.py                ← BaseAIClient 인터페이스
├── ai/claude_client.py       ← Claude API 구현
├── ai/cost.py                ← calculate_cost() 순수 함수
└── prompts/*.md              ← 프롬프트 파일

어댑터 패턴으로 교체:
├── ai/analyzer.py            ← DB 접근 부분만 인터페이스화
│   - save_analysis(result)   → lets_portal: SQLite / bidwatch: PostgreSQL
│   - load_profile()          → lets_portal: company_profile 테이블 / bidwatch: ORM
│   - deduct_credit(cost)     → lets_portal: ai_credits 테이블 / bidwatch: 결제 시스템
```

### 21-2. 프로젝트 종속 (이식 시 재작성)

```
lets_portal 전용 (bidwatch에서 재작성):
├── routers/ai.py             ← FastAPI 라우터 → bidwatch의 프레임워크로 교체
├── frontend/ai-*.html/.js    ← Vanilla JS → bidwatch의 React 등으로 교체
├── database.py (마이그레이션) ← SQLite DDL → PostgreSQL migration
└── 인증/권한 연동             ← 세션 기반 → bidwatch의 인증 체계
```

### 21-3. 경계 원칙 요약

```
analyzer.py가 유일한 경계점:
  ┌─────────────────────┐     ┌──────────────────────┐
  │   공통 모듈 (이식)    │     │  프로젝트 종속 (재작성) │
  │                     │     │                      │
  │  file_parser ──────►│     │  routers/ai.py       │
  │  claude_client ────►│◄────│  frontend            │
  │  cost.py ──────────►│     │  database 마이그레이션  │
  │  prompts/*.md ─────►│     │  인증/권한             │
  │                     │     │                      │
  │     analyzer.py     │     │                      │
  │  (DB 접근만 교체)    │     │                      │
  └─────────────────────┘     └──────────────────────┘
```
