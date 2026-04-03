"""공고 검색/조회 API 라우터"""

import logging
from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from database import get_connection
from auth import require_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("")
def get_notices(
    request: Request,
    q: str = Query(default="", description="검색어"),
    source: str = Query(default="", description="출처 필터"),
    status: str = Query(default="", description="상태"),
    sort: str = Query(default="latest", description="정렬"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """공고 목록 조회 (검색 + 필터 + 페이지네이션)"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()

    if not status:
        cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
        row = cursor.fetchone()
        status = row[0] if row else "ongoing"

    # 조회 기간 (입찰공고일 기준)
    cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='date_range_days'")
    row = cursor.fetchone()
    date_range_days = int(row[0]) if row else 30

    conditions = []
    params = []

    # 제외 태그 공고 숨김
    conditions.append("id NOT IN (SELECT notice_id FROM notice_tags WHERE tag='제외')")

    # 입찰공고일 기준 최근 N일 필터
    conditions.append("start_date >= date('now', ?)")
    params.append(f"-{date_range_days} days")

    if status and status != "all":
        conditions.append("status = ?")
        params.append(status)

    if source:
        conditions.append("source = ?")
        params.append(source)

    if q:
        conditions.append("(title LIKE ? OR organization LIKE ? OR keywords LIKE ?)")
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    kw_count_expr = "CASE WHEN keywords IS NULL OR keywords = '' THEN 0 ELSE LENGTH(keywords) - LENGTH(REPLACE(keywords, ',', '')) + 1 END"
    if sort == "deadline":
        order = f"CASE WHEN end_date = '' THEN 1 ELSE 0 END, end_date ASC, {kw_count_expr} DESC"
    else:
        order = f"CASE WHEN start_date = '' THEN 1 ELSE 0 END, start_date DESC, {kw_count_expr} DESC"

    cursor.execute(f"SELECT COUNT(*) FROM bid_notices WHERE {where_clause}", params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * size
    cursor.execute(
        f"SELECT * FROM bid_notices WHERE {where_clause} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [size, offset],
    )
    rows = cursor.fetchall()
    conn.close()

    notices = [dict(row) for row in rows]

    return {
        "total": total,
        "page": page,
        "size": size,
        "total_pages": (total + size - 1) // size,
        "notices": notices,
    }


@router.get("/sources")
def get_notice_sources(request: Request):
    """실제 공고가 있는 출처 목록 (건수 포함)"""
    require_login(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT source, COUNT(*) as count FROM bid_notices
        WHERE id NOT IN (SELECT notice_id FROM notice_tags WHERE tag = '제외')
        GROUP BY source ORDER BY count DESC
    """)
    sources = [{"source": row["source"], "count": row["count"]} for row in cursor.fetchall()]
    conn.close()
    return sources


@router.get("/stats")
def get_stats(request: Request):
    """소스별 통계"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT source,
               COUNT(*) as total,
               SUM(CASE WHEN status='ongoing' THEN 1 ELSE 0 END) as ongoing,
               SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) as closed
        FROM bid_notices GROUP BY source
    """)
    stats = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM bid_notices")
    grand_total = cursor.fetchone()[0]

    cursor.execute("SELECT MAX(collected_at) FROM bid_notices")
    last_collected = cursor.fetchone()[0]

    # 태그별 건수
    cursor.execute("SELECT tag, COUNT(*) as cnt FROM notice_tags GROUP BY tag")
    tag_stats = {row["tag"]: row["cnt"] for row in cursor.fetchall()}

    conn.close()
    return {"grand_total": grand_total, "last_collected": last_collected, "by_source": stats, "tag_stats": tag_stats}


@router.get("/tagged")
def get_tagged_notices(
    request: Request,
    tag: str = Query(..., description="태그 필터"),
    q: str = Query(default=""),
    source: str = Query(default=""),
    sort: str = Query(default="latest"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """태그별 공고 목록 조회"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()

    conditions = ["nt.tag = ?"]
    params = [tag]

    if source:
        conditions.append("bn.source = ?")
        params.append(source)
    if q:
        conditions.append("(bn.title LIKE ? OR bn.organization LIKE ? OR bn.keywords LIKE ?)")
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q])

    where_clause = " AND ".join(conditions)

    if sort == "deadline":
        order = "CASE WHEN bn.end_date = '' THEN 1 ELSE 0 END, bn.end_date ASC"
    elif sort == "tagged":
        order = "nt.updated_at DESC"
    else:
        order = "CASE WHEN bn.start_date = '' THEN 1 ELSE 0 END, bn.start_date DESC"

    cursor.execute(f"SELECT COUNT(*) FROM notice_tags nt JOIN bid_notices bn ON nt.notice_id = bn.id WHERE {where_clause}", params)
    total = cursor.fetchone()[0]

    offset = (page - 1) * size
    cursor.execute(f"""
        SELECT bn.*, nt.tag, nt.memo as tag_memo, nt.updated_at as tagged_at, u.name as tagged_by_name
        FROM notice_tags nt
        JOIN bid_notices bn ON nt.notice_id = bn.id
        LEFT JOIN users u ON nt.tagged_by = u.id
        WHERE {where_clause}
        ORDER BY {order} LIMIT ? OFFSET ?
    """, params + [size, offset])
    rows = cursor.fetchall()
    conn.close()

    return {
        "total": total,
        "page": page,
        "size": size,
        "total_pages": (total + size - 1) // size,
        "notices": [dict(row) for row in rows],
    }


@router.get("/{notice_id}")
def get_notice_detail(request: Request, notice_id: int):
    """공고 상세 조회"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bid_notices WHERE id=?", (notice_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"error": "공고를 찾을 수 없습니다."}

    notice = dict(row)

    # 태그 정보 포��
    cursor.execute("""
        SELECT nt.tag, nt.memo, nt.updated_at as tagged_at, u.name as tagged_by_name
        FROM notice_tags nt LEFT JOIN users u ON nt.tagged_by = u.id
        WHERE nt.notice_id = ?
    """, (notice_id,))
    tag_row = cursor.fetchone()
    conn.close()
    if tag_row:
        notice["tag"] = tag_row["tag"]
        notice["tag_memo"] = tag_row["memo"]
        notice["tagged_at"] = tag_row["tagged_at"]
        notice["tagged_by_name"] = tag_row["tagged_by_name"]

    if notice["source"] == "K-Startup" and not notice.get("content"):
        try:
            detail = _fetch_kstartup_detail(notice["bid_no"])
            if detail:
                notice.update(detail)
                _update_notice_detail(notice_id, detail)
        except Exception as e:
            logger.warning(f"K-Startup 상세 조회 실패: {e}")

    return notice


@router.delete("/old")
def delete_old_notices(request: Request, before_date: str = Query(...)):
    """입찰공고게시일 기준으로 이전 데이터 삭제 (태그 있는 공고 보존)"""
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")

    conn = get_connection()
    cursor = conn.cursor()

    # 삭제 대상 건수 조회 (태그 있는 공고 제외)
    cursor.execute("""
        SELECT COUNT(*) FROM bid_notices
        WHERE start_date <= ?
        AND id NOT IN (SELECT notice_id FROM notice_tags)
    """, (before_date,))
    count = cursor.fetchone()[0]

    if count == 0:
        conn.close()
        return {"deleted": 0, "message": "삭제할 데이터가 없습니다."}

    # 삭제 실행
    cursor.execute("""
        DELETE FROM bid_notices
        WHERE start_date <= ?
        AND id NOT IN (SELECT notice_id FROM notice_tags)
    """, (before_date,))
    conn.commit()
    conn.close()

    return {"deleted": count, "message": f"{before_date} 이전 공고 {count}건 삭제 완료 (태그 공고 보존)"}


# ─── 헬퍼 함수 ──────────────────────────────────────

def _fetch_kstartup_detail(bid_no: str) -> dict | None:
    """K-Startup API에서 단건 상세 조회"""
    import requests
    import html as html_mod
    from config import DATA_GO_KR_KEY

    url = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
    params = {
        "serviceKey": DATA_GO_KR_KEY,
        "page": 1,
        "perPage": 1,
        "returnType": "json",
        "cond[pbanc_sn::EQ]": bid_no,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", [])
    if not items:
        return None

    item = items[0]
    def _c(v):
        if not v: return ""
        v = html_mod.unescape(v)
        return v.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n").strip()

    return {
        "content": _c(item.get("pbanc_ctnt", ""))[:500],
        "target": _c(item.get("aply_trgt_ctnt", "")),
        "region": item.get("supt_regin") or "",
        "contact": item.get("prch_cnpl_no") or "",
        "detail_url": item.get("detl_pg_url") or "",
        "apply_url": item.get("biz_aply_url") or "",
        "apply_method": _c(item.get("aply_mthd_onli_rcpt_istc") or item.get("aply_mthd_vst_rcpt_istc") or ""),
        "biz_enyy": item.get("biz_enyy") or "",
        "target_age": item.get("biz_trgt_age") or "",
        "department": _c(item.get("biz_prch_dprt_nm") or ""),
        "excl_target": _c(item.get("aply_excl_trgt_ctnt") or ""),
        "biz_name": _c(item.get("intg_pbanc_biz_nm") or ""),
    }


def _update_notice_detail(notice_id: int, detail: dict):
    """실시간 조회 결과를 DB에 캐시"""
    conn = get_connection()
    cursor = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in detail)
    cursor.execute(f"UPDATE bid_notices SET {sets} WHERE id=?", (*detail.values(), notice_id))
    conn.commit()
    conn.close()
