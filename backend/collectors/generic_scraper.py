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
    """다양한 날짜 형식을 yyyy-MM-dd로 변환. 텍스트 내 날짜 패턴 자동 감지."""
    if not text:
        return None
    text = text.strip()

    # 1) yyyy.MM.dd / yyyy-MM-dd / yyyy/MM/dd (원본에서 먼저 탐색)
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 2) yy.MM.dd / yy-MM-dd (2자리 연도)
    m = re.search(r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        y = int(m.group(1))
        year = 2000 + y if y < 80 else 1900 + y
        return f"{year}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 3) yyyyMMdd (구분자 없이 8자리)
    m = re.search(r"(\d{4})(\d{2})(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 4) 한국어 날짜: yyyy년 MM월 dd일 / MM월 dd일
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 5) 기간 형식에서 첫 번째 날짜 추출: "2026-03-01 ~ 2026-03-31"
    m = re.search(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~∼\-]\s*\d{4}", text)
    if m:
        return _parse_date(m.group(1))

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


def scrape_ccei_allim(region_code: str, region_name: str, days: int = 30) -> list[dict]:
    """
    CCEI 지역센터 입찰공고 수집 (JSON API).
    POST https://ccei.creativekorea.or.kr/{region}/allim/allimList.json
    """
    api_url = f"https://ccei.creativekorea.or.kr/{region_code}/allim/allimList.json"
    cutoff = datetime.now() - timedelta(days=days)
    notices = []
    seen = set()

    for page in range(1, 4):  # max 3 pages
        try:
            resp = requests.post(api_url, data={"div_code": "2", "pn": str(page)}, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("result", {}).get("list", [])
            if not items:
                break

            for item in items:
                seq = str(item.get("SEQ", ""))
                title = item.get("TITLE", "").strip()
                reg_date = item.get("REG_DATE", "")
                if not seq or not title:
                    continue

                parsed_date = _parse_date(reg_date)
                if not parsed_date:
                    continue

                try:
                    dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

                if seq in seen:
                    continue
                seen.add(seq)

                source_name = f"CCEI-{region_name}"
                detail_url = f"https://ccei.creativekorea.or.kr/{region_code}/allim/allim_view.do?no={seq}&div_code=2"

                notices.append({
                    "source": source_name,
                    "title": title,
                    "organization": source_name,
                    "category": "입찰공고",
                    "bid_no": f"CCEI-ALLIM-{seq}",
                    "start_date": parsed_date,
                    "end_date": "",
                    "status": "ongoing",
                    "url": detail_url,
                    "keywords": "",
                    "detail_url": detail_url,
                    "apply_url": "",
                    "target": "",
                    "content": "",
                })

        except Exception as e:
            logger.warning(f"  CCEI {region_name} 페이지 {page} 요청 실패: {e}")
            break

    return notices


def scrape_busan_startup(days: int = 30) -> list[dict]:
    """부산창업포탈 지원사업 수집 (JSON API)."""
    api_url = "https://busanstartup.kr/_Api/bizListData"
    cutoff = datetime.now() - timedelta(days=days)
    notices = []

    for page in range(1, 4):
        try:
            resp = requests.get(api_url, params={"deadline": "N", "pageNo": str(page), "pageSize": "10"},
                                headers=DEFAULT_HEADERS, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("list", [])
            if not items:
                break

            for item in items:
                busi_code = str(item.get("busi_code", ""))
                title = (item.get("busi_title") or "").strip()
                raw_date = (item.get("regi_date") or "")[:10]  # "2025-03-27 10:50:56.0" -> "2025-03-27"
                if not busi_code or not title:
                    continue

                parsed_date = _parse_date(raw_date)
                if not parsed_date:
                    continue
                try:
                    if datetime.strptime(parsed_date, "%Y-%m-%d") < cutoff:
                        continue
                except ValueError:
                    continue

                notices.append({
                    "source": "부산창업포탈",
                    "title": title,
                    "organization": item.get("busi_comp", "부산창업포탈"),
                    "category": "지원사업",
                    "bid_no": f"BUSAN-{busi_code}",
                    "start_date": parsed_date,
                    "end_date": "",
                    "status": "ongoing",
                    "url": f"https://busanstartup.kr/biz_sup/{busi_code}?mcode=biz02",
                    "keywords": "",
                    "detail_url": f"https://busanstartup.kr/biz_sup/{busi_code}?mcode=biz02",
                    "apply_url": "",
                    "target": item.get("appl_type", ""),
                    "content": "",
                })
        except Exception as e:
            logger.warning(f"  부산창업포탈 페이지 {page} 요청 실패: {e}")
            break

    return notices


def scrape_ksd(days: int = 30) -> list[dict]:
    """한국예탁결제원 입찰공고 수집 (JSON API)."""
    api_url = "https://www.ksd.or.kr/ko/api/content"
    cutoff = datetime.now() - timedelta(days=days)
    notices = []

    try:
        resp = requests.get(api_url, params={"menuId": "KR_ABT_070300"}, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code != 200:
            return notices
        items = resp.json().get("body", {}).get("list", [])

        for item in items:
            ntt_id = str(item.get("nttId", ""))
            title = item.get("bbsSj", "").strip()
            raw_date = item.get("frstRegistPnttm", "")[:8]
            if not ntt_id or not title or len(raw_date) != 8:
                continue

            parsed_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            try:
                if datetime.strptime(parsed_date, "%Y-%m-%d") < cutoff:
                    continue
            except ValueError:
                continue

            notices.append({
                "source": "한국예탁결제원",
                "title": title,
                "organization": "한국예탁결제원",
                "category": "입찰공고",
                "bid_no": f"KSD-{ntt_id}",
                "start_date": parsed_date,
                "end_date": "",
                "status": "ongoing",
                "url": f"https://www.ksd.or.kr/ko/about-ksd/ksd-news/bid-notice?nttId={ntt_id}",
                "keywords": "",
                "detail_url": f"https://www.ksd.or.kr/ko/about-ksd/ksd-news/bid-notice?nttId={ntt_id}",
                "apply_url": "",
                "target": "",
                "content": "",
            })
    except Exception as e:
        logger.warning(f"  한국예탁결제원 요청 실패: {e}")

    return notices


# CCEI 입찰공고 7개 지역 설정
CCEI_ALLIM_REGIONS = [
    ("gyeonggi", "경기"),
    ("gyeongnam", "경남"),
    ("daegu", "대구"),
    ("busan", "부산"),
    ("sejong", "세종"),
    ("incheon", "인천"),
    ("chungbuk", "충북"),
]


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

    # POST 페이지네이션 지원
    post_data = config.get("post_data")  # POST 요청 시 전송할 form data (dict 또는 None)
    use_post = post_data is not None  # 빈 dict {}도 POST로 처리
    post_json = config.get("post_json", False)  # True이면 JSON body로 전송
    page_param_key = config.get("page_param_key", "")  # POST data 내 페이지 번호 키
    grid_selector = config.get("grid_selector", "")  # 응답 HTML 내 데이터 영역 셀렉터

    # 날짜 없는 항목 허용 (카드형 레이아웃 등 날짜가 리스트에 없는 사이트)
    skip_no_date = config.get("skip_no_date", True)

    # 세션 초기화 URL (쿠키 획득용)
    session_init_url = config.get("session_init_url", "")

    # JS 링크 패턴 → 실제 URL 변환 (e.g. "javascript:fncShow('10513')" → 실제 URL)
    link_js_regex = config.get("link_js_regex", "")  # e.g. "fncShow\\('(\\d+)'\\)"
    link_template = config.get("link_template", "")  # e.g. "/intro.asp?tmid=14&seq={id}"

    cutoff = datetime.now() - timedelta(days=days)
    notices = []
    seen = set()

    # offset 기반 페이지네이션 지원
    offset_size = config.get("offset_size", 0)

    # 세션 사용 (쿠키 유지)
    session = requests.Session()
    if session_init_url:
        try:
            session.get(session_init_url, headers=DEFAULT_HEADERS, timeout=10, verify=False)
        except requests.RequestException:
            pass

    for page in range(1, max_pages + 1):
        # URL 구성
        if use_post:
            url = list_url
        elif page == 1:
            url = list_url
        elif pagination:
            page_val = str(page)
            if offset_size:
                page_val = str((page - 1) * offset_size)
            url = list_url + pagination.replace("{page}", page_val).replace("{offset}", page_val)
        else:
            break  # 페이지네이션 없으면 1페이지만

        try:
            if use_post:
                form = dict(post_data)
                if page_param_key:
                    form[page_param_key] = page
                if post_json:
                    resp = session.post(url, headers={**DEFAULT_HEADERS, "Content-Type": "application/json;charset=UTF-8"}, json=form, timeout=15, verify=False)
                else:
                    resp = session.post(url, headers=DEFAULT_HEADERS, data=form, timeout=15, verify=False)
            else:
                resp = session.get(url, headers=DEFAULT_HEADERS, timeout=15, verify=False)
            if encoding.lower() != "utf-8":
                resp.encoding = encoding
            else:
                resp.encoding = resp.apparent_encoding or "utf-8"

            if resp.status_code != 200:
                logger.warning(f"  {name} 페이지 {page}: HTTP {resp.status_code}")
                break

            parser = config.get("parser", "html.parser")
            soup = BeautifulSoup(resp.text, parser)
            if grid_selector:
                grid = soup.select_one(grid_selector)
                if grid:
                    soup = grid
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
                if link_js_regex and link_template and link:
                    js_m = re.search(link_js_regex, link)
                    if js_m:
                        result_link = link_template
                        # {id} 호환 (그룹1) + {1},{2},{3}... 다중 그룹 지원
                        result_link = result_link.replace("{id}", js_m.group(1))
                        for gi in range(1, len(js_m.groups()) + 1):
                            result_link = result_link.replace(f"{{{gi}}}", js_m.group(gi))
                        link = result_link
                if link and not link.startswith("http") and not link.startswith("javascript:"):
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

                # 날짜 파싱 실패 시 스킵 (날짜 없는 행은 공지/안내글)
                if not parsed_date and skip_no_date:
                    continue
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


def collect_single_by_name(source_name: str, days: int = 1) -> dict:
    """기관명으로 단건 스크래핑 실행 (재시도용)."""
    configs = _load_configs()
    keywords = _load_common_keywords()
    if not keywords:
        return {"source": source_name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": "활성 키워드가 없습니다."}

    # scraper_configs.json에서 찾기
    for cfg in configs:
        if cfg["name"] == source_name:
            r = collect_single(source_name, cfg, keywords, days=days)
            _update_source_collected(source_name, r["matched"])
            return r

    # CCEI 입찰공고
    for region_code, region_name in CCEI_ALLIM_REGIONS:
        if source_name == f"CCEI-{region_name}":
            notices = scrape_ccei_allim(region_code, region_name, days=days)
            matched = _match_keywords(notices, keywords)
            inserted, updated = save_to_db(matched)
            r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
            _update_source_collected(source_name, r["matched"])
            return r

    # 부산창업포탈
    if source_name == "부산창업포탈":
        notices = scrape_busan_startup(days=days)
        matched = _match_keywords(notices, keywords)
        inserted, updated = save_to_db(matched)
        r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
        _update_source_collected(source_name, r["matched"])
        return r

    # 한국예탁결제원
    if source_name == "한국예탁결제원":
        notices = scrape_ksd(days=days)
        matched = _match_keywords(notices, keywords)
        inserted, updated = save_to_db(matched)
        r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
        _update_source_collected(source_name, r["matched"])
        return r

    return {"source": source_name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": f"'{source_name}' 설정을 찾을 수 없습니다."}


def _load_common_keywords() -> list[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT keyword FROM keywords WHERE is_active=1 AND source_id IS NULL")
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords


def _update_source_collected(source_name: str, count: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE collect_sources SET last_collected_at=datetime('now'), last_collected_count=? WHERE name=?",
        (count, source_name),
    )
    conn.commit()
    conn.close()


def collect_all_scrapers(days: int = 1, batch_time: str | None = None, mode: str = "daily") -> dict:
    """
    48개 스크래퍼 일괄 실행.
    days: 수집할 기간(일수).
    batch_time: 일괄 수집 시작 시간 (None이면 현재 시간 사용)
    """
    configs = _load_configs()
    if not configs:
        return {"total": 0, "success": 0, "failed": 0, "collected": 0, "matched": 0, "inserted": 0, "results": []}

    # 공통 키워드 로드
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT keyword FROM keywords WHERE is_active=1 AND source_id IS NULL")
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()

    if not keywords:
        logger.warning("활성 공통 키워드 없음 — 스크래핑 건너뜀")
        return {"total": len(configs), "success": 0, "failed": 0, "collected": 0, "matched": 0, "inserted": 0,
                "results": [], "error": "활성 키워드가 없습니다."}

    # batch_time이 없으면 현재 시간 사용
    if not batch_time:
        batch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                "UPDATE collect_sources SET last_collected_at=?, last_collected_count=? WHERE name=?",
                (batch_time, r["matched"], name),
            )
            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"  ❌ {name} 스크래핑 실패: {e}")
            results.append({"source": name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)})
            failed += 1

    # CCEI 입찰공고 7개 지역 수집
    for region_code, region_name in CCEI_ALLIM_REGIONS:
        source_name = f"CCEI-{region_name}"
        try:
            logger.info(f"  스크래핑: {source_name}")
            notices = scrape_ccei_allim(region_code, region_name, days=days)
            matched = _match_keywords(notices, keywords)
            inserted, updated = save_to_db(matched)

            r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
            results.append(r)
            success += 1
            total_collected += r["collected"]
            total_matched += r["matched"]
            total_inserted += r["inserted"]
            logger.info(f"  ✅ {source_name}: 수집 {r['collected']}건, 매칭 {r['matched']}건, 신규 {r['inserted']}건")

            # collect_sources 갱신
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE collect_sources SET last_collected_at=?, last_collected_count=? WHERE name=?",
                (batch_time, r["matched"], source_name),
            )
            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"  ❌ {source_name} 수집 실패: {e}")
            results.append({"source": source_name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)})
            failed += 1

    # 부산창업포탈 JSON API 수집
    try:
        source_name = "부산창업포탈"
        logger.info(f"  스크래핑: {source_name}")
        notices = scrape_busan_startup(days=days)
        matched = _match_keywords(notices, keywords)
        inserted, updated = save_to_db(matched)

        r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
        results.append(r)
        success += 1
        total_collected += r["collected"]
        total_matched += r["matched"]
        total_inserted += r["inserted"]
        logger.info(f"  ✅ {source_name}: 수집 {r['collected']}건, 매칭 {r['matched']}건, 신규 {r['inserted']}건")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE collect_sources SET last_collected_at=?, last_collected_count=? WHERE name=?",
            (batch_time, r["matched"], source_name),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"  ❌ 부산창업포탈 수집 실패: {e}")
        results.append({"source": "부산창업포탈", "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)})
        failed += 1

    # 한국예탁결제원 JSON API 수집
    try:
        source_name = "한국예탁결제원"
        logger.info(f"  스크래핑: {source_name}")
        notices = scrape_ksd(days=days)
        matched = _match_keywords(notices, keywords)
        inserted, updated = save_to_db(matched)

        r = {"source": source_name, "collected": len(notices), "matched": len(matched), "inserted": inserted, "updated": updated}
        results.append(r)
        success += 1
        total_collected += r["collected"]
        total_matched += r["matched"]
        total_inserted += r["inserted"]
        logger.info(f"  ✅ {source_name}: 수집 {r['collected']}건, 매칭 {r['matched']}건, 신규 {r['inserted']}건")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE collect_sources SET last_collected_at=?, last_collected_count=? WHERE name=?",
            (batch_time, r["matched"], source_name),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"  ❌ 한국예탁결제원 수집 실패: {e}")
        results.append({"source": "한국예탁결제원", "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)})
        failed += 1

    total_sites = len(configs) + len(CCEI_ALLIM_REGIONS) + 2  # +2 부산창업포탈, 한국예탁결제원
    return {
        "total": total_sites,
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
