"""기관/나라장터 카테고리 API 라우터"""

from fastapi import APIRouter, Request, HTTPException
from database import get_connection
from auth import require_login, has_permission

router = APIRouter(tags=["organizations"])


@router.get("/api/nara-categories")
def get_nara_categories(request: Request):
    """나라장터 관심 중분류 목록"""
    require_login(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, large_class, mid_class, is_active FROM nara_interest_categories ORDER BY id")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


@router.put("/api/nara-categories/{cat_id}")
def update_nara_category(request: Request, cat_id: int, body: dict):
    """나라장터 관심 중분류 활성/비활성 토글"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 필요합니다.")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE nara_interest_categories SET is_active=? WHERE id=?", (body.get("is_active", 1), cat_id))
    conn.commit()
    conn.close()
    return {"success": True}


@router.get("/api/organizations")
def get_organizations(request: Request):
    """기관 목록 조회"""
    user = require_login(request)
    if not has_permission(user, "org"):
        raise HTTPException(status_code=403, detail="기관 목록 조회 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM organizations ORDER BY category, name")
    orgs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return orgs
