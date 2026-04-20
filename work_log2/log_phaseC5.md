# Phase C-5: 마스터 프로필 추출기 (ProposalAssetExtractor) — 작업 로그

> 설계 문서: `work_log2/design_phase_c_extractor.md`
> 시작일: 2026-04-20

## 목표

과거 제안서에서 회사의 정성적 역량을 **Claim 단위**로 추출·구조화하여 마스터 프로필 구축. 공고 매칭 + 제안서 재활용 두 용도 지원. bidwatch 이식 가능 구조(`backend/extractors/`) 유지.

## MVP 범위 (1·2·3단계)

- [x] 프로토타입 1: 샘플 HWP 1건으로 섹션 분할 + 1섹션 LLM 추출 → JSON 검증
- [x] 프로토타입 2: 전체 섹션 확장 + 중복 병합
- [x] `backend/extractors/base.py` + `proposal.py` 클래스 구현
- [x] DB 스키마: `claims`, `proposal_sources`, `proposal_quantitative_hints` 테이블
- [x] API: `backend/routers/extractor.py` — 소스 CRUD + claim 목록/편집/일괄승인/병합/병합제안 + 정량힌트 (11개 엔드포인트)
- [x] UI 1·2·3단계: 설정 > 회사 프로필 > 역량 자산 탭 (업로드 + 소스 진행률 + Claim 검토·편집·병합)
- [x] E2E 전 플로우 검증 — 실제 제안서 업로드 → 36 claims · 482.7원 추출 완료 → 편집/일괄승인/병합제안/삭제 정상 동작
- [x] Prompt caching 적용 (`BaseAIClient.analyze_document(system=, use_cache=)` + 프롬프트 2파일 분리) — 실측 482.7원 → 445.9원 (-7.6%)
- [ ] Prompt caching 적용

## 결정사항 (2026-04-20, 프로토타입 1·2)

1. **섹션 분할은 Python 규칙 기반** — LLM으로 분할하려면 섹션 식별에 토큰을 낭비한다. 목차 마커(Ⅰ./Ⅱ./Ⅲ. + 숫자 서브섹션 `^[1-9]\s+[가-힣]`)만으로 11개 섹션을 정확히 분할 가능함을 실증. 표 라인(`|` 시작)은 헤딩 후보에서 제외 (같은 제목이 표에서 반복되는 패턴 대응).

2. **중간 레벨(1/2/3 서브섹션)을 LLM 호출 단위로 채택** — 최상위(Ⅰ/Ⅱ/Ⅲ)는 섹션이 너무 크고(최대 37K자), 하위(1-1/1-2)는 너무 잘게 쪼개져 호출이 폭발한다. 중간 레벨 = 제안서당 8~11회 호출 = 설계 예상치(8회)와 일치.

3. **스킵 섹션 기본값 3종** — `사업의 필요성`, `사업목표`, `기대효과`. 근거: 이 3개는 RFP/공고 내용의 재서술이라 회사 claim이 거의 없다. `제안개요`(최상위 타이틀)도 같이 포함. 토큰 20~30% 절감.

4. **기존 `analyze_document(text, prompt)` API 재사용** — BaseAIClient에 새 시스템 메시지 지원을 추가하지 않고 기존 API로 시작. Prompt caching은 다음 단계에서 도입(BaseAIClient 확장).

5. **Claim ID는 content-derived MD5 short hash** — `cl_{md5(src_id+statement)[:8]}`. 이유: 재실행 시 동일 statement는 동일 id로 안정화 → 증분 업로드·DB 업데이트 시 매핑 가능. 순차 번호는 재실행마다 바뀌어 부적합.

6. **태그 어휘 통제는 Python에서 강제** — LLM이 자유롭게 태그를 쓰면 "창업 교육" vs "창업교육" vs "창업 전문 교육" 식으로 편차 발생. 프롬프트에 어휘 리스트 주입 + 응답에서 어휘에 없는 태그는 부분 매칭으로 치환/제거. 신규 태그는 수동 어휘 추가 절차로만 확장.

7. **정량 힌트는 LLM + Python 정규식 하이브리드** — LLM은 문맥 이해로 "Main-Biz 인증(2021)", "액셀러레이터 등록(중기부)" 같은 구조화 사실을 잡아낸다. Python 정규식은 백업용으로 번호 패턴(`제 XXX호`) + 인증 키워드 동시 매칭만 허용(단일 키워드 매칭은 "사업자 등록 여부" 같은 오탐이 심했음, 아래 실패 사례 참조).

## 결정사항 (2026-04-20 세션 2, DB 스키마)

1. **3개 테이블로 분리** — `proposal_sources`(소스 메타+처리 상태), `claims`(추출 결과), `proposal_quantitative_hints`(정량 후보). 정량 힌트를 claims와 분리한 이유: 사용자 워크플로가 다르다. Claim은 "승인/거부/병합"이지만, 정량 힌트는 `company_profile`의 `project_history`·`patents_certs`로 수동 편입하는 별도 흐름.

2. **병합은 별도 테이블 없이 `claims.merged_from` JSON에 기록** — 3단계 UI의 "병합 제안"은 fuzzy similarity로 즉시 계산 가능하므로 런타임 조회. 실제 병합 실행 시 대상 claim들은 `user_verified=2`(거부/숨김)로 표시하고, canonical claim의 `merged_from`에 원본 claim_id들을 적재. 증분 업로드 시 동일 statement는 `claim_id` UNIQUE 충돌로 감지 → `recurrence++`.

3. **`user_verified` 3-state** — 0=미검토, 1=승인, 2=거부/병합됨. "거부"와 "병합됨"을 같은 상태로 통일한 이유: UI 표시 측면에서는 둘 다 "기본 목록에서 숨김" 동일 동작. 병합 이력은 `merged_from`으로 추적 가능하므로 별도 상태 불필요.

4. **`src_id`는 extractor 결정적 문자열을 그대로 저장** — extractor가 생성하는 `src_01`·`src_02` 같은 문자열을 `proposal_sources.src_id`(UNIQUE)로 저장. DB `id`와 중복되지만, extractor의 출력 JSON이 자기서술적(bidwatch 이식 대비)이라 `src_id` 기반 참조가 portable.

5. **진행 상태를 DB에 적재 (`status`/`progress`/`processed_sections`/`cost_krw`)** — SSE/폴링 기반 진행률 UI가 다른 세션/페이지 이동 후에도 복원 가능하도록. 백그라운드 작업 전제.

6. **`user_edited_statement` 컬럼 분리** — 사용자가 claim statement를 수정해도 원본(`statement`) 보존. 원본은 재추출 시 동일 claim_id 매칭을 위해 필요.

## 결정사항 (2026-04-20 세션 3, API)

1. **라우터 분리** — `routers/ai.py`(공고 분석)와 별개로 `routers/extractor.py` 신규 작성. 같은 `/api/ai` prefix 하위지만 책임이 다르다. ai.py는 공고별 분석 흐름, extractor.py는 제안서 업로드·claim 라이브러리 관리.

2. **백그라운드 추출은 threading.Thread** — FastAPI의 BackgroundTasks 대신 daemon Thread 채택. 이유: 추출이 수분 소요되어 request life cycle과 분리 필요, 여러 업로드 동시 처리 허용(스레드별 conn 독립), extractor의 `progress_cb` 콜백이 이미 동기 인터페이스라 Thread가 자연스러움.

3. **진행률은 DB 폴링 방식** — SSE/WebSocket 대신 `GET /sources/{src_id}`를 UI가 폴링. 이유: 세션·페이지 이동 후에도 상태 복원 가능(설계 §8-2 요구), 구현 단순, sqlite+WAL이 동시 read 감당 가능.

4. **claim INSERT 시 UNIQUE 충돌은 recurrence++** — 동일 claim_id(content-derived MD5)가 다른 proposal_source에서 재출현하면 기존 레코드의 `recurrence`만 증가. 이는 dedup의 자연스러운 확장: 추출기 내부 dedup은 같은 세션 내에서만, 세션 간 dedup은 DB 레이어에서.

5. **Form 기반 multipart 업로드** — `python-multipart` 의존성 추가(requirements.txt). `UploadFile + Form` 조합으로 파일·메타(year/awarded/organization/proposal_title)를 한 번에 수신. 2단계 처리(메타 등록→파일 업로드)는 UX 복잡도만 올림.

6. **파일 저장 레이아웃** — `data/proposals_assets/{src_id}/{filename}`. src_id 기준 디렉토리화로 삭제/백업 단위 명확. 동일 파일명 충돌 회피.

## 결정사항 (2026-04-20 세션 4, UI)

1. **설정 페이지 내 탭 방식 채택 (별도 페이지 X)** — `회사 프로필` 섹션을 "정량 프로필"(기존) + "역량 자산"(신규) 2-탭으로 구성. 두 개념이 한 프로필의 두 축(수치 vs 정성)이라는 설계 의도와 일치. 별도 페이지면 네비게이션 비용만 증가.

2. **폴링 간격 3초, processing/pending일 때만** — 소스 중 하나라도 `processing`/`pending`이면 3초 후 재조회 예약. 완료 후 자동 중단. SSE 대비 구현 단순 + 동시 업로드 여러 건 지원.

3. **Claim 카드 인라인 편집** — 별도 모달 없이 카드 내 textarea 토글. 편집 중엔 `_editingClaimId` 1건만 유지. 이유: 짧은 statement가 대부분(1~2문장), 모달 팝업은 과함.

4. **병합 제안은 미검토(`user_verified=0`) 대상만** — 이미 승인된 claim끼리 병합 제안은 거의 불필요(중복이 있었다면 승인 전에 발견). 병합 실행 시 primary는 자동 승인(`=1`), 다른 쪽은 숨김(`=2`). 승인 과정을 별도로 거치지 않도록 단축.

5. **일괄 승인 프리셋은 "신뢰도 0.9+"만 제공** — 설계 §8-3의 "신뢰도 낮은 것만 검토" 흐름을 버튼 한 개로. 세밀한 필터는 MVP 외.

6. **반응형 업로드 폼** — `display:grid` 대신 `flex-wrap`으로 구성. 뷰포트가 좁은 사이드바 환경에서도 레이아웃이 자연스럽게 줄바꿈(검증 중 600px 폭에서 그리드가 깨져 수정).

7. **primary로 confidence 높은 claim 자동 선택** — 병합 제안에서 두 쌍 중 confidence가 높은 쪽을 primary로 기본 설정. 사용자가 별도로 고를 필요 없음.

## 실패한 접근 (세션 4)

1. **업로드 폼을 CSS Grid로 6열 고정** → 실패
   - 원인: `grid-template-columns:1fr 90px 100px 1fr 1fr auto`는 데스크탑 기준. 실제 preview는 좁은 폭(sidebar 포함 ~650px)에서 발주처/제안서명 칸 텍스트가 세로로 쌓이고 업로드 버튼이 화면 밖으로 밀렸다.
   - 해결: `flex-wrap:wrap` + 각 필드에 `flex` 기준치와 `min-width` 부여. 좁은 폭에서는 2~3줄로 자연스럽게 접힘.

2. **uvicorn `--reload`의 기본 watch 범위** → 실패
   - 원인: `--reload`만 주면 cwd 전체를 watch. E2E 스크립트(tmp/) 편집 시 uvicorn이 서버 재시작 → 백그라운드 daemon 스레드 종료 → DB는 `pending`으로 잔존.
   - 해결: launch.json에 `--reload-dir backend` 추가. backend/ 내부만 watch. 세션 2회차 E2E부터 정상 동작.

3. **requests.Session 기본 keep-alive** → 실패 (일시)
   - 원인: Windows + uvicorn 장시간 폴링 조합에서 유휴 소켓이 서버/OS에 의해 먼저 닫히는데 Session이 재사용을 시도해 `WinError 10053 ConnectionAborted`.
   - 해결: E2E 스크립트에 `Connection: close` 헤더 + 지수백오프 재시도 래퍼 추가. 서버/애플리케이션 코드는 무결.

## Prompt caching 실측 (세션 5) — 2026-04-20

| 메트릭 | 캐시 OFF (src_0002) | 캐시 ON (src_0003) | 차이 |
|-------|---------------------|-------------------|-----|
| claims | 36 | 37 | +1 (추출 편차) |
| input tokens | 62,758 | 49,718 | -20.8% (캐시 read로 빠짐) |
| output tokens | 10,432 | 10,657 | +2.2% |
| cache_write | 0 | 1,620 | system 1회 적재 |
| cache_read | 0 | 11,340 | 1,620×7회 재사용 |
| **비용** | **482.7원** | **445.9원** | **-7.6%** |

### 설계 예상(65% 절감) vs 실측(7.6% 절감) 차이 원인

- 캐시 대상 system 프롬프트: **1,620 tokens** (프롬프트 2파일 분리 후 실측)
- 섹션 본문(user content): 평균 **~6,200 tokens/호출** — 고정의 약 4배
- 섹션 본문이 지배적이라 90% 할인 적용 대상이 전체의 ~3%에 불과
- 이론 최대: `(1,620 × 7회 × 0.9) / 전체 비용 ≈ 7~8%` → 실측과 일치

### 결론

- Prompt caching은 **정상 작동** (API usage에 `cache_creation_input_tokens=1620`, `cache_read_input_tokens=11340` 모두 반영)
- 절감 효과는 설계 예상치의 ~1/8 수준. 섹션 본문이 큰 구조에서는 caching이 지배 레버가 아님
- 더 큰 절감이 필요하면 **Haiku 전환** (보통 30~50% 절감)이나 **섹션 스킵 목록 확장**(10~20% 절감)이 더 효율적

### 결정사항 추가 (세션 5, Prompt caching)

1. **Prompt caching은 그대로 유지** — 절감률이 작아도 "공짜 최적화"(코드 추가 부담 거의 없음). 향후 프롬프트가 풍부해지면(few-shot, 상세 가이드) 절감률 자동 증가.

2. **프롬프트 파일 2개 분리 채택** — `extract_proposal_claims_system.md`(고정) + `_user.md`(섹션 메타). legacy `extract_proposal_claims.md`는 하위 호환 폴백용으로 유지. 캐시 유효성이 프롬프트 문자열의 바이트-완전 동일성에 의존하므로 파일 분리가 안전.

3. **DB에 캐시 토큰 컬럼 미추가** — 비용은 `cost_krw`에 이미 반영, 진단은 서버 로그에서. MVP 범위에서는 컬럼 추가가 오버엔지니어링.

4. **태그 어휘 치환은 system 쪽에서** — 세션 내 `ExtractionConfig`가 불변이므로 치환된 문자열도 불변 → 캐시 유효. 어휘를 변경하는 경우 전체 캐시가 무효화되지만 희소한 시나리오.

## 외부 제약

1. **분할 HWP의 섹션 마커 특성** — `pyhwp`가 추출한 마크다운은 헤딩 라인이 두 번 등장한다 (순수 텍스트 + `| 1 | 사업의 필요성 |` 표 포맷). 헤딩 regex는 표 라인(`|` 시작)을 제외해야 중복 매칭을 피할 수 있다.

2. **섹션 크기 비대칭** — 샘플 HWP에서 `Ⅱ.3 사업 세부 내용` 섹션만 25,663자(≈24K 토큰)로 다른 섹션(1~7K) 대비 4배. 단일 Sonnet 호출은 가능하지만 비용 불균형 발생. MVP는 그대로 통과, 향후 대형 섹션은 서브섹션(3-1/3-2) 기준으로 재분할 검토.

3. **Claude SDK의 `anthropic` 패키지 필요** — 기존 Phase C-3에서 이미 설치. 신규 의존성 없음.

4. **`python-multipart` 패키지 필요** — FastAPI의 `UploadFile + Form` 조합이 multipart/form-data 파싱에 이 패키지를 요구. requirements.txt에 추가 (2026-04-20 세션 3).

## 실패한 접근

1. **정량 힌트 초기 regex — 단일 키워드 매칭 (`"인증"` or `"등록"` 포함 시 hit)** → 실패
   - 원인: "사업자 등록 여부", "SNS 인증 이벤트" 같이 키워드만 포함된 문장이 대량 매칭되어 노이즈 히트 20개 이상 발생.
   - 해결: 키워드 + `제 XXX호` 번호 패턴을 AND 조건으로 묶어 정확한 인증/등록/특허 라인만 허용. 정량 힌트의 주 수집은 LLM이 담당하도록 역할 재분리.

2. **`_extract_section`이 LLM 응답의 `quantitative_hints` 필드를 무시하고 있었음** → 실패
   - 원인: 초기 구현에서 claims만 파싱하고 quantitative_hints는 파이프라인에서 drop. 프롬프트는 이 필드를 요구했으나 응답을 버리는 구조였음.
   - 해결: `_extract_section` 반환 튜플에 hints 추가(5-tuple), `_process_single`에서 claims·hints 모두 수집. 수정 후 단일 섹션(Ⅲ.1 업체 현황)에서 실적 2건·인증 2건·등록 1건·특허 1건·자격 2건 = 총 8건의 고품질 정량 힌트 획득.

## 테스트 결과

### 프로토타입 1 (단일 섹션) — 2026-04-20

| 항목 | 값 |
|------|-----|
| 대상 | `샘플 8 _ 경과원 ESG 교육/제안서(사본).hwp` → `Ⅲ.1 업체 현황` (6,150자) |
| 모델 | claude-sonnet-4-20250514 |
| input tokens | 7,547 |
| output tokens | 2,153 |
| 비용 | 76.9원 |
| 추출 claims | 8개 (Identity 1, USP 4, Story 2, Philosophy 1) |
| 정량 힌트 | 8개 (실적 2, 인증 2, 등록 1, 특허 1, 자격 2) |
| 신뢰도 분포 | 0.85~0.98, 평균 0.92 |

샘플 최고점 claim:
- `[USP 0.98]` "2020~2022년 창업진흥원 재도전 성공패키지 3년 연속 수행"
- `[Story 0.98]` "2020~2022년 경기도경제과학진흥원 창업 실전교육 3년 연속 수행"
- `[Methodology 0.95]` "PBL 기반 프로그램 『교육 → 과제 부여 → 참가자 개별 아이템 기준의 과제 작성 → 참가자가 작성한 자료 중심의 멘토링』 구성"

### 프로토타입 2 (전체 섹션) — 2026-04-20

| 항목 | 값 |
|------|-----|
| 대상 | 경과원 ESG 제안서 HWP 전체 (57,454자) |
| 섹션 분할 | 11개 → 스킵 3개 → 타깃 8개 |
| LLM 호출 | 8회 (Sonnet) |
| 총 input tokens | 62,814 |
| 총 output tokens | 9,892 |
| 총 비용 | **471.6원** (설계 예상 490원과 일치) |
| 소요 시간 | 175.7초 |
| 최종 claims (dedupe 후) | 34개 |
| 카테고리 분포 | USP 10 · Methodology 7 · Operational 6 · Story 5 · Philosophy 4 · Identity 2 |
| 태그 커버리지 | 32/34 claim (94%) |
| 평균 confidence | 0.92 |

JSON 출력: `tmp/extractor_proto2_output.json` (자기서술적, bidwatch 등 외부 소비 가능 포맷).

### 품질 평가

- 발주처 요구사항(RFP)이 회사 claim으로 섞여 들어온 케이스 **없음** — 프롬프트의 "발주처 요구사항 제외" 규칙이 잘 작동.
- 수치/연도/고유명사 포함률 높음 (예: "3년 연속(2021~2023)", "모집 134%·수료 165%", "290억원").
- 중복 claim은 확인 범위 내 없음 (단일 제안서). 다중 제안서 dedupe는 향후 테스트 필요.

### E2E 전 플로우 (세션 4) — 2026-04-20

| 단계 | 결과 |
|------|------|
| HTTP 업로드 (multipart) | src_0002 생성, DB 레코드 + 파일 저장 |
| 백그라운드 스레드 기동 | status pending→processing 전환 확인 |
| 섹션 분할 + LLM 호출 8회 | progress/current_section 실시간 업데이트 정상 (5초 폴링으로 UI 반영) |
| 추출 완료 | **36 claims · 482.7원 · 62,758/10,432 tokens** (프로토타입 2: 34 claims · 471.6원 — 일관성 확인) |
| 카테고리 분포 | USP 14·Methodology 8·Operational 5·Philosophy 5·Story 3·Identity 1 |
| Claims PATCH (편집) | `user_edited_statement` 저장, 원본 `statement` 보존 확인 |
| Bulk-verify (filter 0.9+) | 30/36 건 승인 |
| merge-suggestions | 단일 제안서라 0건 (정상) |
| 정량 힌트 | 44건 (실적/인증/등록/목표/예산 등) |
| UI 렌더링 | 소스 카드 1개(✅완료 · 비용/토큰), claim 카드 6개(미검토 필터), 툴바 카운트 "미검토 6 · 승인 30 · 숨김 0 · 전체 36" 정상 |

## 신규 의존성

없음. 기존 `anthropic`, `pyhwp`, `beautifulsoup4` (Phase C-1~C-3에서 이미 설치) 그대로 사용.

## 다음 단계

1. ~~**DB 스키마**~~ ✅ (세션 2 완료) — 3개 테이블 + 5개 인덱스.
2. ~~**API 엔드포인트**~~ ✅ (세션 3 완료) — `routers/extractor.py`, 11개 엔드포인트.
3. ~~**UI 1·2·3단계**~~ ✅ (세션 4 완료) — 설정 > 회사 프로필 > 역량 자산 탭.
4. ~~**E2E 검증**~~ ✅ (세션 4 완료) — 36 claims · 482.7원, 모든 플로우 통과.
5. ~~**BaseAIClient 확장 + Prompt caching**~~ ✅ (세션 5 완료) — 실측 482.7원 → 445.9원 (-7.6%). MVP 완료.

## MVP 완료 — 후속 작업 (Phase C 후반)

- 4단계: 공고 분석에 "사용된 claim" 연결 표시
- 5단계: 증분 업로드 diff 뷰
- Haiku 전환 품질 실험 (추출 비용 추가 절감)
- 섹션 스킵 목록 확장 (`Ⅱ.1 개요` 등 claim 수확률 낮은 섹션)
- 다중 제안서 dedupe 품질 검증
- 임베딩 기반 중복 병합 (현재 fuzzy string)
- 결과보고서/회사소개서용 추출기 (`ResultReportExtractor` 등)

### 잠재 과제 (세션 종료 시점 기록)

- `Ⅱ.3 사업 세부 내용` 섹션이 25K자로 비대칭. 향후 대형 섹션은 3-1/3-2 하위 단위로 재분할할지 결정 필요.
- `Ⅱ.1 개요` 섹션은 타깃에 포함되지만 RFP 재서술 성격이 강함. 실제 claim 수확량이 낮으면 스킵 목록 추가 검토.
- 다중 제안서 dedupe 정확도는 샘플 1건으로는 검증 불가. 최소 3건 업로드 시나리오에서 fuzzy similarity 0.85 임계치의 적절성 재평가 필요.
