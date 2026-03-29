"""
창조경제혁신센터(CCEI) 수집기
엔드포인트: https://ccei.creativekorea.or.kr/service/business_list.json (POST)
전국 19개 센터 통합 사이트에서 지원사업 공고를 수집한다.
"""

import requests
import logging
import html as html_mod
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_connection

logger = logging.getLogger(__name__)

API_URL = "https://ccei.creativekorea.or.kr/service/business_list.json"


def fetch_announcements(keywords: list[str], days: int = 30, only_current: bool = True) -> list[dict]:
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
            title = _clean(item.get("PROGRAM_TITLE", ""))
            eligibility = _clean(item.get("ELIGIBILITY", ""))
            support = _clean(item.get("SUPPORT_NM", ""))
            org = _clean(item.get("CD_NM2", ""))
            search_text = f"{title} {eligibility} {support} {org}".lower()

            # 키워드 매칭
            matched = [kw for kw in keywords if kw.lower() in search_text]
            if not matched:
                continue

            # 중복 체크
            seq = str(item.get("SEQ", item.get("seq", "")))
            if not seq or seq in seen_ids:
                continue
            seen_ids.add(seq)

            # 날짜 파싱
            c_sdate = item.get("C_SDATE", "")
            c_edate = item.get("C_EDATE", "")

            # 상태 판단
            status = "ongoing"
            if c_edate:
                try:
                    end_dt = datetime.strptime(c_edate[:10], "%Y-%m-%d")
                    if end_dt < datetime.now():
                        status = "closed"
                except ValueError:
                    pass

            detail_url = f"https://ccei.creativekorea.or.kr/service/business_view.do?seq={seq}"

            # content: HTML → 텍스트 변환 (최대 1000자)
            raw_content = item.get("content", "")
            content_text = _clean_html_to_text(raw_content)[:1000]

            # 신청 URL 추출 (텍스트 변환 후 깨끗한 URL)
            apply_url = ""
            import re
            url_match = re.search(r'https?://[^\s<>"\'&]+', content_text)
            if url_match:
                apply_url = url_match.group(0).rstrip('.)')

            collected.append({
                "source": "창조경제혁신센터",
                "title": title,
                "organization": org or "창조경제혁신센터",
                "category": support,
                "bid_no": f"CCEI-{seq}",
                "start_date": _format_date(c_sdate),
                "end_date": _format_date(c_edate),
                "status": status,
                "url": detail_url,
                "keywords": ",".join(matched),
                "detail_url": detail_url,
                "apply_url": apply_url,
                "target": eligibility,
                "content": content_text,
            })

        # 다음 페이지
        if page * 5 >= total_count:  # CCEI 기본 페이지 사이즈 5건
            break
        page += 1

    logger.info(f"CCEI 키워드 매칭 결과: {len(collected)}건")
    return collected


def _clean(text: str) -> str:
    """HTML 엔티티 디코딩 + 태그 제거"""
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    return text.strip()


def _clean_html_to_text(html_str: str) -> str:
    """HTML content → 순수 텍스트 (태그 제거, 공백 정리)"""
    if not html_str:
        return ""
    import re
    text = html_mod.unescape(html_str)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _format_date(dt_str: str) -> str:
    """다양한 날짜 형식 → yyyy-MM-dd"""
    if not dt_str:
        return ""
    dt_str = dt_str.strip()[:10]
    # 이미 yyyy-MM-dd 형식이면 그대로
    if len(dt_str) == 10 and dt_str[4] == "-":
        return dt_str
    # yyyy.MM.dd 형식
    if len(dt_str) == 10 and dt_str[4] == ".":
        return dt_str.replace(".", "-")
    # yyyyMMdd 형식
    if len(dt_str) >= 8 and dt_str[:8].isdigit():
        try:
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
                   detail_url=?, apply_url=?, target=?, content=?,
                   collected_at=datetime('now')
                   WHERE id=?""",
                (n["title"], n["organization"], n["category"],
                 n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("detail_url", ""), n.get("apply_url", ""),
                 n.get("target", ""), n.get("content", ""),
                 existing[0]),
            )
            updated += 1
        else:
            cursor.execute(
                """INSERT INTO bid_notices
                   (source, title, organization, category, bid_no, start_date, end_date, status, url, keywords,
                    detail_url, apply_url, target, content, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (n["source"], n["title"], n["organization"], n["category"],
                 n["bid_no"], n["start_date"], n["end_date"], n["status"], n["url"], n["keywords"],
                 n.get("detail_url", ""), n.get("apply_url", ""),
                 n.get("target", ""), n.get("content", "")),
            )
            inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"CCEI DB 저장: 신규 {inserted}건, 업데이트 {updated}건")
    return inserted, updated


def collect_and_save(keywords=None, mode="daily"):
    """키워드 목록 로드 → 수집 → 저장 (메인 실행 함수)
    mode: 'daily'/'full' — CCEI는 sPtime=now로 현재 프로그램만 가져오므로 차이 없음
    """
    conn = get_connection()
    cursor = conn.cursor()

    if keywords is None:
        cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
        keywords = [row[0] for row in cursor.fetchall()]

    # 설정 로드
    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='date_range_days'")
    row = cursor.fetchone()
    days = int(row[0]) if row else 30

    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
    row = cursor.fetchone()
    only_current = (row[0] == "ongoing") if row else True

    conn.close()

    logger.info(f"CCEI 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일, 현재만={only_current}")
    notices = fetch_announcements(keywords, days=days, only_current=only_current)
    inserted, updated = save_to_db(notices)
    return {"source": "창조경제혁신센터", "collected": len(notices), "inserted": inserted, "updated": updated}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== CCEI 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
