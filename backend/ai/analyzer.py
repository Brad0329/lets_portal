"""AI 분석 오케스트레이터 — 첨부 다운로드→파싱→매칭→저장"""

import json
import os
import logging
import requests
from pathlib import Path
from typing import Optional

from .claude_client import ClaudeClient
from .cost import calculate_cost

logger = logging.getLogger(__name__)

# 프롬프트 파일 경로
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """프롬프트 파일 로드"""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {path}")
    return path.read_text(encoding="utf-8")


def _load_ai_config(conn) -> dict:
    """ai_config 테이블에서 설정 로드"""
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM ai_config")
    return {row["key"]: row["value"] for row in cur.fetchall()}


def _load_profile(conn) -> dict:
    """company_profile → dict"""
    cur = conn.cursor()
    cur.execute("SELECT category, field_key, field_label, field_value, field_type FROM company_profile ORDER BY sort_order")
    profile = {}
    for r in cur.fetchall():
        value = r["field_value"] or ""
        if r["field_type"] == "json":
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                value = []
        profile[r["field_key"]] = {"label": r["field_label"], "value": value, "category": r["category"]}
    return profile


def _get_credit_balance(conn) -> float:
    """현재 잔액 조회"""
    cur = conn.cursor()
    cur.execute("SELECT balance FROM ai_credits ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    return row["balance"] if row else 0.0


def _deduct_credit(conn, amount: float, description: str, notice_id: int, analysis_id: int,
                   model: str, input_tokens: int, output_tokens: int) -> float:
    """크레딧 차감 — 새 잔액 반환"""
    balance = _get_credit_balance(conn)
    new_balance = balance - amount
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ai_credits (type, amount, balance, description, notice_id, analysis_id, model_used, tokens_input, tokens_output) "
        "VALUES ('usage', ?, ?, ?, ?, ?, ?, ?, ?)",
        (-amount, new_balance, description, notice_id, analysis_id, model, input_tokens, output_tokens),
    )
    conn.commit()
    return new_balance


PARSEABLE_EXTS = {"pdf", "hwpx", "docx", "hwp"}

# 분석에 유용한 파일명 키워드 (우선 다운로드 대상)
PRIORITY_KEYWORDS = [
    "제안요청", "과업지시", "사업안내", "평가기준", "입찰안내", "제안안내",
    "사업설명", "공고문", "심사기준", "사업계획", "과업내용", "제안서작성",
    "평가배점", "제안평가", "기술평가", "입찰공고",
]


def _is_priority_file(filename: str) -> bool:
    """파일명에 우선 키워드가 포함되어 있는지 확인"""
    name_lower = filename.lower()
    return any(kw in name_lower for kw in PRIORITY_KEYWORDS)


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def _download_file(url: str, filepath: str) -> bool:
    """단일 파일 다운로드 — 성공 시 True"""
    if os.path.exists(filepath):
        return True
    try:
        r = requests.get(url, timeout=30, verify=False)
        if r.status_code == 200 and len(r.content) > 500:
            with open(filepath, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        logger.warning("첨부파일 다운로드 실패: %s — %s", filepath, e)
    return False


def _extract_zip(zip_path: str, extract_dir: str) -> list:
    """ZIP 압축 해제 → 파싱 가능한 파일 경로 리스트"""
    import zipfile
    results = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                # 디렉토리 스킵
                if member.endswith("/"):
                    continue
                ext = member.rsplit(".", 1)[-1].lower() if "." in member else ""
                if ext not in PARSEABLE_EXTS:
                    continue
                # 안전한 파일명으로 추출
                basename = os.path.basename(member)
                safe = _safe_filename(basename)
                out_path = os.path.join(extract_dir, safe)
                if not os.path.exists(out_path):
                    with zf.open(member) as src, open(out_path, "wb") as dst:
                        dst.write(src.read())
                results.append({"filename": basename, "path": out_path, "format": ext})
    except Exception as e:
        logger.warning("ZIP 압축 해제 실패: %s — %s", zip_path, e)
    return results


def _download_attachments(notice_id: int, attachments_json: str, data_dir: str) -> list:
    """첨부파일 다운로드 → 파일 경로 리스트

    전략:
    1. 파일명에 우선 키워드(제안요청서, 과업지시서 등)가 있는 파일만 다운로드
    2. 키워드 매칭 파일이 없으면 전체 다운로드 (폴백)
    3. ZIP 파일은 압축 해제 후 내부 파일에 같은 로직 적용
    """
    att_dir = os.path.join(data_dir, "attachments", str(notice_id))
    os.makedirs(att_dir, exist_ok=True)

    try:
        attachments = json.loads(attachments_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []

    # 파싱 가능 파일 + ZIP 분류
    parseable = []  # (att, ext, is_priority)
    zips = []       # (att,)
    for att in attachments:
        name = att.get("name", "")
        url = att.get("url", "")
        if not name or not url:
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext == "zip":
            zips.append(att)
        elif ext in PARSEABLE_EXTS:
            parseable.append((att, ext, _is_priority_file(name)))

    # 1단계: 우선 키워드 매칭 파일만 다운로드
    priority_files = [(att, ext) for att, ext, pri in parseable if pri]
    downloaded = []

    if priority_files:
        # 키워드 매칭 파일만 다운로드
        for att, ext in priority_files:
            safe = _safe_filename(att["name"])
            filepath = os.path.join(att_dir, safe)
            if _download_file(att["url"], filepath):
                downloaded.append({"filename": att["name"], "path": filepath, "format": ext})
        logger.info("공고 %d: 키워드 매칭 %d개 다운로드 (전체 %d개 중)", notice_id, len(downloaded), len(parseable))
    else:
        # 2단계: 키워드 매칭 없으면 전체 다운로드
        for att, ext, _ in parseable:
            safe = _safe_filename(att["name"])
            filepath = os.path.join(att_dir, safe)
            if _download_file(att["url"], filepath):
                downloaded.append({"filename": att["name"], "path": filepath, "format": ext})
        logger.info("공고 %d: 키워드 매칭 없음 → 전체 %d개 다운로드", notice_id, len(downloaded))

    # 3단계: ZIP 처리 — 다운로드 후 압축 해제, 내부 파일에 같은 키워드 로직
    for att in zips:
        safe = _safe_filename(att["name"])
        zip_path = os.path.join(att_dir, safe)
        if not _download_file(att["url"], zip_path):
            continue

        extracted = _extract_zip(zip_path, att_dir)
        if not extracted:
            continue

        # ZIP 내부에서도 키워드 우선
        zip_priority = [f for f in extracted if _is_priority_file(f["filename"])]
        if zip_priority:
            downloaded.extend(zip_priority)
            logger.info("공고 %d: ZIP '%s' → 키워드 매칭 %d개", notice_id, att["name"], len(zip_priority))
        else:
            # ZIP 내부에 키워드 매칭 없고, 본체에서도 다운로드된 게 없을 때만 전부 추가
            if not downloaded:
                downloaded.extend(extracted)
                logger.info("공고 %d: ZIP '%s' → 전체 %d개 추가", notice_id, att["name"], len(extracted))

    return downloaded


def run_analysis(notice_id: int, conn, data_dir: str = "data") -> dict:
    """AI 분석 전체 파이프라인 실행

    Returns:
        dict with success, analysis_id, match_rate, etc.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.file_parser import extract_text

    cur = conn.cursor()

    # 1. 공고 정보 로드
    cur.execute(
        "SELECT id, title, organization, budget, content, target, attachments, detail_url "
        "FROM bid_notices WHERE id = ?",
        (notice_id,),
    )
    notice = cur.fetchone()
    if not notice:
        return {"success": False, "error": "공고를 찾을 수 없습니다."}

    # 2. 설정 로드
    config = _load_ai_config(conn)
    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"success": False, "error": "API 키가 설정되지 않았습니다. .env에 CLAUDE_API_KEY를 설정하세요."}

    model_parsing = config.get("model_parsing", "claude-haiku-4-5-20251001")
    model_matching = config.get("model_matching", "claude-sonnet-4-20250514")
    exchange_rate = float(config.get("exchange_rate", "1400"))

    # 3. 잔액 확인
    balance = _get_credit_balance(conn)
    if balance < 50:  # 최소 예상 비용
        return {
            "success": False,
            "error": "credit_insufficient",
            "message": f"잔액이 부족합니다. (잔액: {balance:.0f}원, 예상 비용: ~100원)",
            "credit_balance": balance,
        }

    # 4. 프로필 로드
    profile = _load_profile(conn)
    if not any(f["value"] for f in profile.values() if isinstance(f["value"], str) and f["value"]):
        # 프로필 비어있어도 파싱은 진행, 매칭만 제한
        pass

    # 5. 첨부파일 다운로드 + 파싱
    attachments = _download_attachments(notice_id, notice["attachments"], data_dir)
    parsed_files = []
    all_text = ""
    pdf_bytes = None

    for att in attachments:
        result = extract_text(att["path"])
        parsed_files.append({
            "filename": att["filename"],
            "format": att["format"],
            "parsed": result.success,
            "error": result.error if not result.success else "",
        })
        if result.success:
            all_text += f"\n\n=== {att['filename']} ===\n{result.text}"
            if att["format"] == "pdf" and result.raw_bytes and pdf_bytes is None:
                pdf_bytes = result.raw_bytes

    # 6. 분석 차수 결정
    cur.execute("SELECT MAX(analysis_seq) as max_seq FROM ai_analyses WHERE notice_id = ?", (notice_id,))
    row = cur.fetchone()
    analysis_seq = (row["max_seq"] or 0) + 1

    # 7. 분석 모드 결정
    has_attachments = bool(all_text.strip())

    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0

    if has_attachments:
        # === 일반 모드: 파싱 + 매칭 ===

        # 7-1. 문서 파싱 (Haiku)
        parse_prompt = _load_prompt("parse_document")
        parsing_client = ClaudeClient(api_key, model_parsing)

        if pdf_bytes and len(pdf_bytes) < 30_000_000:  # 30MB 이하 PDF 직접 전달
            parse_response = parsing_client.analyze_document_pdf(pdf_bytes, parse_prompt)
        else:
            parse_response = parsing_client.analyze_document(all_text, parse_prompt)

        if not parse_response.success:
            return {"success": False, "error": f"문서 파싱 실패: {parse_response.error}"}

        total_input_tokens += parse_response.input_tokens
        total_output_tokens += parse_response.output_tokens
        parse_cost = calculate_cost(model_parsing, parse_response.input_tokens, parse_response.output_tokens, exchange_rate=exchange_rate)
        total_cost += parse_cost

        # 파싱 결과 JSON 추출
        parsed_json = _extract_json(parse_response.content)
        criteria = parsed_json.get("evaluation_criteria", [])
        requirements = parsed_json.get("requirements", [])
        parsed_summary = parsed_json.get("business_summary", {}).get("purpose", "")

        # 7-2. 매칭 분석 (Sonnet)
        match_prompt = _load_prompt("match_profile")
        matching_client = ClaudeClient(api_key, model_matching)
        match_response = matching_client.match_profile(
            {"evaluation_criteria": criteria, "requirements": requirements},
            _profile_to_flat(profile),
            match_prompt,
        )

        if not match_response.success:
            # 파싱은 성공했으나 매칭 실패 — 파싱 결과만 저장
            cur.execute(
                "INSERT INTO ai_analyses (notice_id, analysis_seq, mode, parsed_criteria, parsed_requirements, parsed_summary, "
                "model_parsing, cost_krw, tokens_total, profile_snapshot) "
                "VALUES (?, ?, 'full', ?, ?, ?, ?, ?, ?, ?)",
                (notice_id, analysis_seq,
                 json.dumps(criteria, ensure_ascii=False),
                 json.dumps(requirements, ensure_ascii=False),
                 parsed_summary, model_parsing, total_cost,
                 total_input_tokens + total_output_tokens,
                 json.dumps(_profile_to_flat(profile), ensure_ascii=False)),
            )
            conn.commit()
            return {"success": False, "error": f"매칭 분석 실패: {match_response.error}"}

        total_input_tokens += match_response.input_tokens
        total_output_tokens += match_response.output_tokens
        match_cost = calculate_cost(model_matching, match_response.input_tokens, match_response.output_tokens, exchange_rate=exchange_rate)
        total_cost += match_cost

        match_json = _extract_json(match_response.content)
        match_rate = match_json.get("match_rate", 0)
        recommendation = match_json.get("recommendation", "")
        summary = match_json.get("summary", "")

        # 8. DB 저장
        cur.execute(
            "INSERT INTO ai_analyses (notice_id, analysis_seq, mode, "
            "parsed_criteria, parsed_requirements, parsed_summary, "
            "total_score, total_max_score, match_rate, match_detail, match_recommendation, "
            "model_parsing, model_matching, cost_krw, tokens_total, profile_snapshot) "
            "VALUES (?, ?, 'full', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (notice_id, analysis_seq,
             json.dumps(criteria, ensure_ascii=False),
             json.dumps(requirements, ensure_ascii=False),
             parsed_summary,
             match_json.get("total_expected_score", 0),
             match_json.get("total_max_score", 0),
             match_rate,
             json.dumps(match_json.get("items", []), ensure_ascii=False),
             recommendation,
             model_parsing, model_matching,
             total_cost, total_input_tokens + total_output_tokens,
             json.dumps(_profile_to_flat(profile), ensure_ascii=False)),
        )
        conn.commit()
        analysis_id = cur.lastrowid

        # bid_notices 업데이트
        cur.execute(
            "UPDATE bid_notices SET ai_status='done', ai_match_rate=?, ai_recommendation=? WHERE id=?",
            (match_rate, recommendation, notice_id),
        )
        conn.commit()

        # 크레딧 차감
        new_balance = _deduct_credit(
            conn, total_cost,
            f"AI분석: {notice['title'][:30]} (파싱+매칭)",
            notice_id, analysis_id,
            f"{model_parsing}+{model_matching}",
            total_input_tokens, total_output_tokens,
        )

        return {
            "success": True,
            "mode": "full",
            "analysis_id": analysis_id,
            "analysis_seq": analysis_seq,
            "notice_id": notice_id,
            "match_rate": match_rate,
            "recommendation": recommendation,
            "summary": summary,
            "items": match_json.get("items", []),
            "cost_krw": total_cost,
            "credit_balance": new_balance,
            "parsed_files": parsed_files,
        }

    else:
        # === 간이 모드: 첨부 없이 DB 정보만으로 판단 ===
        simple_prompt = _load_prompt("match_simple")
        simple_prompt = simple_prompt.replace("{title}", notice["title"] or "")
        simple_prompt = simple_prompt.replace("{organization}", notice["organization"] or "")
        simple_prompt = simple_prompt.replace("{budget}", notice["budget"] or "정보 없음")
        simple_prompt = simple_prompt.replace("{content}", (notice["content"] or "")[:2000])
        simple_prompt = simple_prompt.replace("{requirements}", notice["target"] or "정보 없음")
        simple_prompt = simple_prompt.replace("{profile_json}", json.dumps(_profile_to_flat(profile), ensure_ascii=False, indent=2))

        matching_client = ClaudeClient(api_key, model_matching)
        response = matching_client.analyze_document(simple_prompt, "")

        if not response.success:
            return {"success": False, "error": f"간이 분석 실패: {response.error}"}

        total_input_tokens = response.input_tokens
        total_output_tokens = response.output_tokens
        total_cost = calculate_cost(model_matching, total_input_tokens, total_output_tokens, exchange_rate=exchange_rate)

        simple_json = _extract_json(response.content)
        grade = simple_json.get("grade", "중")
        reason = simple_json.get("reason", "")
        recommendation = simple_json.get("recommendation", "")

        # DB 저장
        cur.execute(
            "INSERT INTO ai_analyses (notice_id, analysis_seq, mode, "
            "simple_grade, simple_reason, match_recommendation, "
            "model_matching, cost_krw, tokens_total, profile_snapshot) "
            "VALUES (?, ?, 'simple', ?, ?, ?, ?, ?, ?, ?)",
            (notice_id, analysis_seq,
             grade, reason, recommendation,
             model_matching, total_cost,
             total_input_tokens + total_output_tokens,
             json.dumps(_profile_to_flat(profile), ensure_ascii=False)),
        )
        conn.commit()
        analysis_id = cur.lastrowid

        # bid_notices 업데이트
        cur.execute(
            "UPDATE bid_notices SET ai_status='done', ai_recommendation=? WHERE id=?",
            (recommendation, notice_id),
        )
        conn.commit()

        # 크레딧 차감
        new_balance = _deduct_credit(
            conn, total_cost,
            f"AI분석(간이): {notice['title'][:30]}",
            notice_id, analysis_id,
            model_matching,
            total_input_tokens, total_output_tokens,
        )

        return {
            "success": True,
            "mode": "simple",
            "analysis_id": analysis_id,
            "analysis_seq": analysis_seq,
            "notice_id": notice_id,
            "grade": grade,
            "reason": reason,
            "strengths": simple_json.get("strengths", []),
            "weaknesses": simple_json.get("weaknesses", []),
            "recommendation": recommendation,
            "cost_krw": total_cost,
            "credit_balance": new_balance,
        }


def _extract_json(text: str) -> dict:
    """AI 응답에서 JSON 추출 — ```json 블록 또는 전체 파싱 시도"""
    import re
    # ```json ... ``` 블록 추출
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 전체 텍스트를 JSON으로 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # { } 범위 추출 시도
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("JSON 추출 실패: %s", text[:200])
    return {}


def _profile_to_flat(profile: dict) -> dict:
    """프로필 dict → 평탄화 (AI에 전달용)"""
    flat = {}
    for key, info in profile.items():
        flat[info["label"]] = info["value"]
    return flat
