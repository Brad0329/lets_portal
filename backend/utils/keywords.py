"""키워드 매칭/로딩 유틸리티"""

from database import get_connection


def match_keywords(search_text: str, keywords: list[str]) -> list[str]:
    """텍스트에서 매칭되는 키워드 목록 반환.
    search_text는 호출 측에서 lower() 처리하여 전달.
    """
    return [kw for kw in keywords if kw.lower() in search_text]


def load_active_keywords(source_id=None) -> list[str]:
    """DB에서 활성 키워드 로드.
    source_id=None이면 공통 키워드만,
    source_id 지정 시 공통 + 해당 출처 키워드.
    """
    conn = get_connection()
    cursor = conn.cursor()

    if source_id is not None:
        # 공통 키워드 + 출처 전용 키워드
        cursor.execute(
            "SELECT keyword FROM keywords WHERE is_active=1 AND (source_id IS NULL OR source_id=?)",
            (source_id,),
        )
    else:
        cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")

    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords
