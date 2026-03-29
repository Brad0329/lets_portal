"""
LETS 프로젝트 관리 시스템 - FastAPI 백엔드
"""

from fastapi import FastAPI, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import logging
import os


class TagRequest(BaseModel):
    tag: str
    memo: str = ""

from database import init_db, get_connection, hash_password, verify_password
from auth import (
    create_session, get_current_user, require_login, require_admin,
    has_permission, delete_session, cleanup_expired_sessions,
)
from collectors.collect_all import collect_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 초기화"""
    init_db()
    logger.info("DB 초기화 완료")

    yield


app = FastAPI(
    title="LETS 프로젝트 관리 시스템",
    description="입찰공고 통합 검색 및 프로젝트 관리",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS (프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# ─── 인증 API ─────────────────────────────────────

@app.post("/api/auth/login")
def login(request: Request, username: str = Body(...), password: str = Body(...)):
    """로그인 → 세션 쿠키 발급"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(password, row["password_hash"]):
        return JSONResponse(status_code=401, content={"error": "아이디 또는 비밀번호가 올바르지 않습니다."})

    user = dict(row)
    token = create_session(user["id"])

    response = JSONResponse(content={
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
            "must_change_pw": user["must_change_pw"],
        },
    })
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    """로그아웃 → 세션 삭제"""
    token = request.cookies.get("session_token")
    if token:
        delete_session(token)
    response = JSONResponse(content={"success": True})
    response.delete_cookie("session_token")
    return response


@app.get("/api/auth/me")
def get_me(request: Request):
    """현재 로그인 사용자 정보"""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "로그인이 필요합니다."})
    return {"user": user}


@app.post("/api/auth/change-password")
def change_password(
    request: Request,
    current_password: str = Body(...),
    new_password: str = Body(...),
):
    """비밀번호 변경"""
    user = require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    row = cursor.fetchone()

    if not verify_password(current_password, row["password_hash"]):
        conn.close()
        return JSONResponse(status_code=400, content={"error": "현재 비밀번호가 올바르지 않습니다."})

    if len(new_password) < 4:
        conn.close()
        return JSONResponse(status_code=400, content={"error": "새 비밀번호는 4자 이상이어야 합니다."})

    cursor.execute(
        "UPDATE users SET password_hash=?, must_change_pw=0, updated_at=datetime('now') WHERE id=?",
        (hash_password(new_password), user["id"]),
    )
    conn.commit()
    conn.close()
    return {"success": True}


# ─── 계정 관리 API (관리자 전용) ──────────────────

@app.get("/api/users")
def list_users(request: Request):
    """사용자 목록 조회"""
    require_admin(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, name, role, must_change_pw, perm_bid_tag, perm_display, perm_keyword, perm_org, created_at FROM users ORDER BY id")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users


@app.post("/api/users")
def create_user(
    request: Request,
    username: str = Body(...),
    name: str = Body(...),
    role: str = Body(default="staff"),
    perm_bid_tag: int = Body(default=0),
    perm_display: int = Body(default=0),
    perm_keyword: int = Body(default=0),
    perm_org: int = Body(default=0),
):
    """계정 생성 (관리자 전용) — 기본 비밀번호 '1234'"""
    require_admin(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username=?", (username,))
    if cursor.fetchone():
        conn.close()
        return JSONResponse(status_code=400, content={"error": f"'{username}' 아이디가 이미 존재합니다."})

    cursor.execute(
        """INSERT INTO users (username, name, password_hash, role, must_change_pw,
           perm_bid_tag, perm_display, perm_keyword, perm_org) VALUES (?,?,?,?,1,?,?,?,?)""",
        (username, name, hash_password("1234"), role, perm_bid_tag, perm_display, perm_keyword, perm_org),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"success": True, "id": new_id, "username": username, "default_password": "1234"}


@app.put("/api/users/{user_id}")
def update_user(
    request: Request,
    user_id: int,
    name: str = Body(default=None),
    role: str = Body(default=None),
    perm_bid_tag: int = Body(default=None),
    perm_display: int = Body(default=None),
    perm_keyword: int = Body(default=None),
    perm_org: int = Body(default=None),
):
    """계정 정보 수정 (관리자 전용)"""
    require_admin(request)

    updates = {}
    if name is not None:
        updates["name"] = name
    if role is not None:
        updates["role"] = role
    if perm_bid_tag is not None:
        updates["perm_bid_tag"] = perm_bid_tag
    if perm_display is not None:
        updates["perm_display"] = perm_display
    if perm_keyword is not None:
        updates["perm_keyword"] = perm_keyword
    if perm_org is not None:
        updates["perm_org"] = perm_org

    if not updates:
        return {"error": "변경할 항목이 없습니다."}

    conn = get_connection()
    cursor = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in updates)
    cursor.execute(f"UPDATE users SET {sets}, updated_at=datetime('now') WHERE id=?",
                   (*updates.values(), user_id))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/api/users/{user_id}/reset-password")
def reset_password(request: Request, user_id: int):
    """비밀번호 초기화 (관리자 전용) → '1234'로 리셋"""
    require_admin(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash=?, must_change_pw=1, updated_at=datetime('now') WHERE id=?",
        (hash_password("1234"), user_id),
    )
    conn.commit()
    conn.close()
    return {"success": True, "default_password": "1234"}


@app.delete("/api/users/{user_id}")
def delete_user(request: Request, user_id: int):
    """계정 삭제 (관리자 전용)"""
    admin = require_admin(request)
    if admin["id"] == user_id:
        return JSONResponse(status_code=400, content={"error": "자기 자신은 삭제할 수 없습니다."})

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0}


# ─── 공고 검색/조회 API ─────────────────────────────

@app.get("/api/notices")
def get_notices(
    request: Request,
    q: str = Query(default="", description="검색어"),
    source: str = Query(default="", description="출처 필터"),
    status: str = Query(default="", description="상태"),
    sort: str = Query(default="deadline", description="정렬"),
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

    if sort == "deadline":
        order = "CASE WHEN end_date = '' THEN 1 ELSE 0 END, end_date ASC"
    else:
        order = "CASE WHEN start_date = '' THEN 1 ELSE 0 END, start_date DESC"

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


@app.get("/api/notices/stats")
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


@app.get("/api/notices/tagged")
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


# ─── 공고 상세 조회 API ──────────────────────────

@app.get("/api/notices/{notice_id}")
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

    # 태그 정보 포함
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


# ─── 태그 관리 API ────────────────────────────────

@app.get("/api/notice-tags/{notice_id}")
def get_notice_tag(request: Request, notice_id: int):
    """공고의 태그 조회"""
    require_login(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nt.*, u.name as tagged_by_name
        FROM notice_tags nt LEFT JOIN users u ON nt.tagged_by = u.id
        WHERE nt.notice_id = ?
    """, (notice_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"tag": None}


@app.put("/api/notice-tags/{notice_id}")
def set_notice_tag(request: Request, notice_id: int, body: TagRequest):
    """공고에 태그 설정 — 검토요청: 모든 사용자, 입찰대상/제외/낙찰/유찰: 관리자(perm_bid_tag)"""
    user = require_login(request)

    valid_tags = ["검토요청", "입찰대상", "제외", "낙찰", "유찰"]
    if body.tag not in valid_tags:
        return JSONResponse(status_code=400, content={"error": f"유효하지 않은 태그입니다. ({', '.join(valid_tags)})"})

    # 검토요청은 모든 로그인 사용자, 나머지는 관리자/perm_bid_tag 권한 필요
    if body.tag != "검토요청" and not has_permission(user, "bid_tag"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="입찰예정/제외 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO notice_tags (notice_id, tag, tagged_by, memo)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(notice_id) DO UPDATE SET
            tag = excluded.tag,
            tagged_by = excluded.tagged_by,
            memo = excluded.memo,
            updated_at = datetime('now')
    """, (notice_id, body.tag, user["id"], body.memo))
    conn.commit()
    conn.close()
    return {"success": True, "notice_id": notice_id, "tag": body.tag}


@app.delete("/api/notice-tags/{notice_id}")
def remove_notice_tag(request: Request, notice_id: int):
    """공고 태그 제거 (복원) — 검토요청은 본인 해제 가능, 나머지는 관리자"""
    user = require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tag, tagged_by FROM notice_tags WHERE notice_id=?", (notice_id,))
    tag_row = cursor.fetchone()
    conn.close()

    if tag_row:
        # 검토요청 태그는 본인이 해제 가능, 나머지는 관리자/perm_bid_tag
        if tag_row["tag"] != "검토요청" and not has_permission(user, "bid_tag"):
            raise __import__("fastapi").HTTPException(status_code=403, detail="입찰예정/제외 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notice_tags WHERE notice_id=?", (notice_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0}




# ─── 설정 API ────────────────────────────────────

@app.get("/api/settings")
def get_settings(request: Request):
    """현재 표시 설정 조회"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM display_settings")
    settings = {row["setting_key"]: {"value": row["setting_value"], "description": row["description"]} for row in cursor.fetchall()}
    conn.close()
    return settings


@app.put("/api/settings/{key}")
def update_setting(request: Request, key: str, value: str = Query(...)):
    """설정값 변경 (관리자 또는 perm_display 권한)"""
    user = require_login(request)
    if not has_permission(user, "display"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="표시 설정 변경 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE display_settings SET setting_value=?, updated_at=datetime('now') WHERE setting_key=?",
        (value, key),
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        return {"error": f"설정키 '{key}'를 찾을 수 없습니다."}
    return {"success": True, "key": key, "value": value}


# ─── 키워드 관리 API ─────────────────────────────

@app.get("/api/keywords")
def get_keywords(request: Request):
    """키워드 목록 조회"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords ORDER BY keyword_group, keyword")
    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


@app.put("/api/keywords/{keyword_id}/toggle")
def toggle_keyword(request: Request, keyword_id: int):
    """키워드 활성/비활성 토글"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE keywords SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?", (keyword_id,))
    conn.commit()
    cursor.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"error": "not found"}


@app.post("/api/keywords")
def add_keyword(request: Request, keyword: str = Query(...), keyword_group: str = Query(default="사용자 추가")):
    """키워드 추가"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM keywords WHERE keyword=?", (keyword.strip(),))
    if cursor.fetchone():
        conn.close()
        return {"error": f"'{keyword}' 키워드가 이미 존재합니다."}
    cursor.execute(
        "INSERT INTO keywords (keyword, keyword_group, is_active) VALUES (?, ?, 1)",
        (keyword.strip(), keyword_group.strip()),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.execute("SELECT * FROM keywords WHERE id=?", (new_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/keywords/{keyword_id}")
def delete_keyword(request: Request, keyword_id: int):
    """키워드 삭제"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0, "deleted_id": keyword_id}


# ─── 기관 관리 API ────────────────────────────────

@app.get("/api/organizations")
def get_organizations(request: Request):
    """기관 목록 조회"""
    user = require_login(request)
    if not has_permission(user, "org"):
        raise __import__("fastapi").HTTPException(status_code=403, detail="기관 목록 조회 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM organizations ORDER BY category, name")
    orgs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return orgs


# ─── 수집 실행 API ────────────────────────────────

@app.post("/api/collect")
def run_collect(request: Request):
    """수동으로 전체 수집 실행 (관리자 전용)"""
    require_admin(request)
    results = collect_all()
    return {"results": results}


# ─── 프론트엔드 정적파일 ──────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    # 명시적 HTML 페이지 라우트
    @app.get("/login.html")
    def login_page():
        return FileResponse(os.path.join(frontend_dir, "login.html"))

    @app.get("/settings.html")
    def settings_page():
        return FileResponse(os.path.join(frontend_dir, "settings.html"))

    @app.get("/dashboard.html")
    def dashboard_page():
        return FileResponse(os.path.join(frontend_dir, "dashboard.html"))

    @app.get("/review-list.html")
    def review_list_page():
        return FileResponse(os.path.join(frontend_dir, "review-list.html"))

    @app.get("/bid-list.html")
    def bid_list_page():
        return FileResponse(os.path.join(frontend_dir, "bid-list.html"))

    @app.get("/excluded-list.html")
    def excluded_list_page():
        return FileResponse(os.path.join(frontend_dir, "excluded-list.html"))

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
