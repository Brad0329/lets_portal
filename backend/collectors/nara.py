"""
나라장터 (조달청) 입찰공고정보서비스 API 수집기
엔드포인트: https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc
"""

import json
import time
import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_GO_KR_KEY
from database import get_connection

logger = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 용역 / 물품 / 공사 엔드포인트 (PPSSrch: 공고명 검색 지원)
ENDPOINTS = {
    "용역": f"{BASE_URL}/getBidPblancListInfoServcPPSSrch",
    "물품": f"{BASE_URL}/getBidPblancListInfoThngPPSSrch",
    "공사": f"{BASE_URL}/getBidPblancListInfoCnstwkPPSSrch",
}


MAX_DAYS_PER_REQUEST = 7  # 새 API는 날짜 범위 제한이 있음 (14일 이내 권장, 안전하게 7일)


def fetch_announcements(keywords: list[str], days: int = 30, bid_types: list[str] = None) -> list[dict]:
    """나라장터 입찰공고 수집 (키워드별 API 호출, PPSSrch 엔드포인트)"""
    if bid_types is None:
        bid_types = ["용역"]  # 기본: 용역만

    collected = {}  # bid_no → dict (중복 제거용)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    # 날짜 범위를 MAX_DAYS_PER_REQUEST 단위로 분할
    date_ranges = []
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=MAX_DAYS_PER_REQUEST), end_dt)
        date_ranges.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(seconds=1)

    logger.info(f"날짜 범위 {days}일 → {len(date_ranges)}개 구간, 키워드 {len(keywords)}개")

    for bid_type in bid_types:
        url = ENDPOINTS.get(bid_type)
        if not url:
            continue

        for keyword in keywords:
            for range_start, range_end in date_ranges:
                page = 1
                while True:
                    params = {
                        "serviceKey": DATA_GO_KR_KEY,
                        "pageNo": page,
                        "numOfRows": 100,
                        "inqryDiv": "1",  # 1=공고일 기준
                        "inqryBgnDt": range_start.strftime("%Y%m%d") + "0000",
                        "inqryEndDt": range_end.strftime("%Y%m%d") + "2359",
                        "bidNtceNm": keyword,
                        "type": "json",
                    }

                    try:
                        resp = requests.get(url, params=params, timeout=30)
                        # 429 Too Many Requests → 대기 후 재시도
                        if resp.status_code == 429:
                            logger.warning(f"나라장터 429 rate limit — 5초 대기 후 재시도 [{keyword}]")
                            time.sleep(5)
                            resp = requests.get(url, params=params, timeout=30)
                        resp.raise_for_status()
                        data = resp.json()
                        time.sleep(0.2)  # API 호출 간 딜레이
                    except Exception as e:
                        logger.error(f"나라장터 {bid_type} [{keyword}] API 호출 실패 (page={page}): {e}")
                        break

                    # 에러 응답 체크
                    if "response" not in data:
                        err = data.get("nkoneps.com.response.ResponseError", {})
                        err_msg = err.get("header", {}).get("resultMsg", str(data))
                        logger.error(f"나라장터 {bid_type} [{keyword}] API 에러: {err_msg}")
                        break

                    body = data.get("response", {}).get("body", {})
                    total_count = body.get("totalCount", 0)
                    items = body.get("items", [])

                    if not items:
                        break

                    logger.info(
                        f"나라장터 {bid_type} [{keyword}] {range_start.strftime('%m/%d')}~{range_end.strftime('%m/%d')} "
                        f"page {page}: {len(items)}건 (전체 {total_count}건)"
                    )

                    for item in items:
                        bid_no = item.get("bidNtceNo", "")
                        bid_no_sub = item.get("bidNtceOrd", "")
                        full_bid_no = f"{bid_no}-{bid_no_sub}" if bid_no_sub else bid_no
                        dedup_key = f"{bid_type}-{full_bid_no}"

                        # 이미 수집된 공고면 키워드만 추가
                        if dedup_key in collected:
                            existing_kws = set(collected[dedup_key]["keywords"].split(","))
                            existing_kws.add(keyword)
                            collected[dedup_key]["keywords"] = ",".join(sorted(existing_kws))
                            continue

                        title = item.get("bidNtceNm", "")
                        org = item.get("ntceInsttNm", "")
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

                        # 첨부파일 추출 (ntceSpecDocUrl1~10, ntceSpecFileNm1~10)
                        attachments = []
                        for i in range(1, 11):
                            file_url = item.get(f"ntceSpecDocUrl{i}", "")
                            file_name = item.get(f"ntceSpecFileNm{i}", "")
                            if file_url:
                                attachments.append({"name": file_name or f"첨부파일{i}", "url": file_url})

                        # 조달 분류 조합
                        procure_parts = [
                            item.get("pubPrcrmntLrgClsfcNm", ""),
                            item.get("pubPrcrmntMidClsfcNm", ""),
                        ]
                        procure_class = " > ".join([p for p in procure_parts if p])

                        # 담당자 정보
                        contact_name = item.get("ntceInsttOfclNm", "") or ""
                        contact_phone = item.get("ntceInsttOfclTelNo", "") or ""
                        contact_email = (item.get("ntceInsttOfclEmailAdrs", "") or
                                         item.get("dminsttOfclEmailAdrs", "") or "")

                        collected[dedup_key] = {
                            "source": "나라장터",
                            "title": title,
                            "organization": org,
                            "category": bid_type,
                            "bid_no": f"G2B-{full_bid_no}",
                            "start_date": start_date,
                            "end_date": end_date,
                            "status": status,
                            "url": detail_url,
                            "keywords": keyword,
                            "est_price": item.get("presmptPrce", "") or "",
                            "assign_budget": item.get("asignBdgtAmt", "") or "",
                            "bid_method": item.get("bidMethdNm", "") or "",
                            "contract_method": item.get("cntrctCnclsMthdNm", "") or "",
                            "award_method": item.get("sucsfbidMthdNm", "") or "",
                            "open_date": _format_datetime(item.get("opengDt", "")),
                            "contact_name": contact_name,
                            "contact_phone": contact_phone,
                            "contact_email": contact_email,
                            "tech_eval_ratio": item.get("techAbltEvlRt", "") or "",
                            "price_eval_ratio": item.get("bidPrceEvlRt", "") or "",
                            "procure_class": procure_class,
                            "attachments": json.dumps(attachments, ensure_ascii=False) if attachments else "",
                        }

                    if page * 100 >= total_count:
                        break
                    page += 1

    result = list(collected.values())
    logger.info(f"나라장터 수집 결과: {len(result)}건 (중복 제거 완료)")
    return result


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

        # 나라장터 확장 필드
        extra_fields = {
            "est_price": n.get("est_price", ""),
            "assign_budget": n.get("assign_budget", ""),
            "bid_method": n.get("bid_method", ""),
            "contract_method": n.get("contract_method", ""),
            "award_method": n.get("award_method", ""),
            "open_date": n.get("open_date", ""),
            "contact_name": n.get("contact_name", ""),
            "contact_phone": n.get("contact_phone", ""),
            "contact_email": n.get("contact_email", ""),
            "tech_eval_ratio": n.get("tech_eval_ratio", ""),
            "price_eval_ratio": n.get("price_eval_ratio", ""),
            "procure_class": n.get("procure_class", ""),
            "attachments": n.get("attachments", ""),
        }

        if existing:
            cursor.execute(
                """UPDATE bid_notices SET title=?, organization=?, category=?,
                   start_date=?, end_date=?, status=?, url=?, keywords=?,
                   est_price=?, assign_budget=?, bid_method=?, contract_method=?,
                   award_method=?, open_date=?, contact_name=?, contact_phone=?,
                   contact_email=?, tech_eval_ratio=?, price_eval_ratio=?,
                   procure_class=?, attachments=?,
                   collected_at=datetime('now')
                   WHERE id=?""",
                (n["title"], n["organization"], n["category"],
                 n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 extra_fields["est_price"], extra_fields["assign_budget"],
                 extra_fields["bid_method"], extra_fields["contract_method"],
                 extra_fields["award_method"], extra_fields["open_date"],
                 extra_fields["contact_name"], extra_fields["contact_phone"],
                 extra_fields["contact_email"], extra_fields["tech_eval_ratio"],
                 extra_fields["price_eval_ratio"], extra_fields["procure_class"],
                 extra_fields["attachments"],
                 existing[0]),
            )
            updated += 1
        else:
            cursor.execute(
                """INSERT INTO bid_notices
                   (source, title, organization, category, bid_no, start_date, end_date, status, url, keywords,
                    est_price, assign_budget, bid_method, contract_method, award_method, open_date,
                    contact_name, contact_phone, contact_email, tech_eval_ratio, price_eval_ratio,
                    procure_class, attachments, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (n["source"], n["title"], n["organization"], n["category"],
                 n["bid_no"], n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 extra_fields["est_price"], extra_fields["assign_budget"],
                 extra_fields["bid_method"], extra_fields["contract_method"],
                 extra_fields["award_method"], extra_fields["open_date"],
                 extra_fields["contact_name"], extra_fields["contact_phone"],
                 extra_fields["contact_email"], extra_fields["tech_eval_ratio"],
                 extra_fields["price_eval_ratio"], extra_fields["procure_class"],
                 extra_fields["attachments"]),
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
