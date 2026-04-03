# release/v1: exe 빌드 및 납품 준비 — 작업 로그

## 작업일: 2026-04-02

## 목표
현재 시스템을 PyInstaller exe로 패키징하여 다른 회사 PC에서 소스 없이 실행 가능하도록 납품 준비.

## 구현 내역

### 1. Git 브랜치 분기
- `v1.0` 태그: 커밋 `ebb7be9` (Phase B-1 완료 시점)
- `release/v1` 브랜치: v1.0에서 분기 → 납품용 안정 버전
- `master`: 계속 개발 (AI 등 새 기능)
- 공통 수정 시 cherry-pick으로 양쪽 반영

### 2. exe 호환 경로 수정
- **config.py**: `sys.frozen` 감지하여 exe/개발 환경 자동 분기
  - `BASE_DIR`, `DB_PATH`, `FRONTEND_DIR`, `COLLECTORS_DIR` 변수 추가
- **main.py**: `frontend_dir`을 `config.FRONTEND_DIR` 사용, `uvicorn.run(app, ...)` exe 호환
- **generic_scraper.py**: `CONFIGS_PATH`를 `config.COLLECTORS_DIR` 사용

### 3. PyInstaller 빌드
- `build_exe.spec`: 빌드 설정 파일 (hiddenimports 포함)
- 결과: `lets_server.exe` (약 72MB)
- `.gitignore`: `build/`, `dist/`, `release/`, `*.spec` 제외

### 4. 포트 번호 .env 설정
- **main.py**: `PORT` 환경변수로 포트 설정 (기본값 8000)
- `.env`에 `PORT=8001` 추가
- 서버 시작 시 콘솔에 포트 번호 출력

### 5. 공통 키워드 콤마 일괄 입력
- **main.py**: `POST /api/keywords/common`에서 콤마 분리 다건 입력 지원
- **source-list.html**: `input` → `textarea` (600px, 3행)
- 안내문: "콤마를 구분자로 단어를 입력하세요"
- 다건 결과 alert (추가 N개, 중복 N개 건너뜀)

### 6. 공고 데이터 삭제 기능
- **main.py**: `DELETE /api/notices/old?before_date=YYYY-MM-DD`
  - 입찰공고게시일 기준 일괄 삭제
  - `notice_tags`에 등록된 공고(검토요청/입찰대상/제외 등)는 보존
  - 관리자 권한 필요
- **source-list.html**: 공고수집 출처 하단에 삭제 카드 추가
- **source-list.js**: `deleteOldNotices()` — confirm 경고 후 실행

### 7. 납품 폴더 구성
- 위치: `release/LETSEDU_DEPLOY/`
- 포함: lets_server.exe, .env, frontend/, data/, collectors/, main_manual.md, 초기키워드.txt

## 테스트 결과

| 항목 | 결과 |
|------|------|
| exe 실행 | 정상 (콘솔 서버 시작) |
| http://localhost:8000/ | HTTP 200 |
| login.html | HTTP 200 |
| DB 자동 생성 | portal.db 81KB 생성 |
| 인증 체크 | API "로그인 필요" 정상 |

## 커밋 이력 (release/v1)

| 커밋 | 내용 |
|------|------|
| `3dc7254` | PyInstaller exe 빌드 지원 — 경로 자동 감지 |
| `3015275` | 공통 키워드 69개 자동 등록 + 설치 매뉴얼 |
| `00689cd` | 공통 키워드 콤마 일괄 입력 + 하드코딩 키워드 제거 |
| `b94f799` | .gitignore: release/ 폴더 제외 |
| `d448aa4` | 포트 번호 .env 설정 지원 (PORT=8001) |
| `6508fe9` | 공고 데이터 삭제 기능 — 날짜 기준 일괄 삭제 |

## 파일 목록

| 파일 | 작업 |
|------|------|
| `backend/config.py` | 수정 (BASE_DIR 자동 감지) |
| `backend/main.py` | 수정 (경로, PORT, 콤마 키워드, 삭제 API) |
| `backend/database.py` | 수정 (하드코딩 키워드 추가 후 제거) |
| `backend/collectors/generic_scraper.py` | 수정 (CONFIGS_PATH) |
| `frontend/source-list.html` | 수정 (textarea, 삭제 카드) |
| `frontend/js/source-list.js` | 수정 (다건 키워드, 삭제 함수) |
| `.gitignore` | 수정 (build, dist, release, spec 제외) |
| `build_exe.spec` | 신규 (PyInstaller 설정) |
| `main_manual.md` | 신규 → release/LETSEDU_DEPLOY/로 이동 |
