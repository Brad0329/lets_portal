"""
창조경제혁신센터(CCEI) 수집기
엔드포인트: https://ccei.creativekorea.or.kr/service/business_list.json (POST)
전국 19개 센터 통합 사이트에서 지원사업 공고를 수집한다.
"""

import re
import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_connection
from collectors.base import BaseCollector
from utils.text import clean_html, clean_html_to_text
from utils.dates import format_date
from utils.status import determine_status
from utils.keywords import match_keywords

logger = logging.getLogger(__name__)

API_URL = "https://ccei.creativekorea.or.kr/service/business_list.json"


class CceiCollector(BaseCollector):
    source_name = "창조경제혁신센터"

    def collect_and_save(self, keywords=None, days: int = 1, mode: str = "daily") -> dict:
        """CCEI는 display_settings에서 only_current 읽음."""
        if keywords is None:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
        row = cursor.fetchone()
        only_current = (row[0] == "ongoing") if row else True
        conn.close()

        logger.info(f"CCEI 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일, 현재만={only_current}")
        notices = self.fetch_announcements(keywords, days=days, only_current=only_current)
        notices = self.post_filter(notices)
        inserted, updated = self.save_to_db(notices)
        return {"source": self.source_name, "collected": len(notices), "inserted": inserted, "updated": updated}

    def fetch_announcements(self, keywords: list[str], days: int = 30, only_current: bool = True) -> list[dict]:
        """CCEI 지원사업 공고 수집 (키워드 매칭)"""
        collected = []
        seen_ids = set()
        page = 1

        while True:
            form_data = {
                "sPtime": "now" if only_current else "",
                "page": str(page),
            }

            try:
                resp = requests.post(API_URL, data=form_data, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"CCEI API 호출 실패 (page={page}): {e}")
                break

            result = data.get("result", {})
            items = result.get("list", [])
            if not items:
                break

            total_count = result.get("size", 0)
            logger.info(f"CCEI page {page}: {len(items)}건 (전체 {total_count}건)")

            for item in items:
                title = clean_html(item.get("PROGRAM_TITLE", ""))
                eligibility = clean_html(item.get("ELIGIBILITY", ""))
                support = clean_html(item.get("SUPPORT_NM", ""))
                org = clean_html(item.get("CD_NM2", ""))
                search_text = f"{title} {eligibility} {support} {org}".lower()

                matched = match_keywords(search_text, keywords)
                if not matched:
                    continue

                # 중복 체크
                seq = str(item.get("SEQ", item.get("seq", "")))
                if not seq or seq in seen_ids:
                    continue
                seen_ids.add(seq)

                c_sdate = item.get("C_SDATE", "")
                c_edate = item.get("C_EDATE", "")

                status = determine_status(c_edate)

                detail_url = f"https://ccei.creativekorea.or.kr/service/business_view.do?seq={seq}"

                # content: HTML → 텍스트 변환 (최대 1000자)
                raw_content = item.get("content", "")
                content_text = clean_html_to_text(raw_content)[:1000]

                # 신청 URL 추출
                apply_url = ""
                url_match = re.search(r'https?://[^\s<>"\'&]+', content_text)
                if url_match:
                    apply_url = url_match.group(0).rstrip('.)')

                collected.append({
                    "source": "창조경제혁신센터",
                    "title": title,
                    "organization": org or "창조경제혁신센터",
                    "category": support,
                    "bid_no": f"CCEI-{seq}",
                    "start_date": format_date(c_sdate),
                    "end_date": format_date(c_edate),
                    "status": status,
                    "url": detail_url,
                    "keywords": ",".join(matched),
                    "detail_url": detail_url,
                    "apply_url": apply_url,
                    "target": eligibility,
                    "content": content_text,
                })

            if page * 5 >= total_count:
                break
            page += 1

        logger.info(f"CCEI 키워드 매칭 결과: {len(collected)}건")
        return collected


# ─── 하위 호환 함수 (collect_all.py에서 호출) ──────────

_collector = CceiCollector()

def collect_and_save(keywords=None, days: int = 1, mode="daily"):
    return _collector.collect_and_save(keywords=keywords, days=days, mode=mode)

def fetch_announcements(keywords, days=30, only_current=True):
    return _collector.fetch_announcements(keywords, days=days, only_current=only_current)

def save_to_db(notices):
    return _collector.save_to_db(notices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== CCEI 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
