"""Phase C-5: 마스터 프로필 추출기 API.

제안서 업로드 → 백그라운드 claim 추출 → 검토·편집 UI 지원.
MVP 엔드포인트 set:
    POST   /api/ai/extractor/upload                 제안서 업로드 + 메타
    GET    /api/ai/extractor/sources                업로드 목록
    GET    /api/ai/extractor/sources/{src_id}       상태 조회 (폴링)
    DELETE /api/ai/extractor/sources/{src_id}       삭제 (관련 claim/hint 포함)
    GET    /api/ai/extractor/claims                 claim 목록 (필터)
    PATCH  /api/ai/extractor/claims/{claim_id}      편집/승인/거부
    POST   /api/ai/extractor/claims/bulk-verify     일괄 승인/거부
    POST   /api/ai/extractor/claims/merge           병합
    GET    /api/ai/extractor/claims/merge-suggestions  fuzzy 병합 후보
    GET    /api/ai/extractor/quantitative-hints
    PATCH  /api/ai/extractor/quantitative-hints/{id}
"""

import json
import os
import shutil
import threading
import logging
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException

from database import get_connection
from auth import require_login

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/extractor", tags=["ai-extractor"])

_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
_ASSETS_DIR = _DATA_ROOT / "proposals_assets"

_VALID_CATEGORIES = ("Identity", "Methodology", "USP", "Philosophy", "Story", "Operational")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _json_load(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _claim_row_to_dict(r):
    return {
        "claim_id": r["claim_id"],
        "proposal_source_id": r["proposal_source_id"],
        "category": r["category"],
        "statement": r["user_edited_statement"] or r["statement"],
        "statement_original": r["statement"],
        "tags": _json_load(r["tags"]) or {"domain": [], "audience": [], "method": []},
        "proposal_sections": _json_load(r["proposal_sections"]) or [],
        "length_variants": _json_load(r["length_variants"]) or {},
        "evidence_refs": _json_load(r["evidence_refs"]) or [],
        "source_section": r["source_section"],
        "source_page": r["source_page"],
        "recurrence": r["recurrence"],
        "confidence": r["confidence"],
        "user_verified": r["user_verified"],
        "merged_from": _json_load(r["merged_from"]) or [],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _source_row_to_dict(r):
    return {
        "id": r["id"],
        "src_id": r["src_id"],
        "file_name": r["file_name"],
        "proposal_title": r["proposal_title"],
        "organization": r["organization"],
        "year": r["year"],
        "awarded": r["awarded"],
        "status": r["status"],
        "progress": r["progress"],
        "total_sections": r["total_sections"],
        "processed_sections": r["processed_sections"],
        "current_section": r["current_section"],
        "cost_krw": r["cost_krw"],
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "model": r["model"],
        "error_message": r["error_message"],
        "uploaded_at": r["uploaded_at"],
        "completed_at": r["completed_at"],
    }


# ---------------------------------------------------------------------------
# 백그라운드 추출 — 별도 스레드에서 실행
# ---------------------------------------------------------------------------

def _run_extraction_bg(src_db_id: int):
    """별도 스레드에서 proposal_sources 한 건 추출.

    진행률은 DB 직접 UPDATE — UI는 /sources/{src_id} 폴링으로 상태 읽음.
    """
    from extractors import ProposalAssetExtractor, ExtractionConfig
    from extractors.base import SourceMeta
    from ai.claude_client import ClaudeClient

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM proposal_sources WHERE id=?", (src_db_id,))
        src_row = cur.fetchone()
        if not src_row:
            logger.error("proposal_source %d not found", src_db_id)
            return

        api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            cur.execute(
                "UPDATE proposal_sources SET status='failed', error_message=? WHERE id=?",
                ("CLAUDE_API_KEY 미설정 (.env 확인 필요)", src_db_id),
            )
            conn.commit()
            return

        cur.execute("SELECT value FROM ai_config WHERE key='model_matching'")
        row = cur.fetchone()
        model = (row["value"] if row else None) or "claude-sonnet-4-20250514"

        client = ClaudeClient(api_key, model=model)
        config = ExtractionConfig(primary_model=model)
        ex = ProposalAssetExtractor(client, config)

        meta = SourceMeta(
            path=src_row["file_path"],
            year=src_row["year"],
            awarded=(bool(src_row["awarded"]) if src_row["awarded"] is not None else None),
            proposal_title=src_row["proposal_title"],
            organization=src_row["organization"],
            src_id=src_row["src_id"],
        )

        cur.execute(
            "UPDATE proposal_sources SET status='processing', model=? WHERE id=?",
            (model, src_db_id),
        )
        conn.commit()

        def on_progress(payload):
            stage = payload.get("stage")
            try:
                if stage == "segment":
                    total = int(payload.get("target_sections", 0) or 0)
                    cur.execute(
                        "UPDATE proposal_sources SET total_sections=?, current_section=? WHERE id=?",
                        (total, "섹션 분할 완료", src_db_id),
                    )
                    conn.commit()
                elif stage == "extract_section":
                    idx = int(payload.get("index", 0) or 0)
                    total = int(payload.get("total", 0) or 0)
                    section = payload.get("section") or ""
                    progress = (idx - 1) / total if total else 0.0
                    cur.execute(
                        "UPDATE proposal_sources SET processed_sections=?, current_section=?, progress=? WHERE id=?",
                        (idx - 1, section, progress, src_db_id),
                    )
                    conn.commit()
            except Exception:
                logger.exception("progress update 실패")

        result = ex.extract([meta], progress_cb=on_progress)

        # claims INSERT (claim_id UNIQUE — 충돌 시 recurrence 증가)
        for c in result.claims:
            cur.execute("SELECT claim_id, recurrence FROM claims WHERE claim_id=?", (c.id,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE claims SET recurrence=?, updated_at=datetime('now','localtime') WHERE claim_id=?",
                    ((existing["recurrence"] or 1) + 1, c.id),
                )
                continue
            cur.execute(
                """
                INSERT INTO claims (
                    claim_id, proposal_source_id, category, statement, tags,
                    proposal_sections, length_variants, evidence_refs,
                    source_section, source_start_line,
                    recurrence, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c.id,
                    src_db_id,
                    c.category,
                    c.statement,
                    json.dumps(c.tags, ensure_ascii=False),
                    json.dumps(c.proposal_sections, ensure_ascii=False),
                    json.dumps(c.length_variants, ensure_ascii=False),
                    json.dumps(c.evidence_refs, ensure_ascii=False),
                    c.source.get("section"),
                    c.source.get("section_start_line"),
                    c.recurrence,
                    c.confidence,
                ),
            )

        # quantitative_hints INSERT
        for h in result.quantitative_hints:
            cur.execute(
                """
                INSERT INTO proposal_quantitative_hints (
                    proposal_source_id, type, name, year, organization, section, extractor
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src_db_id,
                    h.get("type"),
                    (h.get("name") or "")[:500],
                    h.get("year"),
                    h.get("org") or h.get("organization"),
                    h.get("section"),
                    h.get("extractor", "llm"),
                ),
            )

        cur.execute(
            """
            UPDATE proposal_sources
               SET status='completed',
                   progress=1.0,
                   processed_sections=total_sections,
                   current_section=NULL,
                   cost_krw=?,
                   input_tokens=?,
                   output_tokens=?,
                   completed_at=datetime('now','localtime')
             WHERE id=?
            """,
            (
                result.total_cost_krw,
                result.total_input_tokens,
                result.total_output_tokens,
                src_db_id,
            ),
        )
        conn.commit()
        logger.info(
            "추출 완료 src_id=%s claims=%d hints=%d cost=%.1f원 "
            "tokens in=%d out=%d cache_write=%d cache_read=%d",
            src_row["src_id"],
            len(result.claims),
            len(result.quantitative_hints),
            result.total_cost_krw,
            result.total_input_tokens,
            result.total_output_tokens,
            result.total_cache_creation_tokens,
            result.total_cache_read_tokens,
        )
    except Exception as e:
        logger.exception("추출 실패 src_db_id=%d", src_db_id)
        try:
            cur.execute(
                "UPDATE proposal_sources SET status='failed', error_message=? WHERE id=?",
                (str(e)[:500], src_db_id),
            )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 소스 (제안서) 엔드포인트
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_proposal(
    request: Request,
    file: UploadFile = File(...),
    year: int = Form(...),
    awarded: bool = Form(...),
    organization: str = Form(...),
    proposal_title: str = Form(""),
):
    """제안서 업로드 + 메타 입력 → 백그라운드 추출 시작."""
    user = require_login(request)

    filename = file.filename or "upload"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("pdf", "hwp", "hwpx", "docx"):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식: .{ext}")

    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cur = conn.cursor()
    # 임시 레코드 INSERT → id로 src_id 생성
    cur.execute(
        """
        INSERT INTO proposal_sources (
            src_id, file_path, file_name, proposal_title, organization, year, awarded,
            status, uploaded_by
        ) VALUES (?, '', ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            f"__pending_{os.getpid()}__",
            filename,
            proposal_title or None,
            organization,
            year,
            1 if awarded else 0,
            user["id"],
        ),
    )
    src_db_id = cur.lastrowid
    src_id = f"src_{src_db_id:04d}"

    # 파일 저장
    src_dir = _ASSETS_DIR / src_id
    src_dir.mkdir(parents=True, exist_ok=True)
    safe_name = filename.replace("/", "_").replace("\\", "_")
    file_path = src_dir / safe_name
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        file.file.close()

    cur.execute(
        "UPDATE proposal_sources SET src_id=?, file_path=? WHERE id=?",
        (src_id, str(file_path), src_db_id),
    )
    conn.commit()
    conn.close()

    t = threading.Thread(target=_run_extraction_bg, args=(src_db_id,), daemon=True)
    t.start()

    return {"success": True, "id": src_db_id, "src_id": src_id}


@router.get("/sources")
def list_sources(request: Request):
    """업로드된 제안서 목록 (claim_count 포함)."""
    require_login(request)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ps.*,
               (SELECT COUNT(*) FROM claims WHERE proposal_source_id=ps.id) AS claim_count
        FROM proposal_sources ps
        ORDER BY ps.id DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return {
        "sources": [
            {**_source_row_to_dict(r), "claim_count": r["claim_count"]}
            for r in rows
        ]
    }


@router.get("/sources/{src_id}")
def get_source(request: Request, src_id: str):
    """단일 제안서 상태 조회 — 폴링 용."""
    require_login(request)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM proposal_sources WHERE src_id=?", (src_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="제안서를 찾을 수 없습니다.")
    cur.execute("SELECT COUNT(*) as c FROM claims WHERE proposal_source_id=?", (row["id"],))
    cnt = cur.fetchone()["c"]
    conn.close()
    d = _source_row_to_dict(row)
    d["claim_count"] = cnt
    return d


@router.delete("/sources/{src_id}")
def delete_source(request: Request, src_id: str):
    """제안서 + 관련 claim/hint + 업로드 파일 삭제."""
    require_login(request)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, file_path FROM proposal_sources WHERE src_id=?", (src_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="제안서를 찾을 수 없습니다.")
    pid = row["id"]
    cur.execute("DELETE FROM claims WHERE proposal_source_id=?", (pid,))
    cur.execute("DELETE FROM proposal_quantitative_hints WHERE proposal_source_id=?", (pid,))
    cur.execute("DELETE FROM proposal_sources WHERE id=?", (pid,))
    conn.commit()
    conn.close()

    src_dir = _ASSETS_DIR / src_id
    file_cleanup_ok = True
    if src_dir.exists():
        try:
            shutil.rmtree(src_dir)
        except Exception as e:
            # Windows 파일 잠금 등으로 실패하면 응답에 담아 UI가 재시도 안내 가능
            logger.warning("디렉토리 삭제 실패 src_dir=%s err=%r", src_dir, e)
            file_cleanup_ok = False

    return {"success": True, "file_cleanup_ok": file_cleanup_ok}


def cleanup_orphan_assets() -> int:
    """DB에 없는 proposals_assets/src_* 디렉토리를 제거. 반환: 삭제된 디렉토리 수."""
    if not _ASSETS_DIR.exists():
        return 0
    try:
        conn = get_connection()
        cur = conn.cursor()
        known = {r["src_id"] for r in cur.execute("SELECT src_id FROM proposal_sources")}
        conn.close()
    except Exception as e:
        logger.warning("orphan 정리: DB 조회 실패 err=%r", e)
        return 0

    removed = 0
    for entry in _ASSETS_DIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in known:
            continue
        try:
            shutil.rmtree(entry)
            removed += 1
            logger.info("orphan 디렉토리 제거: %s", entry)
        except Exception as e:
            logger.warning("orphan 디렉토리 제거 실패 path=%s err=%r", entry, e)
    return removed


# ---------------------------------------------------------------------------
# Claims 엔드포인트
# ---------------------------------------------------------------------------

@router.get("/claims")
def list_claims(
    request: Request,
    category: Optional[str] = None,
    verified: Optional[int] = None,
    source_id: Optional[int] = None,
):
    """claim 목록 — category/verified/source_id 필터 조합."""
    require_login(request)

    conditions = []
    params: list = []
    if category:
        if category not in _VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"유효하지 않은 카테고리: {category}")
        conditions.append("category = ?")
        params.append(category)
    if verified is not None:
        conditions.append("user_verified = ?")
        params.append(int(verified))
    if source_id is not None:
        conditions.append("proposal_source_id = ?")
        params.append(int(source_id))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM claims {where} ORDER BY category, confidence DESC, id ASC",
        params,
    )
    claims = [_claim_row_to_dict(r) for r in cur.fetchall()]

    # 카테고리별 카운트 (전체 — 필터 무관)
    cur.execute(
        """
        SELECT category,
               COUNT(*) AS total,
               SUM(CASE WHEN user_verified=0 THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN user_verified=1 THEN 1 ELSE 0 END) AS approved,
               SUM(CASE WHEN user_verified=2 THEN 1 ELSE 0 END) AS hidden
        FROM claims GROUP BY category
        """
    )
    counts = {r["category"]: dict(r) for r in cur.fetchall()}
    conn.close()

    return {"claims": claims, "counts": counts}


@router.patch("/claims/{claim_id}")
def update_claim(request: Request, claim_id: str, body: dict):
    """claim 편집 — statement/user_verified/tags 부분 수정."""
    require_login(request)

    fields: list = []
    params: list = []
    if "statement" in body:
        fields.append("user_edited_statement = ?")
        params.append(body["statement"])
    if "user_verified" in body:
        v = int(body["user_verified"])
        if v not in (0, 1, 2):
            raise HTTPException(status_code=400, detail="user_verified는 0/1/2")
        fields.append("user_verified = ?")
        params.append(v)
    if "tags" in body:
        fields.append("tags = ?")
        params.append(json.dumps(body["tags"], ensure_ascii=False))
    if "proposal_sections" in body:
        fields.append("proposal_sections = ?")
        params.append(json.dumps(body["proposal_sections"], ensure_ascii=False))

    if not fields:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    fields.append("updated_at = datetime('now','localtime')")
    params.append(claim_id)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE claims SET {', '.join(fields)} WHERE claim_id = ?", params)
    affected = cur.rowcount
    conn.commit()
    conn.close()

    if not affected:
        raise HTTPException(status_code=404, detail="claim을 찾을 수 없습니다.")
    return {"success": True, "updated": affected}


@router.post("/claims/bulk-verify")
def bulk_verify(request: Request, body: dict):
    """일괄 승인/거부.

    body 형식:
        {"claim_ids": [...], "user_verified": 1}
        혹은 {"filter": {"min_confidence": 0.9, "category": "USP"}, "user_verified": 1}
    """
    require_login(request)

    verified = int(body.get("user_verified", 1))
    if verified not in (0, 1, 2):
        raise HTTPException(status_code=400, detail="user_verified는 0/1/2")

    claim_ids = body.get("claim_ids") or []
    filt = body.get("filter") or {}

    conn = get_connection()
    cur = conn.cursor()

    if claim_ids:
        placeholders = ",".join("?" * len(claim_ids))
        cur.execute(
            f"UPDATE claims SET user_verified=?, updated_at=datetime('now','localtime') "
            f"WHERE claim_id IN ({placeholders})",
            [verified, *claim_ids],
        )
    elif filt:
        conditions = ["user_verified = 0"]
        params: list = []
        if "min_confidence" in filt:
            conditions.append("confidence >= ?")
            params.append(float(filt["min_confidence"]))
        if "category" in filt:
            if filt["category"] not in _VALID_CATEGORIES:
                raise HTTPException(status_code=400, detail="잘못된 카테고리")
            conditions.append("category = ?")
            params.append(filt["category"])
        if "source_id" in filt:
            conditions.append("proposal_source_id = ?")
            params.append(int(filt["source_id"]))
        where_clause = " AND ".join(conditions)
        cur.execute(
            f"UPDATE claims SET user_verified=?, updated_at=datetime('now','localtime') "
            f"WHERE {where_clause}",
            [verified, *params],
        )
    else:
        raise HTTPException(status_code=400, detail="claim_ids 또는 filter 필수")

    affected = cur.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "updated": affected}


@router.post("/claims/merge")
def merge_claims(request: Request, body: dict):
    """여러 claim을 primary로 병합.

    body: {primary_id: "cl_xxx", merge_ids: ["cl_yyy", ...], final_statement?: str}
    병합 대상은 user_verified=2(숨김)으로 표시, primary는 merged_from/recurrence 누적.
    """
    require_login(request)

    primary_id = body.get("primary_id")
    merge_ids = body.get("merge_ids") or []
    if not primary_id or not merge_ids:
        raise HTTPException(status_code=400, detail="primary_id, merge_ids 필수")
    if primary_id in merge_ids:
        raise HTTPException(status_code=400, detail="primary_id가 merge_ids에 포함됨")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM claims WHERE claim_id=?", (primary_id,))
    primary = cur.fetchone()
    if not primary:
        conn.close()
        raise HTTPException(status_code=404, detail="primary claim을 찾을 수 없습니다.")

    placeholders = ",".join("?" * len(merge_ids))
    cur.execute(f"SELECT * FROM claims WHERE claim_id IN ({placeholders})", merge_ids)
    merges = cur.fetchall()

    primary_tags = _json_load(primary["tags"]) or {"domain": [], "audience": [], "method": []}
    for k in ("domain", "audience", "method"):
        primary_tags.setdefault(k, [])
    primary_sections = _json_load(primary["proposal_sections"]) or []
    primary_variants = _json_load(primary["length_variants"]) or {}
    primary_evidence = _json_load(primary["evidence_refs"]) or []
    primary_merged = _json_load(primary["merged_from"]) or []
    recurrence_sum = primary["recurrence"] or 1

    for m in merges:
        mtags = _json_load(m["tags"]) or {}
        for k in ("domain", "audience", "method"):
            merged_vals = primary_tags.get(k, []) + (mtags.get(k) or [])
            primary_tags[k] = list(dict.fromkeys(merged_vals))
        primary_sections = list(
            dict.fromkeys(primary_sections + (_json_load(m["proposal_sections"]) or []))
        )
        primary_evidence = list(
            dict.fromkeys(primary_evidence + (_json_load(m["evidence_refs"]) or []))
        )
        for lk, lv in (_json_load(m["length_variants"]) or {}).items():
            if lk not in primary_variants and lv:
                primary_variants[lk] = lv
        if m["claim_id"] not in primary_merged:
            primary_merged.append(m["claim_id"])
        recurrence_sum += (m["recurrence"] or 1)

    final_stmt = (
        body.get("final_statement")
        or primary["user_edited_statement"]
        or primary["statement"]
    )

    cur.execute(
        """
        UPDATE claims SET
            user_edited_statement=?,
            tags=?, proposal_sections=?, length_variants=?, evidence_refs=?,
            merged_from=?, recurrence=?, user_verified=1,
            updated_at=datetime('now','localtime')
        WHERE claim_id=?
        """,
        (
            final_stmt,
            json.dumps(primary_tags, ensure_ascii=False),
            json.dumps(primary_sections, ensure_ascii=False),
            json.dumps(primary_variants, ensure_ascii=False),
            json.dumps(primary_evidence, ensure_ascii=False),
            json.dumps(primary_merged, ensure_ascii=False),
            recurrence_sum,
            primary_id,
        ),
    )

    cur.execute(
        f"UPDATE claims SET user_verified=2, updated_at=datetime('now','localtime') "
        f"WHERE claim_id IN ({placeholders})",
        merge_ids,
    )

    conn.commit()
    conn.close()
    return {
        "success": True,
        "merged_count": len(merges),
        "recurrence": recurrence_sum,
        "final_statement": final_stmt,
    }


@router.get("/claims/merge-suggestions")
def merge_suggestions(
    request: Request,
    threshold: float = 0.85,
    category: Optional[str] = None,
    limit: int = 50,
):
    """fuzzy similarity로 병합 후보 쌍을 제안 (미검토 claim 대상)."""
    require_login(request)

    params: list = []
    where = "WHERE user_verified = 0"
    if category:
        if category not in _VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail="잘못된 카테고리")
        where += " AND category = ?"
        params.append(category)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT claim_id, category, statement, user_edited_statement, confidence FROM claims {where}",
        params,
    )
    rows = cur.fetchall()
    conn.close()

    by_cat: dict = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    suggestions: list = []
    for cat, items in by_cat.items():
        n = len(items)
        for i in range(n):
            a = items[i]
            a_stmt = a["user_edited_statement"] or a["statement"]
            for j in range(i + 1, n):
                b = items[j]
                b_stmt = b["user_edited_statement"] or b["statement"]
                sim = SequenceMatcher(None, a_stmt, b_stmt).ratio()
                if sim >= threshold:
                    suggestions.append({
                        "category": cat,
                        "similarity": round(sim, 3),
                        "claim_a": {
                            "claim_id": a["claim_id"],
                            "statement": a_stmt,
                            "confidence": a["confidence"],
                        },
                        "claim_b": {
                            "claim_id": b["claim_id"],
                            "statement": b_stmt,
                            "confidence": b["confidence"],
                        },
                    })

    suggestions.sort(key=lambda x: x["similarity"], reverse=True)
    return {"suggestions": suggestions[:limit], "threshold": threshold}


# ---------------------------------------------------------------------------
# 정량 힌트
# ---------------------------------------------------------------------------

@router.get("/quantitative-hints")
def list_hints(request: Request, source_id: Optional[int] = None):
    """정량 후보 목록 — 사용자가 company_profile로 수동 편입."""
    require_login(request)
    conn = get_connection()
    cur = conn.cursor()
    if source_id is not None:
        cur.execute(
            "SELECT * FROM proposal_quantitative_hints WHERE proposal_source_id=? ORDER BY id",
            (source_id,),
        )
    else:
        cur.execute("SELECT * FROM proposal_quantitative_hints ORDER BY id DESC")
    hints = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"hints": hints}


@router.patch("/quantitative-hints/{hint_id}")
def update_hint(request: Request, hint_id: int, body: dict):
    """정량 힌트 상태 변경 — imported/dismissed/pending."""
    require_login(request)
    action = body.get("user_action")
    if action not in ("pending", "imported", "dismissed"):
        raise HTTPException(status_code=400, detail="user_action는 pending/imported/dismissed")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE proposal_quantitative_hints SET user_action=? WHERE id=?",
        (action, hint_id),
    )
    affected = cur.rowcount
    conn.commit()
    conn.close()
    if not affected:
        raise HTTPException(status_code=404, detail="힌트를 찾을 수 없습니다.")
    return {"success": True}


# ---------------------------------------------------------------------------
# C-5-B: 회사 프로필 자동 채우기
# ---------------------------------------------------------------------------

import re as _re

# 힌트 type → company_profile.field_key 매핑
_HINT_TO_PROJECT_HISTORY = {"실적"}
_HINT_TO_PATENTS_CERTS = {"인증", "등록", "인증/등록", "자격", "특허"}

_SUSPICIOUS_PATTERNS = [
    _re.compile(r"등록\s*여부"),
    _re.compile(r"등록증\s*번호"),
    _re.compile(r"가능\s*여부"),
    _re.compile(r"사업자\s*등록(?!증)"),
]


def _norm_text(s: str) -> str:
    """중복 감지용 정규화 — 공백·구두점 제거, 소문자."""
    if not s:
        return ""
    s = _re.sub(r"[\s,\.·\-\_\(\)\[\]]+", "", s)
    return s.lower()


def _is_suspicious(text: str) -> bool:
    """오탐 의심 패턴 — 기본 해제 대상."""
    if not text or len(text.strip()) < 6:
        return True
    for pat in _SUSPICIOUS_PATTERNS:
        if pat.search(text):
            return True
    return False


def _is_duplicate_project(new_name: str, existing: list) -> bool:
    """project_history JSON 배열에서 name 중복 감지."""
    new_key = _norm_text(new_name)
    if not new_key:
        return False
    for ex in existing or []:
        if not isinstance(ex, dict):
            continue
        ex_key = _norm_text(ex.get("name", ""))
        if not ex_key:
            continue
        if new_key == ex_key:
            return True
        if len(new_key) >= 6 and len(ex_key) >= 6:
            if new_key in ex_key or ex_key in new_key:
                return True
    return False


def _is_duplicate_cert(new_line: str, existing_text: str, threshold: float = 0.85) -> bool:
    """patents_certs textarea에서 줄 단위 fuzzy 중복 감지."""
    new_key = _norm_text(new_line)
    if not new_key or not existing_text:
        return False
    for line in existing_text.split("\n"):
        ex_key = _norm_text(line)
        if not ex_key:
            continue
        if new_key == ex_key:
            return True
        if SequenceMatcher(None, new_key, ex_key).ratio() >= threshold:
            return True
    return False


def _load_profile_map(conn) -> dict:
    """company_profile을 {field_key: (field_value, field_type)} dict로 로드."""
    cur = conn.cursor()
    cur.execute("SELECT field_key, field_value, field_type FROM company_profile")
    return {r["field_key"]: (r["field_value"] or "", r["field_type"]) for r in cur.fetchall()}


def _hint_to_project_item(h: dict) -> dict:
    """실적 힌트 → project_history 배열 아이템."""
    return {
        "name": (h.get("name") or "").strip(),
        "client": (h.get("organization") or "").strip(),
        "amount": "",
        "period": str(h.get("year") or ""),
        "role": "",
    }


@router.get("/preview/{src_id}")
def preview_autofill(request: Request, src_id: str):
    """C-5-B: 업로드된 제안서의 정량 힌트·claim 요약 — 미리보기 모달용.

    힌트를 매핑 규칙대로 분류하고, 기존 company_profile과 중복·오탐 감지 결과를 함께 반환.
    """
    require_login(request)
    conn = get_connection()
    cur = conn.cursor()

    # 소스 확인
    cur.execute("SELECT * FROM proposal_sources WHERE src_id=?", (src_id,))
    src_row = cur.fetchone()
    if not src_row:
        conn.close()
        raise HTTPException(status_code=404, detail="제안서를 찾을 수 없습니다.")
    if src_row["status"] != "completed":
        conn.close()
        raise HTTPException(status_code=400, detail=f"추출이 완료되지 않았습니다 (현재 상태: {src_row['status']}).")
    pid = src_row["id"]

    # 기존 프로필 조회 — 중복 감지 기준
    profile = _load_profile_map(conn)
    existing_projects = []
    try:
        existing_projects = json.loads(profile.get("project_history", ("[]", ""))[0] or "[]")
    except (json.JSONDecodeError, TypeError):
        existing_projects = []
    existing_certs = profile.get("patents_certs", ("", ""))[0] or ""

    # 힌트 로드 (아직 imported 되지 않은 것만)
    cur.execute(
        "SELECT * FROM proposal_quantitative_hints WHERE proposal_source_id=? AND user_action != 'imported' ORDER BY id",
        (pid,),
    )
    hint_rows = [dict(r) for r in cur.fetchall()]

    project_candidates = []
    cert_candidates = []
    ignored = []

    for h in hint_rows:
        htype = h.get("type") or ""
        name = (h.get("name") or "").strip()
        suspicious = _is_suspicious(name)
        if htype in _HINT_TO_PROJECT_HISTORY:
            project_candidates.append({
                "hint_id": h["id"],
                "type": htype,
                "name": name,
                "client": (h.get("organization") or "").strip(),
                "period": str(h.get("year") or ""),
                "section": h.get("section") or "",
                "is_duplicate": _is_duplicate_project(name, existing_projects),
                "is_suspicious": suspicious,
            })
        elif htype in _HINT_TO_PATENTS_CERTS:
            cert_candidates.append({
                "hint_id": h["id"],
                "type": htype,
                "text": name,
                "year": h.get("year"),
                "section": h.get("section") or "",
                "is_duplicate": _is_duplicate_cert(name, existing_certs),
                "is_suspicious": suspicious,
            })
        else:
            ignored.append({
                "hint_id": h["id"],
                "type": htype,
                "name": name,
                "reason": "현재 프로필 스키마에 매핑 규칙 없음",
            })

    # Claim 로드 — by category
    cur.execute(
        "SELECT * FROM claims WHERE proposal_source_id=? ORDER BY category, confidence DESC",
        (pid,),
    )
    claim_rows = [dict(r) for r in cur.fetchall()]
    by_category: dict = {}
    counts: dict = {}
    for c in claim_rows:
        cat = c.get("category") or "Other"
        # JSON 필드 파싱
        for k in ("tags", "proposal_sections", "length_variants", "evidence_refs", "merged_from"):
            v = c.get(k)
            if isinstance(v, str) and v:
                try:
                    c[k] = json.loads(v)
                except json.JSONDecodeError:
                    pass
        by_category.setdefault(cat, []).append(c)
        counts[cat] = counts.get(cat, 0) + 1
    conn.close()

    return {
        "source": {
            "src_id": src_row["src_id"],
            "file_name": src_row["file_name"],
            "organization": src_row["organization"],
            "year": src_row["year"],
            "awarded": bool(src_row["awarded"]) if src_row["awarded"] is not None else None,
            "claim_count": len(claim_rows),
            "hint_count": len(hint_rows),
        },
        "quantitative": {
            "project_history": project_candidates,
            "patents_certs": cert_candidates,
            "ignored": ignored,
        },
        "claims": {
            "by_category": by_category,
            "counts": counts,
        },
    }


@router.post("/apply-to-profile")
def apply_to_profile(request: Request, body: dict):
    """C-5-B: 선택된 힌트·claim을 company_profile에 병합 + claim 일괄 승인.

    body = {
        "source_id": str,             # src_id
        "hint_ids": [int, ...],       # 반영할 힌트 ID
        "claim_ids": [str, ...],      # 승인 처리할 claim_id
        "merge_mode": "fill_empty" | "append_only"   # overwrite는 MVP 제외
    }
    """
    require_login(request)
    src_id = body.get("source_id")
    hint_ids = list(body.get("hint_ids") or [])
    claim_ids = list(body.get("claim_ids") or [])
    merge_mode = body.get("merge_mode") or "fill_empty"
    if merge_mode not in ("fill_empty", "append_only"):
        raise HTTPException(status_code=400, detail="merge_mode는 fill_empty 또는 append_only")
    if not src_id:
        raise HTTPException(status_code=400, detail="source_id 필수")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM proposal_sources WHERE src_id=?", (src_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="제안서를 찾을 수 없습니다.")
    pid = row["id"]

    # 선택된 힌트 로드
    hints: list = []
    if hint_ids:
        placeholders = ",".join("?" * len(hint_ids))
        cur.execute(
            f"SELECT * FROM proposal_quantitative_hints WHERE id IN ({placeholders}) AND proposal_source_id=?",
            (*hint_ids, pid),
        )
        hints = [dict(r) for r in cur.fetchall()]

    # 기존 프로필 로드
    profile = _load_profile_map(conn)
    existing_projects = []
    try:
        existing_projects = json.loads(profile.get("project_history", ("[]", ""))[0] or "[]")
    except (json.JSONDecodeError, TypeError):
        existing_projects = []
    existing_certs = profile.get("patents_certs", ("", ""))[0] or ""

    # 힌트 분류 + 병합
    projects_added = 0
    projects_skipped = 0
    cert_lines_added = 0
    cert_lines_skipped = 0
    new_projects = list(existing_projects)
    new_cert_lines: list = []

    for h in hints:
        htype = h.get("type") or ""
        name = (h.get("name") or "").strip()
        if not name:
            continue
        if htype in _HINT_TO_PROJECT_HISTORY:
            if _is_duplicate_project(name, new_projects):
                projects_skipped += 1
                continue
            new_projects.append(_hint_to_project_item(h))
            projects_added += 1
        elif htype in _HINT_TO_PATENTS_CERTS:
            year = h.get("year")
            line = f"{name} ({year})" if year else name
            if _is_duplicate_cert(line, existing_certs) or _is_duplicate_cert(
                line, "\n".join(new_cert_lines)
            ):
                cert_lines_skipped += 1
                continue
            new_cert_lines.append(line)
            cert_lines_added += 1
        # 매핑 없는 type은 silently skip

    # project_history 저장
    if projects_added > 0:
        cur.execute(
            "UPDATE company_profile SET field_value=?, updated_at=datetime('now','localtime') WHERE field_key='project_history'",
            (json.dumps(new_projects, ensure_ascii=False),),
        )

    # patents_certs 저장 — merge_mode 적용
    if cert_lines_added > 0:
        if merge_mode == "fill_empty" and not existing_certs.strip():
            new_certs_value = "\n".join(new_cert_lines)
        else:
            # append_only 또는 기존 값이 있을 때: 기존 + 줄바꿈 + 신규
            sep = "\n" if existing_certs and not existing_certs.endswith("\n") else ""
            new_certs_value = existing_certs + sep + "\n".join(new_cert_lines)
        cur.execute(
            "UPDATE company_profile SET field_value=?, updated_at=datetime('now','localtime') WHERE field_key='patents_certs'",
            (new_certs_value,),
        )

    # 힌트 상태 imported
    hints_marked = 0
    if hint_ids:
        placeholders = ",".join("?" * len(hint_ids))
        cur.execute(
            f"UPDATE proposal_quantitative_hints SET user_action='imported' WHERE id IN ({placeholders}) AND proposal_source_id=?",
            (*hint_ids, pid),
        )
        hints_marked = cur.rowcount

    # claim 일괄 승인
    claims_approved = 0
    if claim_ids:
        placeholders = ",".join("?" * len(claim_ids))
        cur.execute(
            f"UPDATE claims SET user_verified=1, updated_at=datetime('now','localtime') WHERE claim_id IN ({placeholders}) AND proposal_source_id=?",
            (*claim_ids, pid),
        )
        claims_approved = cur.rowcount

    conn.commit()
    conn.close()

    return {
        "success": True,
        "profile_updates": {
            "project_history": {"added": projects_added, "skipped_duplicates": projects_skipped},
            "patents_certs": {"lines_added": cert_lines_added, "skipped_duplicates": cert_lines_skipped},
        },
        "claims_approved": claims_approved,
        "hints_marked_imported": hints_marked,
    }
