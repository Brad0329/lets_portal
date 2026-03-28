# Phase A: 입찰 예정 공고 관리

## 작업 일자: 2026-03-28

## 완료 항목

### 1. DB 스키마 확장
- `notice_tags` 테이블 생성
  - id, notice_id(UNIQUE), tag, tagged_by(FK→users), memo
  - created_at, updated_at
  - 공고 1건당 태그 1개 (UNIQUE 제약)
- 유효 태그: `입찰대상`, `제외`, `검토중`, `낙찰`, `유찰`

### 2. 태그 관리 API
| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/notice-tags/{notice_id}` | GET | 공고 태그 조회 |
| `/api/notice-tags/{notice_id}` | PUT | 태그 설정 (UPSERT) — `perm_bid_tag` 권한 필요 |
| `/api/notice-tags/{notice_id}` | DELETE | 태그 해제 (복원) — `perm_bid_tag` 권한 필요 |
| `/api/notices/tagged` | GET | 태그별 공고 목록 (검색/필터/페이지네이션) |

### 3. 기존 API 수정
- `/api/notices` — 제외 태그 공고 자동 숨김 (WHERE절에 NOT IN 조건)
- `/api/notices/{notice_id}` — 상세 조회 시 태그 정보(tag, tagged_by_name, tagged_at, tag_memo) 포함
- `/api/notices/stats` — `tag_stats` 필드 추가 (태그별 건수)

### 4. 모달에 태그 버튼 추가 (app.js)
- `perm_bid_tag` 권한 사용자에게 태그 버튼 표시
  - `입찰대상`, `검토중`, `제외` 버튼 (현재 태그 활성 표시)
  - 태그 해제 버튼 (태그가 있을 때만 표시)
- 태그 설정/해제 시 모달 즉시 갱신
- 제외 태그 시 공고 리스트 자동 새로고침
- `setTag()`, `removeTag()`, `getTagClass()` 함수 추가

### 5. 입찰 예정 공고 리스트 (bid-list.html)
- 입찰대상 태그 공고만 표시
- 검색/필터: 키워드, 출처, 정렬(태그일/마감/최신)
- 테이블: 출처, 공고명, 기관, 마감일, 상태, 태그
- 클릭 시 상세 모달 (태그 변경 가능)
- 페이지네이션

### 6. 제외된 공고 리스트 (excluded-list.html)
- 제외 태그 공고만 표시
- 검색/필터: 키워드, 출처, 정렬(제외일/마감/최신)
- 복원 버튼 (`perm_bid_tag` 권한자만) — 클릭 시 태그 해제 → 일반 목록 복귀
- 클릭 시 상세 모달

### 7. 네비게이션 바 업데이트 (auth.js)
- 메뉴 추가: `입찰 예정` (📌), `제외 공고` (🚫)
- 제외 공고 메뉴: 관리자 또는 `perm_bid_tag` 권한자만 표시
- 입찰 예정: 모든 로그인 사용자 접근 가능

### 8. 대시보드 업데이트 (dashboard.html)
- 카드 추가: `입찰 예정 공고` (입찰대상 건수), `제외된 공고` (제외 건수)
- 태그 건수는 `/api/notices/stats`의 `tag_stats`에서 가져옴
- 4개 카드: 공고 중인 사업 → 입찰 예정 → 제외된 공고 → 전체 공고

### 9. CSS 추가 (style.css)
- `.tag-badge` — 태그 배지 (입찰대상=파랑, 제외=회색, 검토중=노랑, 낙찰=초록, 유찰=빨강)
- `.modal-tag-actions` — 모달 내 태그 버튼 그룹
- `.tag-btn` — 태그 버튼 (활성/비활성 스타일)

### 10. 정적 페이지 라우트 추가 (main.py)
- `/bid-list.html`, `/excluded-list.html` 라우트 등록

## 파일 변경 목록

| 파일 | 변경 유형 |
|------|----------|
| `backend/database.py` | 수정 — notice_tags 테이블 추가 |
| `backend/main.py` | 수정 — 태그 API, tagged 목록, 제외 숨김, 상세 태그 포함, 통계 태그, 페이지 라우트 |
| `frontend/js/app.js` | 수정 — 태그 버튼, setTag/removeTag/getTagClass 함수 |
| `frontend/js/auth.js` | 수정 — 네비게이션 메뉴에 입찰예정/제외 추가 |
| `frontend/css/style.css` | 수정 — 태그 배지, 태그 버튼 스타일 |
| `frontend/dashboard.html` | 수정 — 입찰예정/제외 카드, 태그 통계 로드 |
| `frontend/bid-list.html` | 신규 — 입찰 예정 공고 리스트 페이지 |
| `frontend/excluded-list.html` | 신규 — 제외된 공고 리스트 (복원 기능) |

## 테스트 결과
- 태그 설정 (입찰대상/제외/검토중) → 성공 ✅
- 태그 조회 → 태그 정보 + 설정자 이름 반환 ✅
- 입찰대상 태그 목록 → total/notices 정상 ✅
- 제외된 공고 일반 목록에서 숨김 → 정상 ✅
- 태그 해제 (복원) → 일반 목록에 다시 표시 ✅
- 통계 API tag_stats → 태그별 건수 정상 ✅
- 상세 조회 태그 정보 포함 ✅

## 추가 수정: 검토요청 워크플로우

### 워크플로우
```
(태그 없음) → 검토요청(실무자) → 입찰대상 또는 제외(관리자)
```

### 변경 사항
- **검토요청 태그** 추가 — 모든 로그인 사용자가 설정 가능
- **모달 버튼 권한 분리**: 실무자=검토요청만, 관리자(perm_bid_tag)=검토요청+입찰대상+제외
- **태그 해제 권한**: 검토요청은 본인 해제 가능, 입찰대상/제외는 관리자만
- **검토요청 공고리스트** (`review-list.html`) 페이지 추가 — 요청자 표시
- **네비게이션**: 검토요청 메뉴 추가 (모든 사용자)
- **대시보드**: 검토요청 카드 추가

### 추가 파일 변경

| 파일 | 변경 유형 |
|------|----------|
| `frontend/review-list.html` | 신규 — 검토요청 공고 리스트 |
| `backend/main.py` | 수정 — 태그 권한 분리, review-list 라우트 |
| `frontend/js/app.js` | 수정 — 모달 버튼 역할별 분리 |
| `frontend/js/auth.js` | 수정 — 검토요청 메뉴, 입찰예정 관리자만 |
| `frontend/dashboard.html` | 수정 — 검토요청 카드 추가 |

## 권한 구조

| 기능 | 관리자 | perm_bid_tag | 일반 실무자 |
|------|--------|-------------|-----------|
| 검토요청 버튼 | O | O | O |
| 검토요청 리스트 | O | O | O |
| 입찰대상/제외 버튼 | O | O | X |
| 입찰 예정 리스트/메뉴 | O | O | X |
| 제외 리스트/메뉴 | O | O | X |
| 검토요청 태그 해제 | O | O | 본인만 |
| 입찰대상/제외 태그 해제 | O | O | X |

## 다음 단계: Phase B
- 입찰 준비 페이지 UI
- 체크리스트 기능
- 파일 업로드/관리
