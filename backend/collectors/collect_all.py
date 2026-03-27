"""
전체 수집기 실행 (K-Startup + 중소벤처기업부 + 나라장터)
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.kstartup import collect_and_save as collect_kstartup
from collectors.mss_biz import collect_and_save as collect_mss
from collectors.nara import collect_and_save as collect_nara

logger = logging.getLogger(__name__)


def collect_all():
    """모든 API 수집기 실행"""
    results = []

    # 1. K-Startup
    try:
        r = collect_kstartup()
        results.append(r)
        logger.info(f"✅ K-Startup: {r['collected']}건 수집")
    except Exception as e:
        logger.error(f"❌ K-Startup 수집 실패: {e}")
        results.append({"source": "K-Startup", "collected": 0, "inserted": 0, "updated": 0, "error": str(e)})

    # 2. 중소벤처기업부
    try:
        r = collect_mss()
        results.append(r)
        logger.info(f"✅ 중소벤처기업부: {r['collected']}건 수집")
    except Exception as e:
        logger.error(f"❌ 중소벤처기업부 수집 실패: {e}")
        results.append({"source": "중소벤처기업부", "collected": 0, "inserted": 0, "updated": 0, "error": str(e)})

    # 3. 나라장터 (서버 장애 시 건너뜀)
    try:
        r = collect_nara()
        results.append(r)
        logger.info(f"✅ 나라장터: {r['collected']}건 수집")
    except Exception as e:
        logger.error(f"❌ 나라장터 수집 실패: {e}")
        results.append({"source": "나라장터", "collected": 0, "inserted": 0, "updated": 0, "error": str(e)})

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
