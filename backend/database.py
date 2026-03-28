import sqlite3
import os
import bcrypt
from config import DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            must_change_pw INTEGER DEFAULT 1,
            perm_bid_tag INTEGER DEFAULT 0,
            perm_display INTEGER DEFAULT 0,
            perm_keyword INTEGER DEFAULT 0,
            perm_org INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    # 초기 관리자 계정 (admin / admin1234)
    cursor.execute("SELECT id FROM users WHERE username='admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, name, password_hash, role, must_change_pw) VALUES (?, ?, ?, ?, ?)",
            ("admin", "관리자", hash_password("admin1234"), "admin", 0),
        )

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS bid_notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            organization TEXT,
            category TEXT,
            bid_no TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            url TEXT,
            keywords TEXT,
            collected_at TEXT,
            UNIQUE(source, bid_no)
        );

        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            page_category TEXT,
            url TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            keyword_group TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS display_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT NOT NULL UNIQUE,
            setting_value TEXT NOT NULL,
            description TEXT,
            updated_at TEXT
        );
    """)

    # Phase 3: bid_notices 스키마 확장 (9개 컬럼 추가)
    new_columns = [
        ("file_url", "TEXT"),       # 첨부파일 URL (중기부 fileUrl)
        ("detail_url", "TEXT"),     # 상세페이지 URL (K-Startup detl_pg_url)
        ("apply_url", "TEXT"),      # 신청 URL (K-Startup biz_aply_url)
        ("region", "TEXT"),         # 지원 지역 (K-Startup supt_regin)
        ("target", "TEXT"),         # 지원 대상 (K-Startup aply_trgt)
        ("content", "TEXT"),        # 공고 내용 요약
        ("budget", "TEXT"),         # 지원 규모/예산 (중기부 supt_scale)
        ("contact", "TEXT"),        # 문의처 (K-Startup prch_cnpl_no)
        ("est_price", "TEXT"),      # 추정 가격 (나라장터 presmptPrce)
        ("apply_method", "TEXT"),   # 접수 방법 (K-Startup 온라인/방문 등)
        ("biz_enyy", "TEXT"),       # 창업 연차 조건 (K-Startup)
        ("target_age", "TEXT"),     # 대상 연령 (K-Startup)
        ("department", "TEXT"),     # 담당부서 (K-Startup biz_prch_dprt_nm)
        ("excl_target", "TEXT"),    # 제외 대상 (K-Startup aply_excl_trgt_ctnt)
        ("biz_name", "TEXT"),       # 통합공고 사업명 (K-Startup intg_pbanc_biz_nm)
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE bid_notices ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass  # 이미 존재하면 무시

    # 설정 초기값 삽입 (없을 때만)
    defaults = [
        ("status_filter", "ongoing", "진행중만=ongoing, 전체=all"),
        ("date_range_days", "30", "입찰공고 최근 N일 이내 표시"),
        ("sort_order", "deadline", "마감임박순=deadline, 입찰공고일 최신순=latest"),
        ("items_per_page", "20", "페이지당 표시 건수"),
    ]
    for key, value, desc in defaults:
        cursor.execute(
            "INSERT OR IGNORE INTO display_settings (setting_key, setting_value, description, updated_at) VALUES (?, ?, ?, datetime('now'))",
            (key, value, desc),
        )

    conn.commit()
    conn.close()


def import_excel_data(excel_path):
    """엑셀에서 기관 목록 + 키워드를 DB에 임포트"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True)
    conn = get_connection()
    cursor = conn.cursor()

    # Sheet1: 기관 목록 (2행부터 데이터, 1행은 헤더)
    ws1 = wb.worksheets[0]
    rows = list(ws1.iter_rows(min_row=3, values_only=True))  # 3행부터 (1행 제목, 2행 헤더)
    cursor.execute("DELETE FROM organizations")
    for row in rows:
        no, category, name, active, page_cat, url = row[:6]
        if not name or not url:
            continue
        is_active = 1 if active == "O" else 0
        cursor.execute(
            "INSERT INTO organizations (name, category, page_category, url, is_active) VALUES (?, ?, ?, ?, ?)",
            (str(name).strip(), str(category).strip() if category else None, str(page_cat).strip() if page_cat else None, str(url).strip(), is_active),
        )

    # Sheet2: 키워드 (2행부터 데이터)
    ws2 = wb.worksheets[1]
    header_row = list(ws2.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    groups = [str(h).strip() if h else f"그룹{i}" for i, h in enumerate(header_row[1:], 1)]

    cursor.execute("DELETE FROM keywords")
    for row in ws2.iter_rows(min_row=3, values_only=True):
        for i, keyword in enumerate(row[1:]):
            if keyword and str(keyword).strip():
                group_name = groups[i] if i < len(groups) else "기타"
                cursor.execute(
                    "INSERT INTO keywords (keyword, keyword_group, is_active) VALUES (?, ?, 1)",
                    (str(keyword).strip(), group_name),
                )

    conn.commit()
    conn.close()
    wb.close()


if __name__ == "__main__":
    import sys

    init_db()
    print("DB 초기화 완료")

    excel_path = os.path.join(os.path.dirname(__file__), "..", "●입찰 공고(사업 공고) 기관별 입찰 정리.xlsx")
    if os.path.exists(excel_path):
        import_excel_data(excel_path)
        print("엑셀 데이터 임포트 완료")

        # 확인
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM organizations")
        print(f"  기관: {cur.fetchone()[0]}건")
        cur.execute("SELECT COUNT(*) FROM keywords")
        print(f"  키워드: {cur.fetchone()[0]}건")
        cur.execute("SELECT COUNT(*) FROM display_settings")
        print(f"  설정: {cur.fetchone()[0]}건")
        conn.close()
    else:
        print(f"엑셀 파일 없음: {excel_path}")
