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
from database import get_connection

logger = logging.getLogger(__name__)

API_URL = "http://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2"


def fetch_announcements(keywords: list[str], days: int = 30) -> list[dict]:
    """중소벤처기업부 사업공고 수집 (키워드 매칭)"""
    collected = []
    page = 1
    num_of_rows = 100

    # 조회 기간
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

            # 키워드 매칭
            matched = [kw for kw in keywords if kw.lower() in search_text]
            if not matched:
                continue

            app_start = item.findtext("applicationStartDate", "") or ""
            app_end = item.findtext("applicationEndDate", "") or ""
            view_url = item.findtext("viewUrl", "") or ""
            item_id = item.findtext("itemId", "")

            # 상태 판단: 마감일이 있고 오늘 이후이면 ongoing
            status = "ongoing"
            if app_end:
                try:
                    end_dt = datetime.strptime(app_end, "%Y-%m-%d")
                    if end_dt < datetime.now():
                        status = "closed"
                except ValueError:
                    pass

            collected.append({
                "source": "중소벤처기업부",
                "title": title,
                "organization": "중소벤처기업부",
                "category": item.findtext("writerPosition", "") or "",
                "bid_no": f"MSS-{item_id}",
                "start_date": app_start,
                "end_date": app_end,
                "status": status,
                "url": view_url,
                "keywords": ",".join(matched),
                # Phase 3 확장 필드 — 첨부파일 전체 수집
                "file_url": _extract_files(item),
                "content": (content[:500] if content else ""),
                "budget": item.findtext("suptScale", "") or item.findtext("supt_scale", "") or "",
            })

        # 다음 페이지
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
                   file_url=?, content=?, budget=?,
                   collected_at=datetime('now')
                   WHERE id=?""",
                (n["title"], n["organization"], n["category"],
                 n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("file_url", ""), n.get("content", ""), n.get("budget", ""),
                 existing[0]),
            )
            updated += 1
        else:
            cursor.execute(
                """INSERT INTO bid_notices
                   (source, title, organization, category, bid_no, start_date, end_date, status, url, keywords,
                    file_url, content, budget, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (n["source"], n["title"], n["organization"], n["category"],
                 n["bid_no"], n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("file_url", ""), n.get("content", ""), n.get("budget", "")),
            )
            inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"중소벤처기업부 DB 저장: 신규 {inserted}건, 업데이트 {updated}건")
    return inserted, updated


def collect_and_save(keywords=None, days: int = 1, mode="daily"):
    """키워드 목록 로드 → 수집 → 저장
    days: 수집할 기간(일수).
    """
    conn = get_connection()
    cursor = conn.cursor()

    if keywords is None:
        cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
        keywords = [row[0] for row in cursor.fetchall()]

    conn.close()

    logger.info(f"중소벤처기업부 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일")
    notices = fetch_announcements(keywords, days=days)
    inserted, updated = save_to_db(notices)
    return {"source": "중소벤처기업부", "collected": len(notices), "inserted": inserted, "updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== 중소벤처기업부 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
