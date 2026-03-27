import sqlite3
import os
from config import DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

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

    # 설정 초기값 삽입 (없을 때만)
    defaults = [
        ("status_filter", "ongoing", "진행중만=ongoing, 전체=all"),
        ("date_range_days", "30", "최근 N일 이내 공고 표시"),
        ("sort_order", "deadline", "마감임박순=deadline, 최신순=latest"),
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
