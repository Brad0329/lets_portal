"""AI 관련 API 라우터 — 프로필, 분석, 크레딧"""

import json
import threading
from fastapi import APIRouter, Request, HTTPException
from database import get_connection
from auth import require_login

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ---------------------------------------------------------------------------
# 회사 프로필 API
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(request: Request):
    """회사 프로필 조회 — 카테고리별 그룹핑"""
    require_login(request)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT category, field_key, field_label, field_value, field_type, sort_order, updated_at "
        "FROM company_profile ORDER BY sort_order"
    )
    rows = cur.fetchall()
    conn.close()

    categories = {}
    for r in rows:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "key": r["field_key"],
            "label": r["field_label"],
            "value": r["field_value"],
            "type": r["field_type"],
        })

    return {
        "categories": [
            {"category": cat, "fields": fields}
            for cat, fields in categories.items()
        ]
    }


@router.put("/profile")
def update_profile(request: Request, body: dict):
    """회사 프로필 수정 — fields: [{key, value}, ...]"""
    require_login(request)

    fields = body.get("fields", [])
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")

    conn = get_connection()
    cur = conn.cursor()
    updated = 0
    for f in fields:
        key = f.get("key")
        value = f.get("value", "")
        if not key:
            continue
        cur.execute(
            "UPDATE company_profile SET field_value = ?, updated_at = datetime('now','localtime') WHERE field_key = ?",
            (value, key),
        )
        updated += cur.rowcount

    conn.commit()
    conn.close()

    return {"success": True, "updated_count": updated}


# ---------------------------------------------------------------------------
# AI 분석 API
# ---------------------------------------------------------------------------

@router.post("/analyze/{notice_id}")
def analyze_notice(request: Request, notice_id: int):
    """AI 분석 실행 (동기) — 첨부 다운로드→파싱→매칭→저장"""
    require_login(request)

    # 진행 상태 설정
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE bid_notices SET ai_status='analyzing' WHERE id=?", (notice_id,))
    conn.commit()

    try:
        from ai.analyzer import run_analysis
        import os
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        result = run_analysis(notice_id, conn, data_dir)
    except Exception as e:
        cur.execute("UPDATE bid_notices SET ai_status='failed' WHERE id=?", (notice_id,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    if not result.get("success"):
        return result  # error 포함하여 반환

    return result


@router.get("/analyses/{notice_id}")
def get_analyses(request: Request, notice_id: int):
    """공고의 분석 결과 목록 (전체 차수)"""
    require_login(request)

    conn = get_connection()
    cur = conn.cursor()

    # 공고 제목
    cur.execute("SELECT title FROM bid_notices WHERE id=?", (notice_id,))
    notice = cur.fetchone()
    if not notice:
        conn.close()
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")

    cur.execute(
        "SELECT id, analysis_seq, mode, "
        "parsed_criteria, parsed_requirements, parsed_summary, "
        "total_score, total_max_score, match_rate, match_detail, match_recommendation, "
        "simple_grade, simple_reason, "
        "profile_snapshot, profile_changes, "
        "model_parsing, model_matching, cost_krw, tokens_total, created_at "
        "FROM ai_analyses WHERE notice_id=? ORDER BY analysis_seq",
        (notice_id,),
    )
    rows = cur.fetchall()
    conn.close()

    analyses = []
    for r in rows:
        item = {
            "analysis_id": r["id"],
            "analysis_seq": r["analysis_seq"],
            "mode": r["mode"],
            "match_rate": r["match_rate"],
            "recommendation": r["match_recommendation"],
            "cost_krw": r["cost_krw"],
            "created_at": r["created_at"],
        }
        if r["mode"] == "full":
            item["parsed_summary"] = r["parsed_summary"]
            item["total_score"] = r["total_score"]
            item["total_max_score"] = r["total_max_score"]
            try:
                item["items"] = json.loads(r["match_detail"] or "[]")
            except (json.JSONDecodeError, TypeError):
                item["items"] = []
            try:
                item["parsed_criteria"] = json.loads(r["parsed_criteria"] or "[]")
            except (json.JSONDecodeError, TypeError):
                item["parsed_criteria"] = []
        else:
            item["grade"] = r["simple_grade"]
            item["reason"] = r["simple_reason"]

        if r["profile_changes"]:
            try:
                item["profile_changes"] = json.loads(r["profile_changes"])
            except (json.JSONDecodeError, TypeError):
                item["profile_changes"] = None

        analyses.append(item)

    return {
        "notice_id": notice_id,
        "notice_title": notice["title"],
        "analyses": analyses,
    }


# ---------------------------------------------------------------------------
# 크레딧 API
# ---------------------------------------------------------------------------

@router.get("/credits")
def get_credits(request: Request):
    """잔액 + 사용이력"""
    require_login(request)

    conn = get_connection()
    cur = conn.cursor()

    # 잔액
    cur.execute("SELECT balance FROM ai_credits ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    balance = row["balance"] if row else 0.0

    # 이번 달 사용
    cur.execute(
        "SELECT COALESCE(SUM(ABS(amount)), 0) as total, COUNT(*) as cnt "
        "FROM ai_credits WHERE type='usage' AND created_at >= date('now','start of month','localtime')"
    )
    monthly = cur.fetchone()

    # 최근 이력
    cur.execute(
        "SELECT id, type, amount, balance, description, notice_id, model_used, "
        "tokens_input, tokens_output, created_at "
        "FROM ai_credits ORDER BY id DESC LIMIT 50"
    )
    history = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "balance": balance,
        "monthly_usage": monthly["total"],
        "monthly_count": monthly["cnt"],
        "history": history,
    }


@router.post("/credits/charge")
def charge_credits(request: Request, body: dict):
    """크레딧 충전 (관리자)"""
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자만 충전 가능합니다.")

    amount = body.get("amount", 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="충전 금액은 양수여야 합니다.")

    description = body.get("description", "관리자 충전")

    conn = get_connection()
    cur = conn.cursor()

    # 현재 잔액
    cur.execute("SELECT balance FROM ai_credits ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    current = row["balance"] if row else 0.0
    new_balance = current + amount

    cur.execute(
        "INSERT INTO ai_credits (type, amount, balance, description) VALUES ('charge', ?, ?, ?)",
        (amount, new_balance, description),
    )
    conn.commit()
    conn.close()

    return {"success": True, "charged": amount, "balance": new_balance}


# ---------------------------------------------------------------------------
# AI 설정 API
# ---------------------------------------------------------------------------

@router.get("/config")
def get_ai_config(request: Request):
    """AI 설정 조회"""
    require_login(request)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT key, value, description FROM ai_config")
    config = {r["key"]: {"value": r["value"], "description": r["description"]} for r in cur.fetchall()}
    conn.close()
    return config


@router.put("/config")
def update_ai_config(request: Request, body: dict):
    """AI 설정 변경"""
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="관리자만 변경 가능합니다.")

    conn = get_connection()
    cur = conn.cursor()
    updated = 0
    for key, value in body.items():
        cur.execute(
            "UPDATE ai_config SET value=?, updated_at=datetime('now','localtime') WHERE key=?",
            (str(value), key),
        )
        updated += cur.rowcount

    conn.commit()
    conn.close()
    return {"success": True, "updated_count": updated}
