"""수집기 기반 클래스 — 공통 UPSERT, 키워드 로딩, 상태 판정 패턴 통합"""

import logging
from database import get_connection

logger = logging.getLogger(__name__)

# 모든 수집기에 공통인 표준 10개 필드
STANDARD_FIELDS = [
    "source", "title", "organization", "category", "bid_no",
    "start_date", "end_date", "status", "url", "keywords",
]


class BaseCollector:
    """수집기 기반 클래스.

    서브클래스는 source_name과 fetch_announcements()를 구현해야 합니다.
    """

    source_name: str = ""

    def collect_and_save(self, keywords=None, days: int = 1, mode: str = "daily") -> dict:
        """키워드 로드 → 수집 → 후처리 → DB 저장.
        collect_all.py에서 키워드를 이미 로드해서 전달하므로
        keywords가 None인 경우(단독 실행)에만 DB에서 로드.
        """
        if keywords is None:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()

        logger.info(f"{self.source_name} 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일")
        notices = self.fetch_announcements(keywords, days=days)
        notices = self.post_filter(notices)
        inserted, updated = self.save_to_db(notices)
        return {
            "source": self.source_name,
            "collected": len(notices),
            "inserted": inserted,
            "updated": updated,
        }

    def fetch_announcements(self, keywords: list[str], days: int = 1) -> list[dict]:
        """API에서 공고 수집. 서브클래스에서 구현."""
        raise NotImplementedError

    def post_filter(self, notices: list[dict]) -> list[dict]:
        """수집 후 추가 필터링 훅. 기본은 패스스루."""
        return notices

    def save_to_db(self, notices: list[dict]) -> tuple[int, int]:
        """범용 UPSERT — 표준 필드 + notice dict의 나머지를 extra 필드로 동적 처리."""
        conn = get_connection()
        cursor = conn.cursor()
        inserted = 0
        updated = 0

        for n in notices:
            cursor.execute(
                "SELECT id FROM bid_notices WHERE source=? AND bid_no=?",
                (n["source"], n["bid_no"]),
            )
            existing = cursor.fetchone()

            # 표준 필드 외 추가 필드 추출
            extra_keys = [k for k in n if k not in STANDARD_FIELDS]
            extra_vals = [n.get(k, "") for k in extra_keys]

            if existing:
                # UPDATE: 표준 필드(source, bid_no 제외) + extra 필드
                update_fields = [f for f in STANDARD_FIELDS if f not in ("source", "bid_no")]
                all_update_fields = update_fields + extra_keys
                sets = ", ".join(f"{f}=?" for f in all_update_fields)
                sets += ", collected_at=datetime('now')"
                vals = [n.get(f, "") for f in update_fields] + extra_vals + [existing[0]]
                cursor.execute(f"UPDATE bid_notices SET {sets} WHERE id=?", vals)
                updated += 1
            else:
                # INSERT: 전체 필드
                all_fields = STANDARD_FIELDS + extra_keys
                placeholders = ", ".join(["?"] * len(all_fields))
                cols = ", ".join(all_fields)
                vals = [n.get(f, "") for f in STANDARD_FIELDS] + extra_vals
                cursor.execute(
                    f"INSERT INTO bid_notices ({cols}, collected_at) VALUES ({placeholders}, datetime('now'))",
                    vals,
                )
                inserted += 1

        conn.commit()
        conn.close()
        logger.info(f"{self.source_name} DB 저장: 신규 {inserted}건, 업데이트 {updated}건")
        return inserted, updated
