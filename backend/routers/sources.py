"""출처 관리 API 라우터"""

import os
from fastapi import APIRouter, Query, Request, Body
from fastapi.responses import JSONResponse
from database import get_connection
from auth import require_login, require_admin, has_permission

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("")
def get_sources(request: Request):
    """출처 목록 (수집 상태 포함 + scraper URL)"""
    require_login(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collect_sources ORDER BY id")
    sources = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # scraper 출처에 URL 정보 추가
    scraper_sources = [s for s in sources if s.get("collector_type") == "scraper"]
    if scraper_sources:
        url_map = _build_scraper_url_map()
        for s in scraper_sources:
            s["site_url"] = url_map.get(s["name"], "")

    return sources


@router.post("")
def create_source(
    request: Request,
    name: str = Body(...),
    collector_type: str = Body(...),
):
    """출처 추가 (관리자)"""
    require_admin(request)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO collect_sources (name, collector_type) VALUES (?, ?)",
            (name.strip(), collector_type.strip()),
        )
        conn.commit()
        new_id = cursor.lastrowid
    except Exception as e:
        conn.close()
        return JSONResponse(status_code=400, content={"error": f"출처 추가 실패: {e}"})
    conn.close()
    return {"success": True, "id": new_id}


@router.put("/{source_id}")
def update_source(
    request: Request,
    source_id: int,
    name: str = Body(default=None),
    collector_type: str = Body(default=None),
    is_active: int = Body(default=None),
):
    """출처 수정 (관리자)"""
    require_admin(request)
    updates = {}
    if name is not None:
        updates["name"] = name.strip()
    if collector_type is not None:
        updates["collector_type"] = collector_type.strip()
    if is_active is not None:
        updates["is_active"] = is_active
    if not updates:
        return {"error": "변경할 항목이 없습니다."}

    conn = get_connection()
    cursor = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in updates)
    cursor.execute(f"UPDATE collect_sources SET {sets} WHERE id=?", (*updates.values(), source_id))
    conn.commit()
    conn.close()
    return {"success": True}


@router.delete("/{source_id}")
def delete_source(request: Request, source_id: int):
    """출처 삭제 (관리자)"""
    require_admin(request)
    conn = get_connection()
    cursor = conn.cursor()
    # 출처에 연결된 키워드도 삭제
    cursor.execute("DELETE FROM keywords WHERE source_id=?", (source_id,))
    cursor.execute("DELETE FROM collect_sources WHERE id=?", (source_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0}


@router.post("/{source_id}/collect")
def collect_by_source(
    request: Request,
    source_id: int,
    start_date: str = Query(default="", description="수집 시작일 (yyyy-MM-dd)"),
    end_date: str = Query(default="", description="수집 종료일 (yyyy-MM-dd)"),
):
    """개별 출처 수집 실행 (관리자). start_date~end_date 기간의 공고 수집."""
    require_admin(request)

    from routers.collection import _calc_days, _collect_lock, _collecting_targets

    days = _calc_days(start_date, end_date)

    source_key = f"source_{source_id}"
    with _collect_lock:
        if source_key in _collecting_targets:
            return JSONResponse(status_code=409, content={"error": "이 출처는 이미 수집 중입니다."})
        _collecting_targets.add(source_key)

    try:
        from collectors.collect_all import collect_by_source as _collect_by_source
        result = _collect_by_source(source_id, days=days)
        return result
    finally:
        with _collect_lock:
            _collecting_targets.discard(source_key)


@router.get("/{source_id}/keywords")
def get_source_keywords(request: Request, source_id: int):
    """출처 전용 추가 키워드 목록"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords WHERE source_id=? ORDER BY keyword_group, keyword", (source_id,))
    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


@router.post("/{source_id}/keywords")
def add_source_keyword(
    request: Request,
    source_id: int,
    keyword: str = Query(...),
    keyword_group: str = Query(default="출처 전용"),
):
    """출처에 추가 키워드 등록"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM keywords WHERE keyword=? AND source_id=?", (keyword.strip(), source_id))
    if cursor.fetchone():
        conn.close()
        return JSONResponse(status_code=400, content={"error": f"'{keyword}' 키워드가 이미 존재합니다."})
    cursor.execute(
        "INSERT INTO keywords (keyword, keyword_group, is_active, source_id) VALUES (?, ?, 1, ?)",
        (keyword.strip(), keyword_group.strip(), source_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.execute("SELECT * FROM keywords WHERE id=?", (new_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)


# ─── 헬퍼 ──────────────────────────────────────

def _build_scraper_url_map() -> dict:
    """scraper_configs.json + 하드코딩 소스에서 기관명→URL 매핑 생성"""
    import json as _json
    from config import COLLECTORS_DIR
    url_map = {}
    configs_path = os.path.join(COLLECTORS_DIR, "scraper_configs.json")
    if os.path.exists(configs_path):
        with open(configs_path, "r", encoding="utf-8") as f:
            for cfg in _json.load(f):
                name = cfg.get("name", "")
                url = cfg.get("list_url", "")
                url_map[name] = url
    # CCEI 입찰공고 7개 지역
    ccei_regions = [
        ("gyeonggi", "경기"), ("gyeongnam", "경남"), ("daegu", "대구"),
        ("busan", "부산"), ("sejong", "세종"), ("incheon", "인천"), ("chungbuk", "충북"),
    ]
    for code, rname in ccei_regions:
        url_map[f"CCEI-{rname}"] = f"https://ccei.creativekorea.or.kr/{code}/allim/allim_list.do?div_code=2"
    # 특수 스크래퍼
    url_map["부산창업포탈"] = "https://busanstartup.kr/biz_sup?mcode=biz02"
    url_map["한국예탁결제원"] = "https://www.ksd.or.kr/ko/about-ksd/ksd-news/bid-notice"
    return url_map
