"""인증 API 라우터"""

from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from database import get_connection, hash_password, verify_password
from auth import create_session, get_current_user, require_login, delete_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
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


@router.post("/logout")
def logout(request: Request):
    """로그아웃 → 세션 삭제"""
    token = request.cookies.get("session_token")
    if token:
        delete_session(token)
    response = JSONResponse(content={"success": True})
    response.delete_cookie("session_token")
    return response


@router.get("/me")
def get_me(request: Request):
    """현재 로그인 사용자 정���"""
    user = get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "로그인이 필요합니다."})
    return {"user": user}


@router.post("/change-password")
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
