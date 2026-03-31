"""
첨부파일 자동 수집 모듈
- 검토요청/입찰대상 태그 설정 시 상세페이지를 스크래핑하여 첨부파일 목록 추출
- K-Startup, CCEI 전용 파서 + 범용 휴리스틱 추출기
"""

import json
import logging
import os
import re
import sys
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_connection

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 파일 확장자 패턴
FILE_EXT_PATTERN = re.compile(
    r"\.(?:pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip|rar|7z|alz|egg)(?:\?|$|#|&)",
    re.IGNORECASE,
)

# 다운로드 URL 패턴
DOWNLOAD_URL_PATTERN = re.compile(
    r"(?:download|fileDown|attachDown|getFile|file_download|dnFile|atchFileDown)",
    re.IGNORECASE,
)


def scrape_attachments_bg(notice_id: int, source: str, detail_url: str):
    """백그라운드 엔트리포인트: 상세페이지에서 첨부파일 추출 후 DB 저장"""
    try:
        logger.info(f"📎 첨부파일 수집 시작: notice_id={notice_id}, source={source}")
        soup = _fetch_page(detail_url)
        if not soup:
            logger.warning(f"📎 페이지 로드 실패: {detail_url}")
            _save_attachments(notice_id, [])
            return

        # 출처별 파서 라우팅
        base_url = f"{urlparse(detail_url).scheme}://{urlparse(detail_url).netloc}"

        if source == "K-Startup":
            attachments = _extract_kstartup(soup, base_url)
        elif "CCEI" in source or "창조경제" in source:
            attachments = _extract_ccei(soup, base_url)
        else:
            attachments = _extract_generic(soup, base_url, detail_url)

        _save_attachments(notice_id, attachments)
        logger.info(f"📎 첨부파일 수집 완료: notice_id={notice_id}, {len(attachments)}개 파일")

    except Exception as e:
        logger.error(f"📎 첨부파일 수집 실패: notice_id={notice_id}, {e}")
        _save_attachments(notice_id, [])


def _fetch_page(url: str) -> BeautifulSoup | None:
    """상세페이지 HTML 가져오기 (세션 쿠키 자동 획득)"""
    try:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        # 일부 사이트는 메인페이지 접근으로 쿠키 획득이 필요
        parsed = urlparse(url)
        main_url = f"{parsed.scheme}://{parsed.netloc}"
        try:
            session.get(main_url, timeout=10, verify=False)
        except Exception:
            pass  # 메인페이지 접근 실패해도 상세페이지 시도

        resp = session.get(url, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "html.parser")
        logger.warning(f"📎 HTTP {resp.status_code}: {url}")
        return None
    except Exception as e:
        logger.error(f"📎 요청 실패: {url} → {e}")
        return None


# ─── K-Startup 전용 파서 ──────────────────────────────
def _extract_kstartup(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """K-Startup 상세페이지에서 첨부파일 추출
    구조: div.btn_wrap 안에 다운로드 링크, 파일명은 btn_wrap의 이전 형제 <a> 텍스트
    """
    attachments = []

    for a in soup.find_all("a", href=re.compile(r"/afile/fileDownload/")):
        href = a.get("href", "")
        if not href:
            continue
        url = urljoin(base_url, href)

        # 파일명: btn_wrap div의 이전 형제 <a> 태그 텍스트
        name = ""
        btn_wrap = a.find_parent("div", class_="btn_wrap")
        if btn_wrap:
            prev_sibling = btn_wrap.find_previous_sibling("a")
            if prev_sibling:
                name = prev_sibling.get_text(strip=True)

        if not name or name in ("바로보기", "다운로드"):
            name = _filename_from_url(url)

        attachments.append({"name": name, "url": url})

    return _deduplicate(attachments)


# ─── CCEI 전용 파서 ──────────────────────────────────
def _extract_ccei(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """CCEI 상세페이지에서 첨부파일 추출
    구조: a[href*="fileDown.download?uuid="]
    """
    attachments = []

    for a in soup.find_all("a", href=re.compile(r"fileDown\.download\?uuid=")):
        href = a.get("href", "")
        if not href:
            continue
        url = urljoin(base_url, href)
        name = a.get_text(strip=True)
        # CCEI는 텍스트에 "첨부파일" 접두어가 있을 수 있음
        name = re.sub(r"^_?첨부파일_?\s*", "", name).strip()
        if not name:
            name = _filename_from_url(url)
        attachments.append({"name": name, "url": url})

    return _deduplicate(attachments)


# ─── 중소벤처기업부 전용 파서 ──────────────────────────
def _extract_mss(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """중소벤처기업부 상세페이지에서 첨부파일 추출
    구조: li > div.info(span.name=파일명) + div.link(Download URL)
    """
    attachments = []

    for li in soup.select("li"):
        dl_link = li.select_one('a[href*="Download.do"]')
        if not dl_link:
            continue
        href = dl_link.get("href", "")
        url = urljoin(base_url, href)

        # 파일명 우선순위:
        # 1. span.name 텍스트 (zip 파일 등)
        # 2. 바로보기 title 속성 (hwpx, pdf 등)
        # 3. URL에서 추출
        name = ""
        name_span = li.select_one("span.name")
        if name_span:
            name = name_span.get_text(strip=True)
            # 크기 정보 제거: "[붙임_1]_신청방법.zip  [209.4 KB]" → "[붙임_1]_신청방법.zip"
            name = re.sub(r"\s*\[[\d.]+ [KMG]?B\]\s*$", "", name).strip()

        if not name or name == "내려받기":
            view_link = li.select_one('a[title]')
            if view_link:
                title = view_link.get("title", "")
                name = re.sub(r"\s*새\s*창\s*열림\s*$", "", title).strip()

        if not name or name == "내려받기":
            name = _filename_from_url(url)

        attachments.append({"name": name, "url": url})

    return _deduplicate(attachments)


# ─── 범용 휴리스틱 추출기 ──────────────────────────────
def _extract_generic(soup: BeautifulSoup, base_url: str, detail_url: str) -> list[dict]:
    """범용 첨부파일 추출 — 스크래퍼 48개 사이트 대응
    전략:
    1. 파일 확장자가 포함된 링크
    2. 다운로드 패턴이 포함된 링크
    3. "첨부" 영역 내 링크
    """
    attachments = []
    seen_urls = set()

    # ─── 중소벤처기업부 전용 처리 ───
    if "mss.go.kr" in detail_url:
        return _extract_mss(soup, base_url)

    all_links = soup.find_all("a", href=True)

    for a in all_links:
        href = a.get("href", "").strip()
        if not href or href.startswith("#"):
            continue

        # javascript: 링크에서 파일 다운로드 패턴 추출
        if href.startswith("javascript:"):
            js_file = _parse_js_download(href, base_url, detail_url)
            if js_file:
                name = a.get_text(strip=True) or js_file["name"]
                # 파일 크기 표시 제거 (예: "(69KB)")
                name = re.sub(r"\(\d+[KMG]?B\)$", "", name).strip()
                if js_file["url"] not in seen_urls:
                    seen_urls.add(js_file["url"])
                    attachments.append({"name": name, "url": js_file["url"]})
            continue

        full_url = urljoin(detail_url, href)
        if full_url in seen_urls:
            continue

        is_file = False

        # 기준 1: 파일 확장자
        if FILE_EXT_PATTERN.search(href):
            is_file = True

        # 기준 2: 다운로드 URL 패턴
        if not is_file and DOWNLOAD_URL_PATTERN.search(href):
            is_file = True

        # 기준 3: "첨부" 영역 내 링크 (부모 요소에 첨부/다운로드 관련 텍스트)
        if not is_file:
            parent = a.find_parent(["div", "td", "li", "section"])
            if parent:
                parent_text = parent.get_text()
                if re.search(r"첨부|다운로드|관련파일|첨부파일|붙임", parent_text):
                    # 해당 영역 내 파일 확장자 또는 다운로드 패턴 링크
                    if FILE_EXT_PATTERN.search(href) or DOWNLOAD_URL_PATTERN.search(href):
                        is_file = True

        if is_file:
            seen_urls.add(full_url)
            name = a.get_text(strip=True)
            if not name or len(name) > 200:
                name = _filename_from_url(full_url)
            # 이미지 파일 제외 (본문 인라인 이미지일 가능성)
            if re.search(r"\.(?:jpg|jpeg|png|gif|bmp|svg|ico)(?:\?|$)", full_url, re.IGNORECASE):
                continue
            attachments.append({"name": name, "url": full_url})

    return _deduplicate(attachments)


# ─── 유틸리티 ──────────────────────────────────────────
def _parse_js_download(href: str, base_url: str, detail_url: str) -> dict | None:
    """javascript: 링크에서 파일 다운로드 URL 추출
    지원 패턴:
    - fncFileDownload('bbs','파일명.hwp')
    - fn_fileDown('파일경로')
    - fileDownload('id')
    """
    # 패턴 1: fncFileDownload('카테고리','파일명')  — 인천테크노파크 등
    m = re.search(r"fncFileDownload\s*\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", href)
    if m:
        category, filename = m.group(1), m.group(2)
        # 일반적인 다운로드 URL 패턴
        url = f"{base_url}/inc/download.asp?cate={category}&fname={filename}"
        return {"name": filename, "url": url}

    # 패턴 2: fileDown('id') — 한국지식재산보호원 등
    m = re.search(r"fileDown\s*\(\s*'(\d+)'\s*\)", href)
    if m:
        file_id = m.group(1)
        url = f"{base_url}/home/board/fileDown.do?file_no={file_id}"
        return {"name": f"첨부파일_{file_id}", "url": url}

    # 패턴 3: 일반적인 파일명이 포함된 JS 함수 호출
    m = re.search(r"['\"]([^'\"]+\.(?:pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip))['\"]", href, re.IGNORECASE)
    if m:
        filename = m.group(1)
        if filename.startswith("http"):
            return {"name": filename.split("/")[-1], "url": filename}
        return {"name": filename, "url": urljoin(detail_url, filename)}

    return None


def _filename_from_url(url: str) -> str:
    """URL에서 파일명 추출"""
    path = urlparse(url).path
    filename = unquote(path.split("/")[-1])
    if not filename or filename == "/":
        return "첨부파일"
    return filename


def _deduplicate(attachments: list[dict]) -> list[dict]:
    """URL 기준 중복 제거"""
    seen = set()
    result = []
    for att in attachments:
        if att["url"] not in seen:
            seen.add(att["url"])
            result.append(att)
    return result


def _save_attachments(notice_id: int, attachments: list[dict]):
    """첨부파일 목록을 DB에 저장"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        json_str = json.dumps(attachments, ensure_ascii=False)
        cursor.execute(
            "UPDATE bid_notices SET attachments=? WHERE id=?",
            (json_str, notice_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"📎 DB 저장 실패: notice_id={notice_id}, {e}")
