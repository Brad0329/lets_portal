# Phase C-5: 마스터 프로필 추출기 (ProposalAssetExtractor) — 설계 문서

> 설계 확정일: 2026-04-20
> 선행: Phase C-1(file_parser) ✅, C-2(정량 프로필) ✅, C-3(AI 엔진) ✅, C-4(매칭 UI) ✅

---

## 1. 목표

과거 제안서(HWP/PDF/DOCX/PPTX 등)에서 회사의 **정성적 역량 정보**를 AI로 추출·구조화하여 "마스터 프로필"의 일부로 저장한다. 이 프로필은 이후 다음 두 용도에 사용된다:

1. **공고 매칭** — 공고 평가항목 vs 회사 역량 claim을 비교해 적합도·낙찰 가능성 산출
2. **제안서 재활용** — 신규 제안서의 섹션별 초안 조립용 텍스트 블록 제공

## 2. 배경 및 필요성

- **현재(C-2) 한계:** 정량 프로필만 수동 입력. 회사의 방법론·차별화·서비스 철학 등 **정성 자산**이 구조화되지 않음
- **정성 자산의 출처:** 제안서가 가장 풍부. 회사소개서/결과보고서/요약자료는 보조
- **중복 문제:** 같은 정보가 여러 문서에 반복 등장 → AI 추출·중복 병합 필요
- **AI에 제안서 통째로 넣는 것이 부적합한 이유:** 토큰 폭발(54K/건), 재사용성 없음, 근거 추적 불가

---

## 3. 데이터 모델 — Claim 단위

정성 정보는 모두 **Claim(역량 진술)** 단위로 쪼갠다. 각 claim은 `주장 + 근거 + 메타`로 구성.

### 3-1. Claim 카테고리 (6종)

제안서 실제 파싱 결과 기반 확정:

| 카테고리 | 성격 | 예시 |
|---------|------|------|
| `Identity` | 회사 정체성 | "분야별 교육 프로그램에 특화된 창업교육·컨설팅 전문기업" |
| `Methodology` | 방법론·접근법 | "PBL 기반 — 교육→과제→멘토링 구성" |
| `USP` | 차별화·우위 | "경과원 창업교육 3년 연속 운영, 수료율 160% 달성" |
| `Philosophy` | 서비스 철학·관점 | "참가자 니즈 고려한 선택형 강의", "논-스톱 멘토링" |
| `Story` | 실적 내러티브 | "2022 경기 탄소중립교육 — 모집 133%·수료 140%" |
| `Operational` | 운영 노하우 | "운영사무국+매뉴얼+체크리스트 기반 품질관리" |

### 3-2. Claim 스키마

```python
@dataclass
class Claim:
    id: str                            # "cl_001"
    category: str                      # 6개 중 하나
    statement: str                     # 주장 본문
    tags: dict                         # {"domain":[...], "audience":[...], "method":[...]}
    proposal_sections: list[str]       # ["차별화전략","업체현황"] — 제안서 재활용 시 어느 섹션에 들어가는지
    length_variants: dict              # {"tagline": ..., "summary": ..., "detail": ...}
    evidence_refs: list[str]           # 정량 프로필의 실적 ID 참조 ["실적#14", ...]
    source: dict                       # {"file":"...", "page": 27, "awarded": True, "year": 2023}
    recurrence: int                    # 여러 제안서에 등장한 횟수 → 정체성 강도
    confidence: float                  # 0.0~1.0 — AI 추출 신뢰도
    user_verified: bool                # 사용자 검토 완료 여부
```

### 3-3. 두 계층 구조

- **Core Identity** (10~20개) — 회사 전체를 관통하는 claim. 거의 모든 공고 분석에 기본 투입
- **Capability Library** (수십~수백 개) — 태그 기반 세부 claim. 공고 내용에 맞는 것만 선별 투입 (토큰 비용 관리)

### 3-4. 태그 어휘 (통제 어휘)

- `domain` — 공고 도메인 (ESG, 교육, 창업, 컨설팅, 문화, 관광 ...)
- `audience` — 대상 (스타트업, 예비창업자, 소상공인, 청소년 ...)
- `method` — 방법 (PBL, 멘토링, 피칭, 해커톤 ...)

초기 어휘는 수동 정의 + 제안서 파싱 결과에서 자동 제안. LLM이 임의로 새 태그를 만들지 않도록 Python 레이어에서 통제 어휘 매핑 강제.

---

## 4. 클래스 설계

### 4-1. 위치 및 디렉토리

```
backend/
├── utils/file_parser.py         ← 이미 portable (C-1)
├── ai/
│   ├── base.py                  ← BaseAIClient (portable)
│   └── claude_client.py
└── extractors/                  ← 신규, portable 타깃
    ├── __init__.py
    ├── base.py                  ← BaseExtractor + 공통 데이터클래스
    └── proposal.py              ← ProposalAssetExtractor
```

### 4-2. ProposalAssetExtractor 인터페이스

```python
@dataclass
class ExtractionConfig:
    categories: list[str] = ("Identity","Methodology","USP","Philosophy","Story","Operational")
    tag_vocabulary: dict = None        # {"domain":[...], "audience":[...], "method":[...]}
    min_confidence: float = 0.6
    max_claims_per_section: int = 10
    dedupe_similarity: float = 0.85
    use_prompt_cache: bool = True

@dataclass
class SourceMeta:
    path: str
    year: int | None = None
    awarded: bool | None = None        # 수주/탈락 — 신뢰도 가중치
    proposal_title: str | None = None
    organization: str | None = None    # 발주처

@dataclass
class ExtractionResult:
    claims: list[Claim]
    quantitative_hints: list[dict]     # 실적·인증 등 Python 정규식으로 뽑은 정량 후보
    sources: list[SourceMeta]
    total_cost_krw: float
    warnings: list[dict]

class ProposalAssetExtractor:
    def __init__(self, ai_client: BaseAIClient, config: ExtractionConfig):
        self.ai = ai_client
        self.cfg = config
    
    # 공개 API
    def extract(self, sources: list[SourceMeta],
                progress_cb: Callable | None = None) -> ExtractionResult: ...
    
    def extract_single(self, source: SourceMeta,
                       progress_cb: Callable | None = None) -> list[Claim]: ...
    
    def merge_with_existing(self, new: ExtractionResult,
                            existing: ExtractionResult) -> MergeReport: ...
    
    def to_json(self, result: ExtractionResult) -> str: ...
    
    # 내부 파이프라인 (단계별 분리 — 테스트·디버그 용이)
    def _parse(self, path: str) -> ParseResult: ...            # file_parser 위임
    def _segment(self, text: str) -> list[Section]: ...        # Python, 목차/■/▣ 기반 분할
    def _extract_claims(self, section, source) -> list[Claim]: ...  # LLM 호출
    def _normalize_tags(self, claims) -> list[Claim]: ...      # 통제 어휘 매핑
    def _dedupe(self, claims) -> list[Claim]: ...              # fuzzy/embedding 병합
    def _detect_quantitative(self, text) -> list[dict]: ...    # 정규식 + 선택적 LLM
```

---

## 5. 처리 파이프라인

하이브리드 — Python(결정적) + LLM(문맥)

| 단계 | 담당 | 이유 |
|-----|------|-----|
| 파일 파싱 | Python (file_parser) | C-1에서 이미 검증됨 |
| 섹션 분할 | Python (목차/■/▣/표 경계) | 규칙 기반으로 충분. 전체 문서 통째 LLM보다 섹션별이 품질↑ |
| **Claim 추출** | **LLM (섹션당 1회)** | 문맥 이해 핵심. 섹션당 1회 = 5~10회/제안서 |
| 태그 정규화 | Python (사전 매핑) | LLM은 비슷한 말을 매번 다르게 태깅 → 통제 어휘 강제 |
| 중복 병합 | Python (fuzzy/embedding) | 비용 효율. 임계치 미만은 별도 |
| 정량 힌트 추출 | Python 정규식 + 선택 LLM | 표는 Python, 서술 속 수치는 LLM |

### 5-1. 섹션 분할 규칙

- 제안서 목차(`목 차`, `CONTENTS`) 파싱 → 섹션 경계 추출
- 폴백: `Ⅰ.`, `1.`, `■`, `▣` 등 헤딩 마커
- 폴백2: 글자 수 기반 청크(6K 토큰씩)
- **스킵 대상:** "사업의 필요성", "기대효과" 등 회사 claim이 거의 없는 섹션은 추출 대상에서 제외 (토큰 30~40% 절감)

### 5-2. LLM 호출 전략

- **모델:** Sonnet (품질 기준선) → 이후 Haiku 품질 확인 후 하이브리드 전환 고려
- **Prompt caching:** 시스템 프롬프트(카테고리 정의 + 태그 어휘 + 스키마, ~2K 토큰)를 캐시. 8회 호출 중 7회가 캐시 히트 → 입력 비용 90% 할인
- **구조화 출력:** JSON 모드로 Claim 배열 직접 반환. 재파싱 실패 방지

### 5-3. 중복 병합 로직

1. 같은 카테고리 내에서 statement 간 fuzzy similarity 계산
2. 임계치(0.85) 초과 시 병합 후보
3. 병합 시 recurrence++, length_variants/evidence_refs 통합
4. 최신 문서 + 수주 제안서를 정본(canonical) statement로 채택

---

## 6. 입출력 포맷

### 6-1. 입력

```python
sources = [
    SourceMeta(path="2023_경과원_ESG.hwp", year=2023, awarded=True, 
               organization="경기도경제과학진흥원"),
    SourceMeta(path="2022_대전청년_관광.hwp", year=2022, awarded=True,
               organization="대전관광공사"),
]
result = extractor.extract(sources)
```

### 6-2. 출력 (JSON — XML 미채택)

```json
{
  "meta": {
    "extracted_at": "2026-04-20T10:15:00",
    "extractor_version": "1.0",
    "model": "claude-sonnet-4-5",
    "total_cost_krw": 320
  },
  "sources": [
    {"id": "src_01", "path": "2023_경과원_ESG.hwp",
     "year": 2023, "awarded": true, "pages": 35}
  ],
  "claims": [
    {
      "id": "cl_001",
      "category": "USP",
      "statement": "경기도경과원 창업교육 3년 연속 운영, 수료율 160% 초과 달성",
      "tags": {
        "domain": ["창업교육","ESG"],
        "audience": ["스타트업","예비창업자"],
        "method": ["PBL","멘토링"]
      },
      "proposal_sections": ["차별화전략","업체현황"],
      "length_variants": {
        "tagline": "경과원 창업교육 3년 연속 운영사",
        "summary": "2021~2023년 경기도경제과학진흥원 '경기 창업허브 창업 실전교육' 3년 연속 운영, 모집 134%·수료 165% 달성",
        "detail": "..."
      },
      "evidence_refs": ["실적#14","실적#23","실적#31"],
      "source": {"src_id": "src_01", "section": "업체현황/강점분야", "page": 27},
      "recurrence": 3,
      "confidence": 0.92,
      "user_verified": false
    }
  ],
  "quantitative_hints": [
    {"type":"실적","year":2022,"name":"2022 재도전 성공패키지",
     "org":"창업진흥원","source_id":"src_01"},
    {"type":"인증","name":"경영혁신형 중소기업(Main-Biz)","year":2021,
     "source_id":"src_01"}
  ],
  "warnings": [
    {"type":"low_confidence","claim_id":"cl_017","reason":"..."}
  ]
}
```

**JSON 선택 이유:** Python 네이티브, Claude LLM이 JSON을 매우 잘 다룸(재입력 용이), 프론트엔드 표시 직접, 스키마 검증은 JSON Schema로 충분. XML의 네임스페이스·속성은 이 도메인에 불필요.

---

## 7. 비용 모델 (실측 기반)

### 7-1. 토큰 실측 (한국어 1.06자/토큰)

| 샘플 | 글자 수 | 토큰 수 |
|-----|--------|--------|
| 경과원 ESG HWP 제안서 | 57,454자 | **54,326 tokens** |
| 경과원 ESG PPTX 요약 | 34,488자 | **32,510 tokens** |

### 7-2. 제안서 1건 추출 비용 (환율 1,400원/$ 기준)

| 전략 | 모델 구성 | LLM 호출 | 비용 |
|-----|---------|---------|------|
| A. 단일 호출 | Sonnet 1회 | 1 | ~395원 |
| **B. 섹션 분할 (MVP)** | **Sonnet 8회** | **8** | **~490원** |
| C. Haiku 전량 | Haiku 8회 | 8 | ~160원 |
| D. 하이브리드 | Haiku 8 + Sonnet 정규화 1 | 9 | ~220원 |

**Prompt caching 적용 시 B 전략 실비: ~165원** (90% 할인 7회 캐시 히트)

### 7-3. 공고 매칭 비용 (C-4 실측)

- 현재: **~100원/건** (Haiku 파싱 + Sonnet 매칭)
- 프로필 캐싱 추가 시: **~60원/건**

### 7-4. 운영 시나리오

| 시나리오 | 비용 |
|---------|------|
| 초기 세팅: 제안서 5건 (B 전략 + caching) | 1회 **~825원** |
| 공고 100건 분석 (caching) | ~6,000원 |
| 공고 1,000건 분석 | ~60,000원 |

추출 비용은 **첫 달 이후 전체 운영비의 1~2%로 희석**. 신규 제안서 추가 시에만 재발생.

### 7-5. 비용 최적화 레버 (우선순위)

1. **Prompt caching** — 섹션별 호출에 필수. ~66% 비용 감소
2. **프로필 캐싱** (매칭 단계) — 공고당 40% 감소
3. **Haiku 전환** (품질 검증 후) — 추출 비용 절반 이하
4. **정량은 Python 정규식으로** — 추출 토큰 30~40% 절감
5. **섹션 스킵** — "사업 필요성" 등 제외

---

## 8. UI 흐름 (MVP: 1·2·3단계)

위치: `설정 > 회사 프로필 > 역량 자산` 탭 (기존 정량 프로필 탭과 병렬)

### 1단계: 제안서 업로드 + 메타 입력

```
┌─ 역량 자산 ─────────────────────────────────┐
│  [+ 제안서 업로드]                            │
│                                             │
│  업로드된 제안서                               │
│  ┌──────────────────────────────────────┐  │
│  │ 📄 2023_경과원_ESG.hwp     [처리완료] │  │
│  │    수주 ● | 2023년 | 경과원            │  │
│  │    추출된 claim: 42개                  │  │
│  ├──────────────────────────────────────┤  │
│  │ 📄 2022_대전청년.hwp      [추출중 3/8] │  │
│  │    수주 ● | 2022년 | 대전관광공사      │  │
│  │    [████████░░░░] 62% | ~180원         │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**파일당 메타 3개 필수:** 수주/탈락, 연도, 발주처 → claim 신뢰도 가중치

### 2단계: 처리 중 (진행률 + 비용 실시간)

- 8단계 진행바 (파싱 → 섹션 분할 → 섹션별 추출)
- 현재까지 사용 비용 실시간 표시 (사용자 불안 해소)
- 백그라운드 작업 허용 (다른 페이지 이동 가능, 완료 시 헤더 알림)

### 3단계: 검토·편집 — **가장 중요**

```
┌─ Claim 라이브러리 ─────────────────────────┐
│ [전체 42] [정체성 5] [방법론 8] [USP 11]  │
│                                           │
│  ┌──────────────────────────────────┐    │
│  │ USP                   [승인] [❌] │    │
│  │ "경과원 창업교육 3년 연속 운영..." │    │
│  │ 태그: 창업교육 ESG 경과원         │    │
│  │ 사용섹션: 차별화전략, 업체현황     │    │
│  │ 근거 실적: #14, #23, #31 (링크)   │    │
│  │ 📄 2023_경과원_ESG.hwp, p.27      │    │
│  │ 🔁 비슷한 claim 2건: [병합] [따로] │    │
│  └──────────────────────────────────┘    │
│                                           │
│ 상단: [일괄 승인] [신뢰도 낮은 것만]       │
└───────────────────────────────────────────┘
```

핵심 기능:
- **병합 제안** — 여러 제안서에 나온 같은 주장 자동 그룹
- **원문 하이라이트** — 클릭 시 출처 페이지 사이드 열림
- **일괄 승인** — 신뢰도 0.9+는 일괄, 낮은 것만 검토
- **근거 실적 자동 연결** — claim 언급 사업을 정량 프로필 실적 ID와 매핑

### 4·5단계 — Phase C 후반 (MVP 제외)

- 4단계: 공고 분석 결과에 "사용된 claim" 표시, "claim 부족 경고"
- 5단계: 증분 업로드 시 diff 뷰 (신규/강화/갱신)

---

## 9. bidwatch 이식 규칙

Phase C-1 file_parser와 동일한 수준의 이식성 확보.

### 9-1. 5가지 규칙 (엄수)

1. **의존성은 portable 모듈만** — `utils/file_parser.py` + `ai/base.py`만 import. `database`, `routers`, `config` 등 lets_portal 특정 모듈 절대 금지
2. **설정은 전부 주입** — 태그 어휘, 카테고리, 임계치를 전역 상수·DB에서 읽지 말고 `ExtractionConfig`로 받음
3. **I/O 없음** — 추출기는 DB 쓰지도, HTTP 호출하지도 않음. 파일 경로 받아 JSON 반환만. 진행률은 콜백으로 외부 통보
4. **출력 JSON은 자기서술적** — lets_portal DB ID·외부 참조 없이 그 자체로 완결. bidwatch는 자기 스키마로 매핑만
5. **단일 진입점** — `extractor.extract(sources) -> ExtractionResult`. 내부 메서드는 비공개

### 9-2. 경계 — 추출기 안/밖

| 역할 | 위치 |
|-----|-----|
| 파일 파싱, 섹션 분할, LLM 호출, claim 추출, 중복 병합, JSON 생성 | **추출기 안** |
| 파일 업로드 HTTP 처리 | 밖 (lets_portal: router, bidwatch: 자체) |
| 진행률 표시 UI | 밖 (콜백 수신 측) |
| 결과 JSON을 DB에 저장 | 밖 (프로젝트별 어댑터) |
| Claim 검토·편집 UI (3단계) | 밖 (프로젝트별 UI) |

**3단계 검토·편집은 추출기에 포함 안 함.** 추출기는 초안 JSON만 생성, 검토 상태·편집 이력은 lets_portal DB 스키마 소관.

### 9-3. 이식 절차 (향후)

1. `backend/extractors/` 디렉토리 전체 복사
2. `utils/file_parser.py` + `ai/base.py` 복사 (이미 portable)
3. bidwatch 측에서 자체 DB 어댑터·라우터·UI 작성
4. 끝

---

## 10. MVP 범위

### 10-1. 포함 (1·2·3단계)

- [ ] `backend/extractors/base.py` + `proposal.py` 클래스 작성
- [ ] 샘플 HWP 1건으로 섹션 분할 + LLM 추출 + JSON 출력 검증
- [ ] 업로드 UI (메타 입력 포함) — 1단계
- [ ] 진행률 표시 + 비용 실시간 — 2단계
- [ ] Claim 검토·편집 화면 (카테고리 탭, 일괄 승인, 병합 제안) — 3단계
- [ ] DB 스키마: `claims` 테이블 + `proposal_sources` 테이블
- [ ] Prompt caching 적용

### 10-2. 제외 (Phase C 후반)

- [ ] 4단계: 공고 분석에 "사용된 claim" 연결 표시
- [ ] 5단계: 증분 업로드 diff 뷰
- [ ] Haiku 전환 실험
- [ ] 임베딩 기반 중복 병합 (초기엔 fuzzy string)
- [ ] 결과보고서/회사소개서 추출기 (`ResultReportExtractor` 등)

### 10-3. 테스트 자원

- `C:\Users\user\OneDrive\바탕 화면\[대외비]제안서 샘플\제안서 샘플\` — 여러 샘플 보유
- 검증 완료: `샘플 8 _ 경과원 ESG 교육\제안서(사본).hwp` (54,326 tokens) + PPTX

---

## 11. 다음 단계 (새 세션에서)

1. **프로토타입 1**: 경과원 ESG HWP로 섹션 분할 + 1섹션 LLM 추출 → JSON 출력 검증
2. **프로토타입 2**: 전체 섹션 확장 + 중복 병합
3. **DB 스키마 확정**: `claims`, `proposal_sources` 테이블 정의
4. **API 설계**: `/api/ai/extractor/upload`, `/api/ai/extractor/progress`, `/api/ai/extractor/claims`
5. **UI**: 3단계 화면 구현 (핵심 가치의 80%)

작업로그는 `work_log2/log_phaseC5.md`에 기록.

---

## 12. 참고 자료

- **이전 설계:** `work_log2/design_phase_c_ai.md` (C-1~C-4)
- **선행 로그:** `work_log2/log_phaseC.md`
- **재사용 모듈:** `backend/utils/file_parser.py`, `backend/ai/base.py`, `backend/ai/claude_client.py`
- **파싱 샘플 결과:** `tmp/hwp_parsed.md` (57K자), `tmp/pptx_parsed.md` (34K자)
