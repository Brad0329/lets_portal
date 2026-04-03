"""계정 관리 API 라우터 (관리자 전용)"""

from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from database import get_connection, hash_password
from auth import require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(request: Request):
    """사용자 목록 조회"""
    require_admin(request)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, name, role, must_change_pw, perm_bid_tag, perm_display, perm_keyword, perm_org, created_at FROM users ORDER BY id")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users


@router.post("")
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


@router.put("/{user_id}")
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


@router.post("/{user_id}/reset-password")
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


@router.delete("/{user_id}")
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
