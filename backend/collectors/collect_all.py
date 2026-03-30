"""
전체 수집기 실행 (K-Startup + 중소벤처기업부 + 나라장터 + 창조경제혁신센터 + 개별기관 스크래퍼)
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.kstartup import collect_and_save as collect_kstartup
from collectors.mss_biz import collect_and_save as collect_mss
from collectors.nara import collect_and_save as collect_nara
from collectors.ccei import collect_and_save as collect_ccei
from collectors.generic_scraper import collect_all_scrapers
from database import get_connection

logger = logging.getLogger(__name__)

# collector_type → 수집기 함수 매핑
COLLECTOR_MAP = {
    "nara": collect_nara,
    "kstartup": collect_kstartup,
    "mss_biz": collect_mss,
    "ccei": collect_ccei,
}

# collector_type → 출처명 매핑 (에러 시 fallback)
SOURCE_NAME_MAP = {
    "nara": "나라장터",
    "kstartup": "K-Startup",
    "mss_biz": "중소벤처기업부",
    "ccei": "창조경제혁신센터",
}


def _load_keywords_for_source(source_id: int) -> list[str]:
    """공통 키워드 + 출처 전용 키워드 합산 로드"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT keyword FROM keywords WHERE is_active=1 AND (source_id IS NULL OR source_id=?)",
        (source_id,),
    )
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords


def collect_by_source(source_id: int, days: int = 1, mode: str = "daily") -> dict:
    """개별 출처 수집 실행. days: 수집할 기간(일수). mode는 하위 호환용."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collect_sources WHERE id=?", (source_id,))
    source = cursor.fetchone()
    conn.close()

    if not source:
        return {"error": f"출처 ID {source_id}를 찾을 수 없습니다."}

    source = dict(source)
    ctype = source["collector_type"]
    collector_fn = COLLECTOR_MAP.get(ctype)

    if not collector_fn:
        if ctype == "scraper":
            return {"error": "스크래퍼 출처는 일괄 수집(/api/scrapers/collect)을 사용하세요."}
        return {"error": f"수집기 타입 '{ctype}'에 대한 수집기가 없습니다."}

    # 키워드 로드
    keywords = _load_keywords_for_source(source_id)
    if not keywords:
        return {"source": source["name"], "collected": 0, "inserted": 0, "updated": 0, "error": "활성 키워드가 없습니다."}

    try:
        result = collector_fn(keywords=keywords, days=days)
        # 수집 상태 갱신
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE collect_sources SET last_collected_at=datetime('now'), last_collected_count=? WHERE id=?",
            (result.get("collected", 0), source_id),
        )
        conn.commit()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"❌ {source['name']} 수집 실패: {e}")
        return {"source": source["name"], "collected": 0, "inserted": 0, "updated": 0, "error": str(e)}


def collect_all():
    """모든 활성 출처 수집 실행 (API 출처 + 스크래퍼)"""
    conn = get_connection()
    cursor = conn.cursor()
    # API 기반 출처만 (scraper 타입 제외)
    cursor.execute("SELECT id FROM collect_sources WHERE is_active=1 AND collector_type != 'scraper' ORDER BY id")
    source_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    results = []
    for sid in source_ids:
        r = collect_by_source(sid)
        results.append(r)
        src_name = r.get("source", f"ID={sid}")
        if r.get("error"):
            logger.error(f"❌ {src_name}: {r['error']}")
        else:
            logger.info(f"✅ {src_name}: {r['collected']}건 수집")

    # 스크래퍼 일괄 실행
    try:
        scraper_result = collect_all_scrapers(mode="daily")
        results.append({
            "source": "개별기관 스크래퍼",
            "collected": scraper_result.get("collected", 0),
            "inserted": scraper_result.get("inserted", 0),
            "updated": 0,
            "matched": scraper_result.get("matched", 0),
            "detail": scraper_result,
        })
    except Exception as e:
        logger.error(f"❌ 스크래퍼 일괄 실행 실패: {e}")
        results.append({"source": "개별기관 스크래퍼", "collected": 0, "inserted": 0, "updated": 0, "error": str(e)})

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    results = collect_all()

    print("\n" + "=" * 50)
    print("  전체 수집 결과")
    print("=" * 50)
    total_collected = 0
    total_inserted = 0
    for r in results:
        err = f" (에러: {r.get('error', '')})" if r.get("error") else ""
        print(f"  {r['source']}: 수집 {r['collected']}건, 신규 {r['inserted']}건, 업데이트 {r['updated']}건{err}")
        total_collected += r["collected"]
        total_inserted += r["inserted"]
    print(f"\n  합계: 수집 {total_collected}건, 신규 DB저장 {total_inserted}건")
