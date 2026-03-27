# Phase 3 작업 로그

## 기간
2026-03-28

## 목표
DB 스키마 확장 + 수집기 새 필드 매핑 + 프론트엔드 상세 모달 확장 + 나라장터 API 테스트

---

## 완료 항목

### 3-1: DB 스키마 확장 (Step 11)
- `bid_notices` 테이블에 15개 컬럼 추가:
  - `file_url` — 첨부파일 URL/JSON (중기부: 다중 파일 JSON 배열)
  - `detail_url` — 상세페이지 URL (K-Startup)
  - `apply_url` — 신청 URL (K-Startup)
  - `region` — 지원 지역 (K-Startup)
  - `target` — 지원 대상 (K-Startup)
  - `content` — 공고 내용/사업 개요
  - `budget` — 지원 규모 (중기부)
  - `contact` — 문의처 (K-Startup)
  - `est_price` — 추정 가격 (나라장터)
  - `apply_method` — 접수 방법 (K-Startup)
  - `biz_enyy` — 창업 연차 조건 (K-Startup)
  - `target_age` — 대상 연령 (K-Startup)
  - `department` — 담당부서 (K-Startup)
  - `excl_target` — 제외 대상 (K-Startup)
  - `biz_name` — 통합공고 사업명 (K-Startup)
- `database.py`의 `init_db()`에 ALTER TABLE 마이그레이션 로직 추가 (이미 존재하면 무시)
- `models.py` BidNotice 데이터클래스에 확장 필드 추가

### 3-2: 수집기 매핑 수정 (Step 12)
- **kstartup.py**: 12개 확장 필드 매핑 (detail_url, apply_url, region, target, content, contact, apply_method, biz_enyy, target_age, department, excl_target, biz_name)
  - HTML 엔티티 디코딩 (`html.unescape`) + `<br>` 태그 → 줄바꿈 처리
- **mss_biz.py**: file_url(다중 파일 JSON), content, budget 매핑
  - `findall("fileName"/"fileUrl")`로 첨부파일 전체 수집 → JSON 배열 저장
  - HTML 태그 제거 (`re.sub`), 엔티티 디코딩
- **nara.py**: est_price (presmptPrce) 매핑 추가

### 3-3: 프론트엔드 상세 모달 확장 (Step 13)
- 모달에 풍부한 상세 정보 표시:
  - 사업명, 지원 지역, 지원 대상, 대상 연령, 창업 연차, 제외 대상
  - 접수 방법, 담당부서, 문의처, 지원 규모, 추정 가격, 사업 개요
- 첨부파일: JSON 배열 파싱 → 파일별 개별 다운로드 버튼 (파일명 표시)
- 링크 버튼 분리: 공고 바로가기(파란색) / 신청 페이지(녹색) / 첨부파일(주황색)
- 리스트 행 클릭 시 외부 이동 제거 → 모달만 표시

### 3-4: 공고 상세 API (실시간 보충)
- `GET /api/notices/{notice_id}` 단건 상세 조회 API 추가
- K-Startup 공고 중 확장 필드가 비어있으면 API 실시간 호출하여 보충
- 조회 결과는 DB에 캐시 → 다음 조회부터 즉시 표시
- 프론트엔드: 모달 열 때 상세 API 비동기 호출 → 기본 정보 즉시 표시 후 확장 필드 자동 갱신

### 3-5: 나라장터 API 테스트 (Step 14)
- 500 Server Error — 조달청 서버 아직 복구되지 않음
- 수집기 코드는 준비 완료, 서버 복구 후 자동 수집 시 정상 동작 예상
- 나라장터 목록 API에는 사업개요/첨부파일 URL 없음 → Phase 4에서 상세 API 연동 예정

### 3-6: 재수집 실행 (Step 15)
- **K-Startup**: 267건 수집, 확장 필드 정상 반영 (사업명/지역/대상/연령/연차/접수방법/담당부서/문의처/사업개요 모두 채워짐)
- **중소벤처기업부**: 62건 수집, 다중 파일 JSON 저장 확인 (최대 3개 파일 공고 확인)

---

## 추가/변경된 파일
```
backend/
  database.py         (수정) 15개 컬럼 ALTER TABLE 마이그레이션
  models.py           (수정) BidNotice 확장 필드 추가
  main.py             (수정) GET /api/notices/{id} 상세 API + 실시간 보충 로직
  collectors/
    kstartup.py       (수정) 12개 확장 필드 매핑 + HTML 디코딩 + save_to_db
    mss_biz.py        (수정) 다중 파일 JSON 수집 + HTML 태그 제거 + save_to_db
    nara.py           (수정) est_price 매핑 + save_to_db
frontend/
  js/app.js           (수정) 상세 API 연동 모달 + 다중 파일 버튼 + 행 클릭 모달만
  css/style.css       (수정) 신청/다운로드 버튼 + 사업개요 박스 스타일
```

---

## 현재 기능 요약
| 기능 | 상태 |
|------|------|
| 메인 페이지 (공고 리스트) | ✅ |
| 검색 + 필터 + 페이지네이션 | ✅ |
| 상세보기 모달 (풍부한 상세 정보) | ✅ |
| 공고 상세 API (실시간 보충) | ✅ |
| 설정 페이지 (키워드/기간/상태) | ✅ |
| 키워드 추가/삭제 | ✅ |
| K-Startup 수집기 (12개 확장 필드) | ✅ 267건 |
| 중소벤처기업부 수집기 (다중 파일 포함) | ✅ 62건 |
| 나라장터 수집기 (est_price) | ⏸️ 서버 미복구 |
| 첨부파일 다운로드 (다중 파일) | ✅ 중기부 |
| 자동 수집 스케줄러 | ✅ 매일 9시/14시 |
