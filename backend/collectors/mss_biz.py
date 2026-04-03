"""
중소벤처기업부 사업공고 API 수집기
엔드포인트: http://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2
응답형식: XML
"""

import re
import json
import requests
import logging
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_GO_KR_KEY
from collectors.base import BaseCollector
from utils.text import clean_html
from utils.status import determine_status
from utils.keywords import match_keywords

logger = logging.getLogger(__name__)

API_URL = "http://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2"


class MssBizCollector(BaseCollector):
    source_name = "중소벤처기업부"

    def fetch_announcements(self, keywords: list[str], days: int = 30) -> list[dict]:
        """중소벤처기업부 사업공고 수집 (키워드 매칭)"""
        collected = []
        page = 1
        num_of_rows = 100

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        while True:
            params = {
                "serviceKey": DATA_GO_KR_KEY,
                "pageNo": page,
                "numOfRows": num_of_rows,
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
            }

            try:
                resp = requests.get(API_URL, params=params, timeout=30)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception as e:
                logger.error(f"중소벤처기업부 API 호출 실패 (page={page}): {e}")
                break

            result_code = root.findtext(".//resultCode", "")
            if result_code != "00":
                logger.error(f"API 에러: {root.findtext('.//resultMsg', '')}")
                break

            total_count = int(root.findtext(".//totalCount", "0"))
            items = root.findall(".//item")
            logger.info(f"중소벤처기업부 page {page}: {len(items)}건 (전체 {total_count}건)")

            if not items:
                break

            for item in items:
                title = html.unescape(item.findtext("title", "") or "")
                content = html.unescape(item.findtext("dataContents", "") or "")
                content = content.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
                content = re.sub(r"<[^>]+>", "", content).strip()
                search_text = f"{title} {content}".lower()

                matched = match_keywords(search_text, keywords)
                if not matched:
                    continue

                app_start = item.findtext("applicationStartDate", "") or ""
                app_end = item.findtext("applicationEndDate", "") or ""
                view_url = item.findtext("viewUrl", "") or ""
                item_id = item.findtext("itemId", "")

                status = determine_status(app_end)

                collected.append({
                    "source": self.source_name,
                    "title": title,
                    "organization": "중소벤처기업부",
                    "category": item.findtext("writerPosition", "") or "",
                    "bid_no": f"MSS-{item_id}",
                    "start_date": app_start,
                    "end_date": app_end,
                    "status": status,
                    "url": view_url,
                    "keywords": ",".join(matched),
                    "file_url": _extract_files(item),
                    "content": (content[:500] if content else ""),
                    "budget": item.findtext("suptScale", "") or item.findtext("supt_scale", "") or "",
                })

            if page * num_of_rows >= total_count:
                break
            page += 1

        logger.info(f"중소벤처기업부 키워드 매칭 결과: {len(collected)}건")
        return collected


def _extract_files(item) -> str:
    """XML item에서 fileName/fileUrl 쌍을 모두 추출하여 JSON 문자열로 반환"""
    names = [el.text for el in item.findall("fileName") if el.text]
    urls = [el.text for el in item.findall("fileUrl") if el.text]
    if not urls:
        return ""
    files = []
    for i, url in enumerate(urls):
        name = names[i] if i < len(names) else f"첨부파일{i+1}"
        files.append({"name": name, "url": url})
    return json.dumps(files, ensure_ascii=False)


# ─── 하위 호환 함수 (collect_all.py에서 호출) ──────────

_collector = MssBizCollector()

def collect_and_save(keywords=None, days: int = 1, mode="daily"):
    return _collector.collect_and_save(keywords=keywords, days=days, mode=mode)

def fetch_announcements(keywords, days=30):
    return _collector.fetch_announcements(keywords, days=days)

def save_to_db(notices):
    return _collector.save_to_db(notices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== 중소벤처기업부 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
