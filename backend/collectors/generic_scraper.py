"""
범용 HTML 스크래퍼 프레임워크
- JSON 설정 기반으로 입찰공고 사이트를 스크래핑
- 최근 1개월 공고 수집 → 키워드 매칭 → DB 저장
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_connection

logger = logging.getLogger(__name__)

# 설정 파일 경로
CONFIGS_PATH = os.path.join(os.path.dirname(__file__), "scraper_configs.json")

# 요청 기본 헤더
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.3",
}


def _load_configs() -> list[dict]:
    """scraper_configs.json 로드"""
    if not os.path.exists(CONFIGS_PATH):
        logger.error(f"설정 파일 없음: {CONFIGS_PATH}")
        return []
    with open(CONFIGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_date(text: str) -> str | None:
    """다양한 날짜 형식을 yyyy-MM-dd로 변환"""
    if not text:
        return None
    text = text.strip().replace(".", "-").replace("/", "-")
    # yyyy-MM-dd 이미 맞는 경우
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    # yy-MM-dd
    m = re.search(r"(\d{2})-(\d{2})-(\d{2})", text)
    if m:
        y = int(m.group(1))
        year = 2000 + y if y < 80 else 1900 + y
        return f"{year}-{m.group(2)}-{m.group(3)}"
    return None


def _get_status(end_date_str: str | None) -> str:
    """마감일 기준 상태 판별"""
    if not end_date_str:
        return "ongoing"
    try:
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        return "closed" if end_dt < datetime.now() else "ongoing"
    except ValueError:
        return "ongoing"


def _match_keywords(notices: list[dict], keywords: list[str]) -> list[dict]:
    """제목 기준 키워드 매칭. 매칭된 공고만 반환."""
    if not keywords:
        return []
    matched = []
    for n in notices:
        title = (n.get("title") or "").lower()
        hit = [kw for kw in keywords if kw.lower() in title]
        if hit:
            n["keywords"] = ",".join(hit)
            matched.append(n)
    return matched


def scrape_site(config: dict, days: int = 30) -> list[dict]:
    """
    설정 기반으로 단일 사이트 스크래핑.
    반환: [{source, title, bid_no, url, start_date, end_date, status, organization, ...}, ...]
    """
    name = config["name"]
    list_url = config["list_url"]
    encoding = config.get("encoding", "utf-8")
    max_pages = config.get("max_pages", 3)
    link_base = config.get("link_base", "")
    source_key = config.get("source_key", name)

    # 셀렉터
    list_sel = config.get("list_selector", "table tbody tr")
    title_sel = config.get("title_selector", "td.title a, td a")
    date_sel = config.get("date_selector", "td.date, td:last-child")
    link_attr = config.get("link_attr", "href")

    # 페이지네이션
    pagination = config.get("pagination", "")  # e.g. "&page={page}" or "?page={page}"

    cutoff = datetime.now() - timedelta(days=days)
    notices = []
    seen = set()

    for page in range(1, max_pages + 1):
        # URL 구성
        if page == 1:
            url = list_url
        elif pagination:
            sep = "&" if "?" in list_url else "?"
            url = list_url + pagination.replace("{page}", str(page))
        else:
            break  # 페이지네이션 없으면 1페이지만

        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15, verify=False)
            if encoding.lower() != "utf-8":
                resp.encoding = encoding
            else:
                resp.encoding = resp.apparent_encoding or "utf-8"

            if resp.status_code != 200:
                logger.warning(f"  {name} 페이지 {page}: HTTP {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select(list_sel)

            if not rows:
                break  # 데이터 없으면 종료

            page_has_old = False

            for row in rows:
                # 제목 추출
                title_el = row.select_one(title_sel)
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue

                # URL 추출
                link = title_el.get(link_attr, "")
                if link and not link.startswith("http"):
                    link = urljoin(link_base or list_url, link)

                # 날짜 추출
                date_el = row.select_one(date_sel)
                date_text = date_el.get_text(strip=True) if date_el else ""
                parsed_date = _parse_date(date_text)

                # 최근 1개월 체크
                if parsed_date:
                    try:
                        dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                        if dt < cutoff:
                            page_has_old = True
                            continue
                    except ValueError:
                        pass

                # 날짜 파싱 실패 시 오늘 날짜 사용
                if not parsed_date:
                    parsed_date = datetime.now().strftime("%Y-%m-%d")

                # 중복 방지
                bid_no = f"SCR-{source_key}-{abs(hash(title + link)) % 1000000:06d}"
                if bid_no in seen:
                    continue
                seen.add(bid_no)

                notices.append({
                    "source": name,
                    "title": title,
                    "organization": name,
                    "category": "입찰공고",
                    "bid_no": bid_no,
                    "start_date": parsed_date,
                    "end_date": "",
                    "status": _get_status(None),
                    "url": link,
                    "keywords": "",
                    "detail_url": link,
                    "apply_url": "",
                    "target": "",
                    "content": "",
                })

            # 오래된 게시물이 나왔으면 더 이상 페이지 넘길 필요 없음
            if page_has_old:
                break

        except requests.RequestException as e:
            logger.warning(f"  {name} 페이지 {page} 요청 실패: {e}")
            break

    return notices


def save_to_db(notices: list[dict]) -> tuple[int, int]:
    """수집 결과를 bid_notices에 저장 (UPSERT)"""
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
    return inserted, updated


def collect_single(source_name: str, config: dict, keywords: list[str], days: int = 30) -> dict:
    """단일 사이트 수집: 스크래핑 → 키워드 매칭 → DB 저장"""
    notices = scrape_site(config, days=days)
    matched = _match_keywords(notices, keywords)
    inserted, updated = save_to_db(matched)
    return {
        "source": source_name,
        "collected": len(notices),
        "matched": len(matched),
        "inserted": inserted,
        "updated": updated,
    }


def collect_all_scrapers(mode: str = "daily") -> dict:
    """
    28개 스크래퍼 일괄 실행.
    mode: 'daily'=최근 7일, 'full'=최근 30일
    """
    configs = _load_configs()
    if not configs:
        return {"total": 0, "success": 0, "failed": 0, "collected": 0, "matched": 0, "inserted": 0, "results": []}

    # 공통 키워드 로드
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT keyword FROM keywords WHERE is_active=1 AND source_id IS NULL")
    keywords = [row[0] for row in cursor.fetchall()]

    # 설정 로드
    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='date_range_days'")
    row = cursor.fetchone()
    days = int(row[0]) if row else 30
    conn.close()

    if mode == "daily":
        days = min(days, 7)

    if not keywords:
        logger.warning("활성 공통 키워드 없음 — 스크래핑 건너뜀")
        return {"total": len(configs), "success": 0, "failed": 0, "collected": 0, "matched": 0, "inserted": 0,
                "results": [], "error": "활성 키워드가 없습니다."}

    results = []
    success = 0
    failed = 0
    total_collected = 0
    total_matched = 0
    total_inserted = 0

    for cfg in configs:
        name = cfg["name"]
        try:
            logger.info(f"  스크래핑: {name}")
            r = collect_single(name, cfg, keywords, days=days)
            results.append(r)
            success += 1
            total_collected += r["collected"]
            total_matched += r["matched"]
            total_inserted += r["inserted"]
            logger.info(f"  ✅ {name}: 수집 {r['collected']}건, 매칭 {r['matched']}건, 신규 {r['inserted']}건")

            # collect_sources 갱신
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE collect_sources SET last_collected_at=datetime('now'), last_collected_count=? WHERE name=?",
                (r["matched"], name),
            )
            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"  ❌ {name} 스크래핑 실패: {e}")
            results.append({"source": name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)})
            failed += 1

    return {
        "total": len(configs),
        "success": success,
        "failed": failed,
        "collected": total_collected,
        "matched": total_matched,
        "inserted": total_inserted,
        "results": results,
    }


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    result = collect_all_scrapers(mode="daily")
    print(f"\n===== 스크래퍼 일괄 수집 결과 =====")
    print(f"  전체: {result['total']}개 | 성공: {result['success']} | 실패: {result['failed']}")
    print(f"  수집: {result['collected']}건 | 매칭: {result['matched']}건 | 신규: {result['inserted']}건")
    for r in result["results"]:
        err = f" (에러: {r.get('error', '')})" if r.get("error") else ""
        print(f"  - {r['source']}: 수집 {r['collected']}건, 매칭 {r['matched']}건{err}")
