# GT Editor — Ground Truth Editor

Phase D 회귀 테스트용 기준 데이터(Ground Truth)를 사람이 보정·저장하는 로컬 웹 도구.

## 전제

D-1 진단 덤프가 있어야 합니다:

```bash
python tools/check_parser.py --dump
```

→ `data/diag_d1/*.txt` + `_summary.json` 생성 (HWP 10건 파싱에 약 14분 소요)

## 실행

```bash
python tools/gt_editor/server.py
```

→ http://127.0.0.1:8088 접속 (메인 앱 8001과 별개 포트)

## 사용 흐름

1. 상단 드롭다운에서 파일 선택 (`✓` = GT 저장됨, `⚠️0섹션` = 현 파서 조용한 실패)
2. **"현 파서 섹션 불러오기"** 클릭 → 초안 생성 (ok 파일의 경우)
3. 좌측 본문 확인하며 보정:
   - 빠진 섹션 추가 (`＋ 섹션 추가`)
   - 잘못 잡힌 섹션 삭제 (`✕`)
   - 섹션 이름 수정
   - `skip` 체크: 분석 제외 섹션 (사업의 필요성·기대효과 등 claim 수확이 거의 없는 RFP 재서술 섹션)
4. **줄 번호 클릭으로 start_line 빠른 입력**:
   - 우측 섹션 행을 클릭해 선택(파란 배경)
   - 좌측 본문의 줄 번호 클릭 → 해당 섹션의 `start_line`에 자동 입력
   - 이름이 비어있으면 해당 줄 앞부분을 제안값으로 채움
5. `expected_claim_range` 설정 (예상 claim 개수 범위 — D-5 합격 기준용)
6. **저장** (Ctrl+S 또는 버튼)

## 저장 위치

`data/ground_truth/{파일명_stem}.json`

## JSON 포맷

```json
{
  "file": "제안서(사본).hwp",
  "expected_sections": [
    {"name": "Ⅰ.1 사업의 필요성", "level": 2, "start_line": 19, "skip": true},
    {"name": "Ⅱ.1 개요", "level": 2, "start_line": 238, "skip": false},
    {"name": "Ⅱ.3 사업 세부 내용", "level": 2, "start_line": 382, "skip": false}
  ],
  "expected_claim_range": [15, 40],
  "notes": "Ⅲ.1 ~ Ⅲ.3 회사 현황 섹션 중심으로 claim 수확 기대"
}
```

## 단축키

- `Ctrl+S` — 저장
- `Ctrl+Enter` — 섹션 추가

## 주의

- 파싱 실패 파일(PPTX 등)은 본문이 비어 있지만 GT는 저장 가능 (사람이 원본을 참고해 섹션 이름만 기록하는 용도)
- 본문 렌더 상한 6000줄 — 샘플 10건은 모두 이 범위 안 (최대 3656줄)
- 브라우저를 닫거나 다른 파일로 이동할 때 저장 안 된 수정사항은 경고
