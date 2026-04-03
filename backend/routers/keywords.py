"""키워드 관리 API 라우터"""

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from database import get_connection
from auth import require_login, has_permission

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


@router.get("")
def get_keywords(request: Request):
    """키워드 목록 조회"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords ORDER BY keyword_group, keyword")
    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


@router.put("/{keyword_id}/toggle")
def toggle_keyword(request: Request, keyword_id: int):
    """키워드 활성/비활성 토글"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE keywords SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?", (keyword_id,))
    conn.commit()
    cursor.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"error": "not found"}


@router.post("")
def add_keyword(request: Request, keyword: str = Query(...), keyword_group: str = Query(default="사용자 추가")):
    """키워드 추가"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

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


@router.delete("/{keyword_id}")
def delete_keyword(request: Request, keyword_id: int):
    """키워드 삭제"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0, "deleted_id": keyword_id}


@router.get("/common")
def get_common_keywords(request: Request):
    """공통 키워드 목록 (source_id IS NULL)"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords WHERE source_id IS NULL ORDER BY keyword_group, keyword")
    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


@router.post("/common")
def add_common_keyword(
    request: Request,
    keyword: str = Query(...),
    keyword_group: str = Query(default="사용자 추가"),
):
    """공통 키워드 추가 (콤마로 여러 개 동시 입력 가능)"""
    user = require_login(request)
    if not has_permission(user, "keyword"):
        raise HTTPException(status_code=403, detail="키워드 관리 권한이 없습니다.")

    # 콤마로 분리하여 여러 개 처리
    raw_keywords = [kw.strip() for kw in keyword.split(",") if kw.strip()]
    if not raw_keywords:
        return JSONResponse(status_code=400, content={"error": "키워드를 입력해주세요."})

    conn = get_connection()
    cursor = conn.cursor()
    added = []
    skipped = []
    for kw in raw_keywords:
        cursor.execute("SELECT id FROM keywords WHERE keyword=? AND source_id IS NULL", (kw,))
        if cursor.fetchone():
            skipped.append(kw)
            continue
        cursor.execute(
            "INSERT INTO keywords (keyword, keyword_group, is_active, source_id) VALUES (?, ?, 1, NULL)",
            (kw, keyword_group.strip()),
        )
        added.append(kw)
    conn.commit()
    conn.close()

    # 단건이면 기존 호환, 다건이면 요약 반환
    if len(raw_keywords) == 1:
        if skipped:
            return JSONResponse(status_code=400, content={"error": f"'{skipped[0]}' 공통 키워드가 이미 존재합니다."})
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM keywords WHERE keyword=? AND source_id IS NULL", (added[0],))
        row = cursor.fetchone()
        conn.close()
        return dict(row)
    else:
        return {"added": added, "skipped": skipped, "added_count": len(added), "skipped_count": len(skipped)}
