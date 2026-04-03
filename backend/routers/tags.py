"""태그 관리 API 라우터"""

from pydantic import BaseModel
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from database import get_connection
from auth import require_login, has_permission

router = APIRouter(prefix="/api/notice-tags", tags=["tags"])


class TagRequest(BaseModel):
    tag: str
    memo: str = ""


@router.get("/{notice_id}")
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


@router.put("/{notice_id}")
def set_notice_tag(request: Request, notice_id: int, body: TagRequest):
    """공고에 태그 설정 — 검토요청: 모든 사용자, 입찰대상/제외/낙찰/유찰: 관리자(perm_bid_tag)"""
    user = require_login(request)

    valid_tags = ["검토요청", "입찰대상", "제외", "낙찰", "유찰"]
    if body.tag not in valid_tags:
        return JSONResponse(status_code=400, content={"error": f"유효하지 않은 태그입니다. ({', '.join(valid_tags)})"})

    # 낙찰/유찰은 관리자/perm_bid_tag 권한 필요, 검토요청/입찰대상/제외는 모든 로그인 사용자
    if body.tag in ("낙찰", "유찰") and not has_permission(user, "bid_tag"):
        raise HTTPException(status_code=403, detail="낙찰/유찰 태그 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    if body.memo:
        # memo가 있으면 덮어쓰기
        cursor.execute("""
            INSERT INTO notice_tags (notice_id, tag, tagged_by, memo)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(notice_id) DO UPDATE SET
                tag = excluded.tag,
                tagged_by = excluded.tagged_by,
                memo = excluded.memo,
                updated_at = datetime('now')
        """, (notice_id, body.tag, user["id"], body.memo))
    else:
        # memo가 없으면 기존 memo 유지
        cursor.execute("""
            INSERT INTO notice_tags (notice_id, tag, tagged_by, memo)
            VALUES (?, ?, ?, '')
            ON CONFLICT(notice_id) DO UPDATE SET
                tag = excluded.tag,
                tagged_by = excluded.tagged_by,
                updated_at = datetime('now')
        """, (notice_id, body.tag, user["id"]))
    conn.commit()
    conn.close()

    # 검토요청/입찰대상 시 첨부파일 백그라운드 수집
    attachment_scraping = False
    if body.tag in ("검토요청", "입찰대상"):
        conn2 = get_connection()
        cur2 = conn2.cursor()
        cur2.execute("SELECT source, detail_url, url, attachments FROM bid_notices WHERE id=?", (notice_id,))
        row = cur2.fetchone()
        conn2.close()

        if row:
            source = row["source"]
            detail = row["detail_url"] or row["url"]
            has_attach = row["attachments"] and row["attachments"] not in ("", "[]")

            if source != "나라장터" and not has_attach and detail:
                import threading
                from collectors.attachment_scraper import scrape_attachments_bg
                threading.Thread(target=scrape_attachments_bg, args=(notice_id, source, detail), daemon=True).start()
                attachment_scraping = True

    return {"success": True, "notice_id": notice_id, "tag": body.tag, "attachment_scraping": attachment_scraping}


@router.delete("/{notice_id}")
def remove_notice_tag(request: Request, notice_id: int):
    """공고 태그 제거 (복원) — 검토요청은 본인 해제 가능, 나머지는 관리자"""
    user = require_login(request)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tag, tagged_by FROM notice_tags WHERE notice_id=?", (notice_id,))
    tag_row = cursor.fetchone()
    conn.close()

    if tag_row:
        # 낙찰/유찰 태그 해제는 관리자/perm_bid_tag 필요
        if tag_row["tag"] in ("낙찰", "유찰") and not has_permission(user, "bid_tag"):
            raise HTTPException(status_code=403, detail="낙찰/유찰 태그 해제 권한이 없습니다.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notice_tags WHERE notice_id=?", (notice_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0}
