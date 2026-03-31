# Phase B-1: 검토요청 시 첨부파일 자동 수집 — 작업 로그

## 작업일: 2026-03-31

## 목표
검토요청/입찰대상 태그 설정 시 상세페이지를 백그라운드 스크래핑하여 첨부파일 목록을 자동 수집.
검토요청/입찰예정 리스트에서 첨부파일 다운로드 + 사유 표시 + 태그 변경 UI 제공.

## 구현 내역

### 1. 첨부파일 스크래핑 모듈 (신규)
- **파일:** `backend/collectors/attachment_scraper.py`
- 태그 설정 시 `threading.Thread(daemon=True)`로 백그라운드 실행
- 출처별 전용 파서 + 범용 휴리스틱 추출기

#### 출처별 파서
| 파서 | 대상 | 추출 방식 |
|------|------|----------|
| `_extract_kstartup` | K-Startup | `btn_wrap` 이전 형제 `<a>` 텍스트 + `/afile/fileDownload/` URL |
| `_extract_ccei` | CCEI/창조경제 | `a[href*="fileDown.download?uuid="]` 셀렉터 |
| `_extract_mss` | 중소벤처기업부 | `span.name` 파일명 + `a[href*="Download.do"]` URL |
| `_extract_generic` | 스크래퍼 48개 | 파일 확장자/다운로드 URL 패턴 + JS 링크 파서 |

#### JS 다운로드 링크 파서 (`_parse_js_download`)
- `fncFileDownload('bbs','파일명.hwp')` → 인천테크노파크
- `fileDown('5812')` → 한국지식재산보호원
- 파일 확장자 포함 문자열 범용 매칭

#### 세션 쿠키 자동 획득
- `_fetch_page()`: 메인페이지 먼저 접근하여 쿠키 획득 후 상세페이지 요청
- 중소벤처기업부(JSESSIONID 필요) 등 대응

### 2. 태그 설정 API 수정
- **파일:** `backend/main.py`
- `PUT /api/notice-tags/{notice_id}`: 검토요청/입찰대상 태그 시 백그라운드 스크래핑 트리거
- 스킵 조건: 나라장터(이미 첨부 있음), attachments 이미 존재, detail_url 없음
- 응답에 `attachment_scraping: true/false` 플래그 추가

### 3. 검토요청 사유 입력
- **파일:** `frontend/js/app.js`
- 검토요청 버튼 → 사유 입력 텍스트박스(15줄) + 취소/완료 버튼 표시
- 사유 미입력 시 alert 안내
- `setTag(id, '검토요청', memo)` — memo 파라미터 추가
- "📎 첨부파일 수집 중..." 표시 + 3초 후 모달 자동 새로고침

### 4. 검토요청 리스트 UI 개선
- **파일:** `frontend/review-list.html`
- 공고 행 아래 첨부파일 전용 행: `📎 파일명.hwp 📎 제안서.pdf` (없으면 "첨부파일 없음")
- 첨부파일 행 아래 사유+태그 버튼 행: `💬 사유 텍스트 [입찰예정] [제외]`
- 사유 줄바꿈 지원 (`\n` → `<br>`)
- `attachments → file_url` 폴백 (중소벤처기업부 등)

### 5. 입찰 예정 리스트 UI 개선
- **파일:** `frontend/bid-list.html`
- 동일하게 첨부파일 전용 행 추가 (attachments → file_url 폴백)

### 6. 권한 변경: 입찰대상/제외 태그 전체 사용자 허용
- **backend/main.py**: 검토요청/입찰대상/제외 → 모든 로그인 사용자, 낙찰/유찰만 관리자 권한
- **frontend/js/app.js**: 모달 입찰대상/제외 버튼 → 모든 사용자 표시
- **frontend/js/auth.js**: 입찰예정/제외 공고 메뉴 → 모든 사용자 표시
- **frontend/review-list.html**: 입찰예정/제외 버튼 → 모든 사용자 표시
- **frontend/excluded-list.html**: 복원 버튼 → 모든 사용자 표시
- **frontend/settings.html**: 계정 생성 시 "입찰예정/제외" 체크박스 제거
- **frontend/js/settings.js**: 계정 목록 권한 표시에서 "입찰" 제거, 기관목록 하단 경고 문구 추가

## 테스트 결과

| 출처 | 첨부 추출 | 비고 |
|------|----------|------|
| K-Startup | ✅ 4개 | btn_wrap 구조 파싱 |
| 중소벤처기업부 | ✅ 5개 | span.name + 세션 쿠키 |
| 제주콘텐츠진흥원 | ✅ 1개 | 범용 추출기 |
| 인천테크노파크 | ✅ 2개 | JS fncFileDownload 파서 |
| 한국지식재산보호원 | ✅ 2개 | JS fileDown 파서 |
| 나라장터 | ✅ 스킵 | API에서 이미 제공 |

## 파일 목록

| 파일 | 작업 |
|------|------|
| `backend/collectors/attachment_scraper.py` | 신규 |
| `backend/main.py` | 수정 |
| `frontend/js/app.js` | 수정 |
| `frontend/js/auth.js` | 수정 |
| `frontend/js/settings.js` | 수정 |
| `frontend/review-list.html` | 수정 |
| `frontend/bid-list.html` | 수정 |
| `frontend/excluded-list.html` | 수정 |
| `frontend/settings.html` | 수정 |
| `work_log2/plan_2.md` | 수정 |
| `work_log2/log_phaseB1.md` | 신규 |
