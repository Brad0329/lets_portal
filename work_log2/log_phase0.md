# Phase 0: 기반 작업 — 로그인/인증 + 메뉴 구조 + 대시보드

## 작업 일자: 2026-03-28

## 완료 항목

### 1. DB 스키마 확장
- `users` 테이블 생성
  - id, username(UNIQUE), name, password_hash, role(admin/staff)
  - must_change_pw (첫 로그인 시 비밀번호 변경 강제)
  - perm_bid_tag, perm_display, perm_keyword, perm_org (추가 권한 플래그)
  - created_at, updated_at
- `sessions` 테이블 생성
  - token(PK), user_id(FK), created_at, expires_at
- 초기 관리자 계정 자동 생성: `admin` / `admin1234` (must_change_pw=0)

### 2. 인증 시스템 (backend/auth.py)
- 세션 기반 인증 (쿠키 `session_token`, 24시간 유효)
- `create_session()` — 로그인 시 토큰 발급
- `get_current_user()` — 쿠키에서 세션 확인, 만료 체크
- `require_login()` / `require_admin()` — 엔드포인트 보호
- `has_permission(user, perm)` — 세분화된 권한 체크
- bcrypt 비밀번호 해싱 (`hash_password`, `verify_password`)
- 만료 세션 자동 정리 (매일 새벽 3시 스케줄)

### 3. 인증 API (main.py)
| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/auth/login` | POST | 로그인 → 세션 쿠키 발급 |
| `/api/auth/logout` | POST | 로그아웃 → 세션/쿠키 삭제 |
| `/api/auth/me` | GET | 현재 로그인 사용자 정보 |
| `/api/auth/change-password` | POST | 비밀번호 변경 |

### 4. 계정 관리 API (관리자 전용)
| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/users` | GET | 사용자 목록 조회 |
| `/api/users` | POST | 계정 생성 (기본PW '1234', must_change_pw=1) |
| `/api/users/{id}` | PUT | 계정 정보 수정 (이름, 역할, 권한) |
| `/api/users/{id}/reset-password` | POST | 비밀번호 '1234'로 초기화 |
| `/api/users/{id}` | DELETE | 계정 삭제 (자기 자신 불가) |

### 5. 기존 API 권한 적용
- 모든 조회 API (`/api/notices`, `/api/notices/stats`, `/api/notices/{id}`) → `require_login`
- 설정 변경 (`/api/settings/{key}`) → `perm_display` 권한 필요
- 키워드 관리 (`/api/keywords/*`) → `perm_keyword` 권한 필요
- 기관 목록 (`/api/organizations`) → `perm_org` 권한 필요
- 수집 실행 (`/api/collect`) → `require_admin`

### 6. 프론트엔드 — 로그인 페이지 (login.html)
- ID/PW 입력 폼
- 로그인 성공 → 대시보드로 이동
- `must_change_pw` 사용자 → 비밀번호 변경 폼 표시
- 비밀번호 변경 완료 → 대시보드 이동
- 이미 로그인 상태면 자동 리다이렉트

### 7. 프론트엔드 — 네비게이션 바 (css/navbar.css, js/auth.js)
- 공통 모듈 `auth.js`: `checkAuth()`, `renderNavbar()`, `doLogout()`
- 상단 네비게이션 바: LETS 로고 | 대시보드 | 공고 중인 사업 | 설정 | 사용자 정보 | 로그아웃
- 역할별 메뉴 표시 (설정 메뉴 — 관리자 또는 관련 권한 보유자만)
- 현재 페이지 active 표시
- 반응형 지원

### 8. 프론트엔드 — 대시보드 (dashboard.html)
- 공고 현황 카드: 진행중 공고 / 전체 공고 (클릭 시 목록 이동)
- 출처별 현황 (K-Startup, 중소벤처기업부, 나라장터)
- 시스템 정보 (마지막 수집 시간, 스케줄, 로그인 사용자)

### 9. 기존 페이지 수정
- `index.html`: 기존 header 제거, navbar + auth.js 적용
- `app.js`: `checkAuth()` 호출 추가
- `settings.html`: navbar 적용, 계정 관리 섹션 추가, 비밀번호 변경 섹션 추가
- `settings.js`: `checkAuth()` + 권한별 섹션 표시 + 계정 CRUD + 비밀번호 변경

## 파일 변경 목록

| 파일 | 변경 유형 |
|------|----------|
| `backend/database.py` | 수정 — users/sessions 테이블, bcrypt 해싱 |
| `backend/auth.py` | 신규 — 인증/세션 관리 모듈 |
| `backend/main.py` | 수정 — 인증 API, 계정 관리 API, 권한 체크 |
| `backend/requirements.txt` | 수정 — bcrypt 추가 |
| `frontend/login.html` | 신규 — 로그인 + 비밀번호 변경 |
| `frontend/dashboard.html` | 신규 — 대시보드 |
| `frontend/js/auth.js` | 신규 — 공통 인증/네비게이션 |
| `frontend/css/navbar.css` | 신규 — 네비게이션 바 스타일 |
| `frontend/index.html` | 수정 — navbar 적용, header 숨김 |
| `frontend/js/app.js` | 수정 — checkAuth() 추가 |
| `frontend/settings.html` | 수정 — navbar, 계정관리, PW변경 섹션 |
| `frontend/js/settings.js` | 수정 — 인증 + 계정 CRUD + PW변경 |

## 테스트 결과
- 비로그인 상태 → API 401 응답 ✅
- admin/admin1234 로그인 → 세션 쿠키 발급 ✅
- 로그인 후 /api/auth/me → 사용자 정보 반환 ✅
- 로그인 후 /api/notices → 정상 접근 ✅
- 계정 생성 (기본PW '1234') → 성공 ✅
- 사용자 목록 조회 → 2명 표시 ✅
- 로그아웃 → 세션 삭제 ✅
- 로그아웃 후 접근 → 401 ✅

## 초기 계정 정보
- 관리자: `admin` / `admin1234`
- 신규 생성 계정: 기본 비밀번호 `1234` → 첫 로그인 시 변경 강제

## 역할 및 권한 구조

| 권한 | 관리자 | 실무자(기본) | 실무자(권한부여) |
|------|--------|------------|----------------|
| 공고 조회 | O | O | O |
| 대시보드 | O | O | O |
| 입찰예정/제외 | O | X | perm_bid_tag |
| 표시 설정 | O | X | perm_display |
| 키워드 관리 | O | X | perm_keyword |
| 기관 목록 | O | X | perm_org |
| 계정 관리 | O | X | X |
| 수집 실행 | O | X | X |

## 다음 단계: Phase A
- 태그 테이블 설계 + API
- 모달에 '입찰예정' / '제외' 버튼
- 입찰 예정 공고 리스트 페이지
- 제외된 공고 리스트 페이지
