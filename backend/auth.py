"""인증/세션 관리 모듈"""

import secrets
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
from database import get_connection, hash_password, verify_password


SESSION_HOURS = 24  # 세션 유효 시간


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    conn = get_connection()
    cursor = conn.cursor()
    expires = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    conn.commit()
    conn.close()
    return token


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("session_token")
    if not token:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.name, u.role, u.must_change_pw,
               u.perm_bid_tag, u.perm_display, u.perm_keyword, u.perm_org
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > datetime('now')
    """, (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None
    return dict(row)


def require_login(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


def has_permission(user: dict, perm: str) -> bool:
    if user["role"] == "admin":
        return True
    return bool(user.get(f"perm_{perm}", 0))


def delete_session(token: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def cleanup_expired_sessions():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
    conn.commit()
    conn.close()
