"""설정 API ���우터"""

from fastapi import APIRouter, Query, Request, HTTPException
from database import get_connection
from auth import require_login, has_permission

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings(request: Request):
    """현재 표시 설정 조회"""
    require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM display_settings")
    settings = {row["setting_key"]: {"value": row["setting_value"], "description": row["description"]} for row in cursor.fetchall()}
    conn.close()
    return settings


@router.put("/{key}")
def update_setting(request: Request, key: str, value: str = Query(...)):
    """설정값 변경 (관리자 또는 perm_display 권한)"""
    user = require_login(request)
    if not has_permission(user, "display"):
        raise HTTPException(status_code=403, detail="표시 설정 변경 권한이 없습니다.")

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
