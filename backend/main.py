"""
입찰공고 포탈서비스 - FastAPI 백엔드
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import os

from database import init_db, get_connection
from collectors.collect_all import collect_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 초기화 + 스케줄러 시작"""
    init_db()
    logger.info("DB 초기화 완료")

    # APScheduler - 매일 오전 9시, 오후 2시 자동 수집
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(collect_all, 'cron', hour='9,14', minute=0, id='auto_collect')
    scheduler.start()
    logger.info("자동 수집 스케줄러 시작 (매일 09:00, 14:00)")

    yield

    scheduler.shutdown()
    logger.info("스케줄러 종료")


app = FastAPI(
    title="입찰공고 포탈서비스",
    description="주요 입찰/사업공고 통합 검색 서비스",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 공고 검색/조회 API ─────────────────────────────

@app.get("/api/notices")
def get_notices(
    q: str = Query(default="", description="검색어"),
    source: str = Query(default="", description="출처 필터 (K-Startup, 중소벤처기업부, 나라장터)"),
    status: str = Query(default="", description="상태 (ongoing, closed, all)"),
    sort: str = Query(default="deadline", description="정렬 (deadline, latest)"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """공고 목록 조회 (검색 + 필터 + 페이지네이션)"""
    conn = get_connection()
    cursor = conn.cursor()

    # 설정에서 기본값 로드
    if not status:
        cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
        row = cursor.fetchone()
        status = row[0] if row else "ongoing"

    # WHERE 절 빌드
    conditions = []
    params = []

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

    # 정렬
    if sort == "deadline":
        order = "CASE WHEN end_date = '' THEN 1 ELSE 0 END, end_date ASC"
    else:
        order = "collected_at DESC"

    # 전체 건수
    cursor.execute(f"SELECT COUNT(*) FROM bid_notices WHERE {where_clause}", params)
    total = cursor.fetchone()[0]

    # 페이지네이션
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
def get_stats():
    """소스별 통계"""
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

    conn.close()
    return {"grand_total": grand_total, "last_collected": last_collected, "by_source": stats}


# ─── 공고 상세 조회 API ──────────────────────────

@app.get("/api/notices/{notice_id}")
def get_notice_detail(notice_id: int):
    """공고 상세 조회 — DB에 확장 필드 없으면 K-Startup API 실시간 조회"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bid_notices WHERE id=?", (notice_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": "공고를 찾을 수 없습니다."}

    notice = dict(row)

    # K-Startup 공고인데 확장 필드가 비어있으면 API에서 실시간 보충
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


# ─── 설정 API ────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    """현재 표시 설정 조회"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM display_settings")
    settings = {row["setting_key"]: {"value": row["setting_value"], "description": row["description"]} for row in cursor.fetchall()}
    conn.close()
    return settings


@app.put("/api/settings/{key}")
def update_setting(key: str, value: str = Query(...)):
    """설정값 변경"""
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
def get_keywords():
    """키워드 목록 조회"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM keywords ORDER BY keyword_group, keyword")
    keywords = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return keywords


@app.put("/api/keywords/{keyword_id}/toggle")
def toggle_keyword(keyword_id: int):
    """키워드 활성/비활성 토글"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE keywords SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?", (keyword_id,))
    conn.commit()
    cursor.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"error": "not found"}


@app.post("/api/keywords")
def add_keyword(keyword: str = Query(...), keyword_group: str = Query(default="사용자 추가")):
    """키워드 추가"""
    conn = get_connection()
    cursor = conn.cursor()
    # 중복 체크
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
def delete_keyword(keyword_id: int):
    """키워드 삭제"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": affected > 0, "deleted_id": keyword_id}


# ─── 기관 관리 API ────────────────────────────────

@app.get("/api/organizations")
def get_organizations():
    """기관 목록 조회"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM organizations ORDER BY category, name")
    orgs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return orgs


# ─── 수집 실행 API ────────────────────────────────

@app.post("/api/collect")
def run_collect():
    """수동으로 전체 수집 실행"""
    results = collect_all()
    return {"results": results}


# ─── 스케줄러 상태 API ────────────────────────────

@app.get("/api/scheduler")
def get_scheduler_status():
    """스케줄러 상태 조회"""
    return {
        "schedule": "매일 09:00, 14:00 자동 수집",
        "status": "running",
    }


# ─── 프론트엔드 정적파일 ──────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    from fastapi.responses import FileResponse

    @app.get("/settings.html")
    def settings_page():
        return FileResponse(os.path.join(frontend_dir, "settings.html"))

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
