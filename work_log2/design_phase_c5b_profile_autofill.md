# Phase C-5-B: 회사 프로필 자동 채우기 (통합 업로드 흐름) — 설계 문서

> 설계 확정일: 2026-04-20
> 선행: Phase C-5 (ProposalAssetExtractor MVP) ✅

---

## 1. 배경

### 1-1. 해결하려는 문제

- **라스트마일 공백**: Phase C-5가 정량 힌트 44건을 `proposal_quantitative_hints`에 자동 축적하지만 `company_profile`로 반영되는 통로가 없음. API(`list_hints`, `update_hint`)만 있고 프론트 UI·반영 로직 미구현.
- **초보자 진입 장벽**: 설정 > 회사 프로필 진입 시 정량 16개 필드와 역량 자산 탭 두 곳을 따로 채워야 함. "제안서 한 번 올리면 알아서 채워준다"는 선언적 UX 부재.
- **두 파이프라인 중복**: 역량 자산 탭 업로드 → claim + 힌트 둘 다 추출 중인데 힌트만 버려지는 형국. 한 번의 파이프라인으로 둘 다 반영하는 통합 입구가 합리적.

### 1-2. 제약·원칙

1. **자동 반영 금지** — 제안서는 오탐·과장·만료된 정보를 섞음. 사용자 확인 없이 `company_profile`을 건드리면 공고 매칭 점수까지 오염.
2. **기존 UI 보존** — 역량 자산 탭의 claim 승인/병합/편집 기능은 유지. 본 흐름은 "초안 입구", 세밀 편집은 탭에 위임.
3. **기존 추출 파이프라인 재사용** — `ProposalAssetExtractor.extract_single`을 그대로 호출. 새 추출 로직·프롬프트 추가 없음.
4. **portable 원칙 미적용** — 본 흐름은 `company_profile` 스키마에 종속되므로 bidwatch 이식 대상 아님. 추출기 자체는 여전히 portable.

---

## 2. UX 흐름

### 2-1. 전체 플로우

```
설정 > 회사 프로필 섹션
│
├─ 🚀 제안서로 프로필 자동 채우기  ← 섹션 상단 신규 카드
│   [파일] [연도] [결과▼] [발주처] [제안서명]
│                                    [📤 분석 시작]
│   
├─ 📊 정량 프로필 (기존 탭)           ← 그대로 유지
└─ 💡 역량 자산 (기존 탭)             ← 그대로 유지

[📤 분석 시작] 클릭
  ↓
  백그라운드 추출 (기존 /upload + 폴링 재사용)
  ↓
  "분석 중... 1/8 섹션 · 누적 120원"  ← 상단 카드 영역에 진행바
  ↓
  완료 시 자동으로 미리보기 모달 오픈
  ↓
┌─ ✨ 분석 결과 미리보기 ────────────────┐
│                                        │
│  📊 정량 정보 — 총 44건                │
│  ┌──────────────────────────────────┐ │
│  │ 📁 수행실적 (project_history)     │ │
│  │  ☑ 2022 경기 ESG 교육 · 경과원    │ │
│  │  ☑ 2023 재도전 성공패키지 · 창진원│ │
│  │  ☐ 사업자 등록 여부  ⚠ 오탐 의심   │ │
│  │                                   │ │
│  │ 🏅 인증·자격 (patents_certs)      │ │
│  │  ☑ Main-Biz 인증 (2021)           │ │
│  │  ☑ 창업보육매니저 자격            │ │
│  └──────────────────────────────────┘ │
│                                        │
│  💡 역량 claim — 36건                  │
│   카테고리별 접힘 (USP 14 · 방법론 7…) │
│   ☑ 신뢰도 0.9+ 자동 체크              │
│                                        │
│  [병합 규칙]                           │
│   ● 빈 칸만 채우기 (권장)              │
│   ○ 덮어쓰기                           │
│   ○ JSON 배열에 추가만                 │
│                                        │
│     [취소]      [선택한 항목 반영]     │
└────────────────────────────────────────┘
  ↓
  반영
  ↓
  정량 프로필 카드 + 역량 자산 claim 목록 동시 리프레시
  "✅ 수행실적 2건·인증 2건·claim 31건 반영됨 · 역량 자산 탭에서 세부 편집 가능"
```

### 2-2. 상단 카드 (자동 채우기) 재사용

- 업로드 폼은 역량 자산 탭의 동일 폼을 재사용 — 서버 엔드포인트(`POST /api/ai/extractor/upload`) 그대로
- 업로드 후 `src_id`를 받아 폴링(`GET /sources/{src_id}`)으로 진행 상태 수신
- 완료 감지 시 자동으로 `GET /preview/{src_id}` 호출 후 모달 오픈

### 2-3. 미리보기 모달 기본값

- **정량 힌트**: 신뢰도(confidence) ≥ 0.8 체크, 단 오탐 의심 플래그가 붙은 것은 해제
- **claim**: 신뢰도 ≥ 0.9 체크 (역량 자산 탭 일괄 승인과 동일 임계)
- **병합 규칙**: "빈 칸만 채우기" 기본 선택

### 2-4. 모달 UX 세부

- **카테고리별 collapse** — claim 36건을 한 번에 표시하면 압도됨. USP/방법론 헤더 펼치기/접기
- **오탐 표시** — 힌트 텍스트에 "등록 여부", "사업자 등록" 등 특정 패턴이 있으면 `⚠ 오탐 의심` 뱃지 + 기본 해제
- **이미 프로필에 존재하는 항목** — `project_history`에 name 기준 동일 항목이 이미 있으면 `🔁 중복` 표시 + 기본 해제
- **반영 후 닫기** — 모달 닫고 상단 카드는 완료 배지로 전환, 역량 자산 탭으로 이동 링크 제공

---

## 3. API 설계

### 3-1. `GET /api/ai/extractor/preview/{src_id}`

완료된 제안서 1건의 미리보기 데이터 조회. 모달 렌더링용.

**응답 스키마:**
```json
{
  "source": {
    "src_id": "src_0002",
    "file_name": "제안서(사본).hwp",
    "organization": "경기도경제과학진흥원",
    "year": 2023,
    "awarded": true,
    "claim_count": 36,
    "hint_count": 44
  },
  "quantitative": {
    "project_history": [
      {
        "hint_id": 12,
        "name": "2022 경기 ESG 교육",
        "client": "경과원",
        "amount": null,
        "period": "2022",
        "role": null,
        "is_duplicate": false,
        "is_suspicious": false,
        "source_text": "2022년 경기도경제과학진흥원 ESG 교육..."
      }
    ],
    "patents_certs": [
      {
        "hint_id": 34,
        "text": "Main-Biz 인증 (2021)",
        "is_duplicate": false,
        "is_suspicious": false
      }
    ],
    "ignored": [
      {"hint_id": 7, "type": "목표", "reason": "매핑 없음"}
    ]
  },
  "claims": {
    "by_category": {
      "USP": [ {"claim_id":"cl_xxx", "statement":"...", "confidence":0.95, "user_verified":0}, ... ],
      "Methodology": [ ... ]
    },
    "counts": {"USP":14, "Methodology":7, "Operational":5, "Philosophy":5, "Story":3, "Identity":1}
  }
}
```

**서버 로직:**
- `proposal_quantitative_hints`에서 `proposal_source_id = (src_id 매핑)` 로드
- type별로 분류: 실적 → `project_history` 후보, 인증·등록·자격 → `patents_certs` 후보, 나머지 → `ignored`
- **중복 감지**:
  - `project_history`: 기존 JSON 배열 파싱 후 `name` 포함 여부(대소문자·공백 무시, 간단 fuzzy)
  - `patents_certs`: 기존 textarea를 줄 단위 split 후 각 줄과 hint text 간 `SequenceMatcher.ratio() > 0.85` 검사
- **오탐 감지**: 힌트 텍스트에 `(등록 여부|등록증 번호|여부)` 패턴, name이 너무 짧음(< 6자), 수치·연도 누락 등 휴리스틱 체크
- `claims`는 기존 `/claims?source_id=X` 재사용 가능 — 하지만 preview용으로 `by_category` 구조화된 응답이 더 편함

### 3-2. `POST /api/ai/extractor/apply-to-profile`

선택된 힌트·claim을 프로필에 반영.

**요청 body:**
```json
{
  "source_id": 2,
  "hint_ids": [12, 14, 34, 35],
  "claim_ids": ["cl_xxx", "cl_yyy", ...],
  "merge_mode": "fill_empty"
}
```

- `merge_mode`: `"fill_empty"` (빈 칸만) | `"overwrite"` (덮어쓰기) | `"append_only"` (JSON 배열만 append, 단일 필드는 건드리지 않음)
- `hint_ids`·`claim_ids`가 비어있어도 OK (빈 반영)

**응답:**
```json
{
  "success": true,
  "profile_updates": {
    "project_history": {"added": 2, "skipped_duplicates": 0},
    "patents_certs": {"lines_added": 2, "skipped_duplicates": 0}
  },
  "claims_approved": 31,
  "hints_marked_imported": 4,
  "skipped": []
}
```

**서버 로직:**
1. `hint_ids` 각 힌트 로드 → type별로 묶음
2. `project_history`:
   - 기존 `company_profile.field_value` JSON 파싱
   - 중복 체크 (name 기준) 후 `merge_mode`에 따라 append 또는 skip
   - `append_only`/`fill_empty` 둘 다 동일 동작 (JSON 배열은 append가 자연스러움)
   - `overwrite`는 배열을 새 리스트로 교체 (위험하니 UI에서 경고 필요)
   - INSERT/UPDATE 결과로 새 JSON 저장
3. `patents_certs`:
   - 기존 textarea 로드
   - 줄 단위 split, 중복 제거 후 새 힌트 line append
   - `fill_empty`는 기존 값이 비어있을 때만 덮어씀, 있으면 append
4. `claim_ids` → `UPDATE claims SET user_verified=1 WHERE claim_id IN (...)` 일괄 승인
5. `hint_ids` → `UPDATE proposal_quantitative_hints SET user_action='imported' WHERE id IN (...)`
6. 모두 단일 transaction

### 3-3. 기존 엔드포인트 재사용

- `POST /api/ai/extractor/upload` — 상단 카드 업로드 그대로
- `GET /api/ai/extractor/sources/{src_id}` — 진행률 폴링 그대로
- `GET /api/ai/extractor/claims?source_id=X` — 역량 자산 탭이 원래 쓰던 것

---

## 4. 중복·오탐 감지 규칙

### 4-1. `project_history` 중복 감지

기존 항목이 `[{"name":"2022 경기 ESG 교육", "client":"경과원", ...}]` 형태일 때, 새 힌트의 name과 비교:

```python
def is_duplicate_project(new_name: str, existing: list[dict]) -> bool:
    new_key = _norm(new_name)  # 공백·특수문자 제거, 소문자
    for ex in existing:
        ex_key = _norm(ex.get("name", ""))
        if not ex_key or not new_key:
            continue
        if new_key == ex_key:
            return True
        # 부분 포함 (한쪽이 다른 쪽에 완전히 들어감)
        if len(new_key) >= 6 and len(ex_key) >= 6:
            if new_key in ex_key or ex_key in new_key:
                return True
    return False
```

### 4-2. `patents_certs` 중복 감지

기존 textarea를 줄 단위 split, 각 줄과 fuzzy 비교:

```python
from difflib import SequenceMatcher

def is_duplicate_cert(new_line: str, existing_text: str, thresh: float = 0.85) -> bool:
    new_norm = _norm(new_line)
    for ex in existing_text.split("\n"):
        ex_norm = _norm(ex)
        if not ex_norm:
            continue
        if SequenceMatcher(None, new_norm, ex_norm).ratio() >= thresh:
            return True
    return False
```

### 4-3. 오탐 감지 (`is_suspicious`)

```python
SUSPICIOUS_PATTERNS = [
    r"등록\s*여부", r"등록증\s*번호", r"가능\s*여부",
    r"사업자\s*등록(?!증)",   # "사업자 등록 여부"는 오탐, "사업자 등록증"은 허용
]
def is_suspicious(text: str) -> bool:
    if len(text.strip()) < 6:
        return True
    for pat in SUSPICIOUS_PATTERNS:
        if re.search(pat, text):
            return True
    return False
```

---

## 5. UI 구현 포인트

### 5-1. 상단 카드 위치

- `settings.html`의 `#company-profile-section` 내부, `<div class="profile-tabs">` **바로 위**
- 탭 전환과 무관하게 항상 보이는 "진입점 UI"
- 접혀진 상태(collapsed) 옵션은 MVP 제외 (항상 펼침)

### 5-2. 상단 카드 컴포넌트

```html
<div id="profile-autofill-card" style="...">
    <h3>🚀 제안서로 프로필 자동 채우기</h3>
    <p style="font-size:12px;color:#666">과거 제안서를 업로드하면 정량 정보와 역량 claim을 분석해 프로필 초안을 작성합니다.</p>
    
    <form id="autofill-upload-form">
        <!-- 역량 자산 탭 업로드 폼과 동일 필드 -->
    </form>
    
    <!-- 진행 상태 (분석 중일 때만) -->
    <div id="autofill-progress" style="display:none">
        <div class="progress-bar">...</div>
        <span>분석 중... 섹션 3/8 · 누적 180원</span>
    </div>
</div>
```

### 5-3. 모달

- 기존 modal 패턴 없으므로 새 `<div id="autofill-preview-modal">` 추가
- position:fixed 배경 + 중앙 정렬 컨테이너
- 모달 내부 카테고리별 collapsible (기본: 펼침)
- ESC · 배경 클릭으로 닫기

### 5-4. 반영 후

- 모달 닫기
- 상단 카드에 "✅ 반영 완료 — 수행실적 2건·인증 2건·claim 31건" 토스트 2초 표시 후 사라짐
- 정량 프로필 탭 `renderProfile()` 재호출
- 역량 자산 탭 `refreshAll()` 재호출
- 상단 카드는 업로드 폼 초기화 (다음 제안서 업로드 가능 상태로)

---

## 6. MVP 범위

### 6-1. 포함

- [ ] `GET /preview/{src_id}` 엔드포인트
- [ ] `POST /apply-to-profile` 엔드포인트 (fill_empty / append_only 2 모드만 — overwrite는 제외)
- [ ] 중복·오탐 감지 로직
- [ ] 상단 카드 UI (업로드 폼 + 진행 상태)
- [ ] 미리보기 모달 (정량·역량 선택 + 반영 버튼)
- [ ] 반영 후 정량 프로필·역량 자산 탭 리프레시
- [ ] E2E: src_0002로 빈 프로필에 반영 → 정량·역량 둘 다 채워짐 확인

### 6-2. 제외 (후속)

- `overwrite` 모드 (위험성 높음 — 확인 후 별건)
- 기본정보(회사명 등) LLM 별도 추출
- 여러 제안서 일괄 분석 미리보기
- 클레임 본문에서 정량 유추 (예: "3년 연속 수행"에서 연도 범위 자동 매핑)
- 미리보기 모달에서 개별 항목 편집 (이름·기간 수정 등) — 반영 후 정량 프로필 탭에서 편집하도록

---

## 7. bidwatch 이식 정책

**이식 대상 아님.** 본 기능은 `company_profile` 스키마에 종속되어 portable 원칙을 위반한다. `backend/extractors/`·`backend/utils/file_parser.py`·`backend/ai/*`는 그대로 portable 유지, C-5-B는 lets_portal 전용 글루 계층.

---

## 8. 참고

- 선행 설계: `work_log2/design_phase_c_extractor.md`
- 선행 로그: `work_log2/log_phaseC5.md` (세션 1~6)
- 실제 스키마: `backend/database.py` `company_profile` 테이블 (줄 286~322)
- 기존 UI: `frontend/js/settings.js` `renderJsonField` (project_history·staff_list JSON 배열), `renderProfile` (textarea 필드)
