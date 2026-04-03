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
from collectors.base import BaseCollector
from utils.dates import format_date
from utils.status import determine_status

logger = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

ENDPOINTS = {
    "용역": f"{BASE_URL}/getBidPblancListInfoServcPPSSrch",
    "물품": f"{BASE_URL}/getBidPblancListInfoThngPPSSrch",
    "공사": f"{BASE_URL}/getBidPblancListInfoCnstwkPPSSrch",
}

MAX_DAYS_PER_REQUEST = 7


class NaraCollector(BaseCollector):
    source_name = "나라장터"

    def collect_and_save(self, keywords=None, days: int = 1, mode: str = "daily") -> dict:
        """나라장터는 post_filter로 관심 중분류 필터링 적용."""
        if keywords is None:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()

        logger.info(f"나라장터 수집 시작 (mode={mode}): 키워드 {len(keywords)}개, 기간 {days}일")
        notices = self.fetch_announcements(keywords, days=days)

        # 관심 중분류 필터링
        notices, filtered_count = _filter_by_interest_categories(notices)

        inserted, updated = self.save_to_db(notices)
        return {
            "source": self.source_name,
            "collected": len(notices),
            "inserted": inserted,
            "updated": updated,
            "filtered": filtered_count,
        }

    def fetch_announcements(self, keywords: list[str], days: int = 30, bid_types: list[str] = None) -> list[dict]:
        """나라장터 입찰공고 수집 (키워드별 API 호출, PPSSrch 엔드포인트)"""
        if bid_types is None:
            bid_types = ["용역"]

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
                            "inqryDiv": "1",
                            "inqryBgnDt": range_start.strftime("%Y%m%d") + "0000",
                            "inqryEndDt": range_end.strftime("%Y%m%d") + "2359",
                            "bidNtceNm": keyword,
                            "type": "json",
                        }

                        try:
                            resp = None
                            for retry in range(3):
                                resp = requests.get(url, params=params, timeout=30)
                                if resp.status_code == 429:
                                    wait = 3 * (retry + 1)
                                    logger.warning(f"나라장터 429 rate limit — {wait}초 대기 후 재시도 ({retry+1}/3) [{keyword}]")
                                    time.sleep(wait)
                                else:
                                    break
                            resp.raise_for_status()
                            data = resp.json()
                            time.sleep(0.5)
                        except Exception as e:
                            logger.error(f"나라장터 {bid_type} [{keyword}] API 호출 실패 (page={page}): {e}")
                            time.sleep(1)
                            break

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

                            if dedup_key in collected:
                                existing_kws = set(collected[dedup_key]["keywords"].split(","))
                                existing_kws.add(keyword)
                                collected[dedup_key]["keywords"] = ",".join(sorted(existing_kws))
                                continue

                            title = item.get("bidNtceNm", "")
                            org = item.get("ntceInsttNm", "")
                            start_date = format_date(item.get("bidNtceDt", ""))
                            end_date = format_date(item.get("bidClseDt", ""))

                            status = determine_status(end_date)

                            detail_url = item.get("bidNtceDtlUrl", "") or f"https://www.g2b.go.kr:8101/ep/invitation/publish/bidInfoDtl.do?bidno={bid_no}"

                            # 첨부파일 추출
                            attachments = []
                            for i in range(1, 11):
                                file_url = item.get(f"ntceSpecDocUrl{i}", "")
                                file_name = item.get(f"ntceSpecFileNm{i}", "")
                                if file_url:
                                    attachments.append({"name": file_name or f"첨부파일{i}", "url": file_url})

                            # 조달 분류
                            procure_parts = [
                                item.get("pubPrcrmntLrgClsfcNm", ""),
                                item.get("pubPrcrmntMidClsfcNm", ""),
                            ]
                            procure_class = " > ".join([p for p in procure_parts if p])

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
                                "open_date": format_date(item.get("opengDt", "")),
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


def _filter_by_interest_categories(notices: list[dict]) -> tuple[list[dict], int]:
    """관심 중분류에 해당하는 공고만 필터링. 관심 목록이 없으면 전체 통과."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT large_class, mid_class FROM nara_interest_categories WHERE is_active=1")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return notices, 0

    interest_set = set()
    for row in rows:
        interest_set.add(row[1].strip())

    original_count = len(notices)
    filtered = []
    for n in notices:
        pc = n.get("procure_class", "")
        if not pc:
            filtered.append(n)
            continue
        parts = pc.split(">")
        mid = parts[-1].strip() if len(parts) >= 2 else ""
        if mid in interest_set:
            filtered.append(n)

    filtered_count = original_count - len(filtered)
    if filtered_count > 0:
        logger.info(f"나라장터 관심 중분류 필터: {original_count}건 → {len(filtered)}건 ({filtered_count}건 제외)")
    return filtered, filtered_count


# ─── 하위 호환 함수 (collect_all.py에서 호출) ──────────

_collector = NaraCollector()

def collect_and_save(keywords=None, days: int = 1, mode="daily"):
    return _collector.collect_and_save(keywords=keywords, days=days, mode=mode)

def fetch_announcements(keywords, days=30, bid_types=None):
    return _collector.fetch_announcements(keywords, days=days, bid_types=bid_types)

def save_to_db(notices):
    return _collector.save_to_db(notices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== 나라장터 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
