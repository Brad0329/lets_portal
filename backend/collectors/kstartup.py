"""
K-Startup (창업진흥원) API 수집기
엔드포인트: https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01
"""

import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_GO_KR_KEY
from database import get_connection

logger = logging.getLogger(__name__)

API_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"


def fetch_announcements(keywords: list[str], days: int = 30, only_ongoing: bool = True) -> list[dict]:
    """K-Startup 사업공고 수집 (키워드 매칭)"""
    collected = []
    page = 1
    per_page = 100

    while True:
        params = {
            "serviceKey": DATA_GO_KR_KEY,
            "page": page,
            "perPage": per_page,
            "returnType": "json",
        }
        # 진행중만 필터
        if only_ongoing:
            params["cond[rcrt_prgs_yn::EQ]"] = "Y"

        try:
            resp = requests.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"K-Startup API 호출 실패 (page={page}): {e}")
            break

        items = data.get("data", [])
        if not items:
            break

        total_count = data.get("totalCount", 0)
        logger.info(f"K-Startup page {page}: {len(items)}건 (전체 {total_count}건)")

        for item in items:
            title = item.get("biz_pbanc_nm", "")
            content = item.get("pbanc_ctnt", "") or ""
            target = item.get("aply_trgt_ctnt", "") or ""
            search_text = f"{title} {content} {target}".lower()

            # 키워드 매칭
            matched = [kw for kw in keywords if kw.lower() in search_text]
            if not matched:
                continue

            # 날짜 필터 (최근 N일)
            start_dt = item.get("pbanc_rcpt_bgng_dt", "")
            if start_dt and len(start_dt) >= 8:
                try:
                    start_date = datetime.strptime(start_dt[:8], "%Y%m%d")
                    cutoff = datetime.now() - timedelta(days=days)
                    if start_date < cutoff:
                        continue
                except ValueError:
                    pass

            end_dt = item.get("pbanc_rcpt_end_dt", "")
            detail_url = item.get("detl_pg_url") or item.get("biz_aply_url") or item.get("biz_gdnc_url") or ""

            # 상태 판단
            status = "ongoing" if item.get("rcrt_prgs_yn") == "Y" else "closed"

            collected.append({
                "source": "K-Startup",
                "title": title,
                "organization": item.get("pbanc_ntrp_nm") or item.get("sprv_inst") or "창업진흥원",
                "category": item.get("supt_biz_clsfc") or "",
                "bid_no": str(item.get("pbanc_sn", "")),
                "start_date": _format_date(start_dt),
                "end_date": _format_date(end_dt),
                "status": status,
                "url": detail_url,
                "keywords": ",".join(matched),
            })

        # 다음 페이지
        if page * per_page >= total_count:
            break
        page += 1

    logger.info(f"K-Startup 키워드 매칭 결과: {len(collected)}건")
    return collected


def _format_date(dt_str: str) -> str:
    """yyyyMMdd → yyyy-MM-dd"""
    if not dt_str or len(dt_str) < 8:
        return ""
    try:
        return datetime.strptime(dt_str[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return dt_str


def save_to_db(notices: list[dict]):
    """수집 결과를 DB에 저장"""
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

        if existing:
            cursor.execute(
                """UPDATE bid_notices SET title=?, organization=?, category=?,
                   start_date=?, end_date=?, status=?, url=?, keywords=?,
                   collected_at=datetime('now')
                   WHERE id=?""",
                (n["title"], n["organization"], n["category"],
                 n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 existing[0]),
            )
            updated += 1
        else:
            cursor.execute(
                """INSERT INTO bid_notices
                   (source, title, organization, category, bid_no, start_date, end_date, status, url, keywords, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (n["source"], n["title"], n["organization"], n["category"],
                 n["bid_no"], n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"]),
            )
            inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"K-Startup DB 저장: 신규 {inserted}건, 업데이트 {updated}건")
    return inserted, updated


def collect_and_save():
    """키워드 목록 로드 → 수집 → 저장 (메인 실행 함수)"""
    conn = get_connection()
    cursor = conn.cursor()

    # 활성 키워드 로드
    cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
    keywords = [row[0] for row in cursor.fetchall()]

    # 설정 로드
    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='date_range_days'")
    row = cursor.fetchone()
    days = int(row[0]) if row else 30

    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
    row = cursor.fetchone()
    only_ongoing = (row[0] == "ongoing") if row else True

    conn.close()

    logger.info(f"K-Startup 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일, 진행중만={only_ongoing}")
    notices = fetch_announcements(keywords, days=days, only_ongoing=only_ongoing)
    inserted, updated = save_to_db(notices)
    return {"source": "K-Startup", "collected": len(notices), "inserted": inserted, "updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== K-Startup 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
