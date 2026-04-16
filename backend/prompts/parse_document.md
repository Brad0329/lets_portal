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

```json
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
