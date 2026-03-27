"""
나라장터 (조달청) 입찰공고정보서비스 API 수집기
엔드포인트: https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServc
※ 현재 서버 장애로 500 에러 발생 중 — 복구 후 테스트 필요
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

BASE_URL = "https://apis.data.go.kr/1230000/BidPublicInfoService04"

# 용역 / 물품 / 공사 엔드포인트
ENDPOINTS = {
    "용역": f"{BASE_URL}/getBidPblancListInfoServc",
    "물품": f"{BASE_URL}/getBidPblancListInfoThng",
    "공사": f"{BASE_URL}/getBidPblancListInfoCnstwk",
}


def fetch_announcements(keywords: list[str], days: int = 30, bid_types: list[str] = None) -> list[dict]:
    """나라장터 입찰공고 수집 (키워드 매칭)"""
    if bid_types is None:
        bid_types = ["용역"]  # 기본: 용역만

    collected = []
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    for bid_type in bid_types:
        url = ENDPOINTS.get(bid_type)
        if not url:
            continue

        page = 1
        while True:
            params = {
                "serviceKey": DATA_GO_KR_KEY,
                "pageNo": page,
                "numOfRows": 100,
                "inqryDiv": "1",  # 1=공고일 기준
                "inqryBgnDt": start_dt.strftime("%Y%m%d") + "0000",
                "inqryEndDt": end_dt.strftime("%Y%m%d") + "2359",
                "type": "json",
            }

            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"나라장터 {bid_type} API 호출 실패 (page={page}): {e}")
                break

            body = data.get("response", {}).get("body", {})
            total_count = body.get("totalCount", 0)
            items = body.get("items", [])

            if not items:
                break

            logger.info(f"나라장터 {bid_type} page {page}: {len(items)}건 (전체 {total_count}건)")

            for item in items:
                title = item.get("bidNtceNm", "")
                org = item.get("ntceInsttNm", "")
                search_text = f"{title} {org}".lower()

                # 키워드 매칭
                matched = [kw for kw in keywords if kw.lower() in search_text]
                if not matched:
                    continue

                bid_no = item.get("bidNtceNo", "")
                bid_no_sub = item.get("bidNtceOrd", "")
                full_bid_no = f"{bid_no}-{bid_no_sub}" if bid_no_sub else bid_no

                start_date = _format_datetime(item.get("bidNtceDt", ""))
                end_date = _format_datetime(item.get("bidClseDt", ""))

                # 상태: 마감일 기준
                status = "ongoing"
                if end_date:
                    try:
                        close_dt = datetime.strptime(end_date, "%Y-%m-%d")
                        if close_dt < datetime.now():
                            status = "closed"
                    except ValueError:
                        pass

                # 상세 URL
                detail_url = item.get("bidNtceDtlUrl", "") or f"https://www.g2b.go.kr:8101/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}"

                collected.append({
                    "source": "나라장터",
                    "title": title,
                    "organization": org,
                    "category": bid_type,
                    "bid_no": f"G2B-{full_bid_no}",
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": status,
                    "url": detail_url,
                    "keywords": ",".join(matched),
                    # Phase 3 확장 필드
                    "est_price": item.get("presmptPrce", "") or "",
                })

            if page * 100 >= total_count:
                break
            page += 1

    logger.info(f"나라장터 키워드 매칭 결과: {len(collected)}건")
    return collected


def _format_datetime(dt_str: str) -> str:
    """yyyyMMddHHmm or yyyyMMdd → yyyy-MM-dd"""
    if not dt_str:
        return ""
    dt_str = dt_str.strip().replace("-", "").replace(" ", "").replace(":", "")
    try:
        if len(dt_str) >= 12:
            return datetime.strptime(dt_str[:12], "%Y%m%d%H%M").strftime("%Y-%m-%d")
        elif len(dt_str) >= 8:
            return datetime.strptime(dt_str[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        pass
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
                   est_price=?,
                   collected_at=datetime('now')
                   WHERE id=?""",
                (n["title"], n["organization"], n["category"],
                 n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("est_price", ""),
                 existing[0]),
            )
            updated += 1
        else:
            cursor.execute(
                """INSERT INTO bid_notices
                   (source, title, organization, category, bid_no, start_date, end_date, status, url, keywords,
                    est_price, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (n["source"], n["title"], n["organization"], n["category"],
                 n["bid_no"], n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("est_price", "")),
            )
            inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"나라장터 DB 저장: 신규 {inserted}건, 업데이트 {updated}건")
    return inserted, updated


def collect_and_save():
    """키워드 목록 로드 → 수집 → 저장"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
    keywords = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='date_range_days'")
    row = cursor.fetchone()
    days = int(row[0]) if row else 30

    conn.close()

    logger.info(f"나라장터 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일")
    notices = fetch_announcements(keywords, days=days)
    inserted, updated = save_to_db(notices)
    return {"source": "나라장터", "collected": len(notices), "inserted": inserted, "updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== 나라장터 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
