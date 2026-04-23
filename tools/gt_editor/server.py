"""
Ground Truth Editor — Phase D-2 용 로컬 웹 도구.

목적:
    샘플 10건에 대한 expected sections(ground truth) 를 사람이 보정 후 저장.
    D-5 regression 테스트가 이 파일들을 기준으로 섹션 일치율을 측정.

전제:
    D-1 덤프가 있어야 함. 먼저 실행:
        python tools/check_parser.py --dump

실행:
    python tools/gt_editor/server.py
    → http://127.0.0.1:8088

저장 위치:
    data/ground_truth/{파일명_stem}.json

JSON 포맷 (설계 design_phase_d_parser.md §6):
    {
      "file": "제안서_혁신창업스쿨.hwp",
      "expected_sections": [
        {"name": "Ⅰ.제안개요", "level": 1, "skip": true, "start_line": 19},
        ...
      ],
      "expected_claim_range": [15, 40],
      "notes": ""
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles


_ROOT = Path(__file__).resolve().parent.parent.parent
DIAG_DIR = _ROOT / "data" / "diag_d1"
DIAG2_DIR = _ROOT / "data" / "diag_d2"
GT_DIR = _ROOT / "data" / "ground_truth"
SUMMARY = DIAG_DIR / "_summary.json"
STATIC_DIR = Path(__file__).resolve().parent

# D-2 모듈 import — backend/ 경로 추가
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
try:
    from extractors.segmenter.toc_detector import detect_toc  # noqa: E402
    from extractors.segmenter.body_matcher import match_entries_to_body  # noqa: E402
    _HAS_D2 = True
except ImportError as _e:
    _HAS_D2 = False
    _D2_IMPORT_ERROR = str(_e)

app = FastAPI(title="GT Editor", docs_url=None, redoc_url=None)


def _stem_for(rec: dict) -> str:
    """check_parser.py 가 덤프에 쓰는 것과 같은 규칙 — 일치해야 함."""
    return Path(rec["file"]).stem.replace(" ", "_")[:80]


def _load_summary() -> list[dict]:
    if not SUMMARY.exists():
        raise HTTPException(
            503,
            f"진단 요약 파일이 없습니다: {SUMMARY}. "
            "먼저 `python tools/check_parser.py --dump` 실행이 필요합니다.",
        )
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def _index() -> list[dict]:
    """파일 목록 + GT 존재 여부."""
    data = _load_summary()
    out = []
    for i, rec in enumerate(data):
        stem = _stem_for(rec)
        gt_path = GT_DIR / f"{stem}.json"
        out.append({
            "id": i,
            "file": rec["file"],
            "stem": stem,
            "ext": rec.get("ext", ""),
            "parse_success": rec.get("parse_success", False),
            "text_len": rec.get("text_len", 0),
            "line_count": rec.get("line_count", 0),
            "section_count": rec.get("section_count", 0),
            "silent_fail": rec.get("silent_fail", False),
            "gt_exists": gt_path.exists(),
        })
    return out


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/files")
def list_files():
    return _index()


@app.get("/api/files/{fid}/text")
def get_text(fid: int):
    idx = _index()
    if fid < 0 or fid >= len(idx):
        raise HTTPException(404, "잘못된 파일 id")
    if not idx[fid]["parse_success"]:
        return {"text": "", "parse_success": False}
    txt = DIAG_DIR / f"{idx[fid]['stem']}.txt"
    if not txt.exists():
        raise HTTPException(404, f"텍스트 덤프 없음: {txt.name}")
    return {"text": txt.read_text(encoding="utf-8"), "parse_success": True}


@app.get("/api/files/{fid}/auto-sections")
def get_auto_sections(fid: int):
    """현 파서가 뽑은 섹션 (`_summary.json` 의 sections 필드)."""
    data = _load_summary()
    if fid < 0 or fid >= len(data):
        raise HTTPException(404)
    return data[fid].get("sections", [])


@app.get("/api/files/{fid}/toc-sections")
def get_toc_sections(fid: int):
    """D-2 목차 탐지 프로토타입 결과를 GT 초안 형식으로 반환.

    매칭 실패한 엔트리(`missed`)는 start_line=0 으로 반환 — 사용자가 본문 클릭으로 채움.
    skip 은 모두 False (사용자가 수동 결정).
    """
    if not _HAS_D2:
        raise HTTPException(500, f"D-2 모듈 import 실패: {_D2_IMPORT_ERROR}")

    idx = _index()
    if fid < 0 or fid >= len(idx):
        raise HTTPException(404)

    rec = idx[fid]
    if not rec["parse_success"]:
        raise HTTPException(400, "파싱 실패 파일은 목차 탐지 불가 (PPTX 등)")

    txt_path = DIAG_DIR / f"{rec['stem']}.txt"
    if not txt_path.exists():
        raise HTTPException(404, f"텍스트 덤프 없음: {txt_path.name}")

    text = txt_path.read_text(encoding="utf-8")
    toc = detect_toc(text)
    if not toc.found:
        return {
            "ok": False,
            "reason": toc.reason,
            "sections": [],
            "summary": toc.summary(),
        }

    mr = match_entries_to_body(text, toc.entries, body_start_line=toc.body_start_line)
    sections = []
    for s in mr.sections:
        sections.append({
            "name": s.name,
            "level": s.level,
            "start_line": max(s.start_line, 0),  # -1 → 0 (사용자가 보정)
            "skip": False,
            "_mode": s.matched_mode,  # 참고용 (GT 저장엔 제외)
        })

    return {
        "ok": True,
        "sections": sections,
        "summary": {
            **toc.summary(),
            "match_rate": round(mr.match_rate, 3),
            "match_by_mode": mr.summary()["by_mode"],
            "anchor_line": toc.anchor_line,
        },
    }


@app.get("/api/files/{fid}/gt")
def get_gt(fid: int):
    idx = _index()
    if fid < 0 or fid >= len(idx):
        raise HTTPException(404)
    stem = idx[fid]["stem"]
    gt_path = GT_DIR / f"{stem}.json"
    if not gt_path.exists():
        return {
            "file": idx[fid]["file"],
            "expected_sections": [],
            "expected_claim_range": [10, 40],
            "notes": "",
        }
    return json.loads(gt_path.read_text(encoding="utf-8"))


@app.post("/api/files/{fid}/gt")
def save_gt(fid: int, payload: dict = Body(...)):
    idx = _index()
    if fid < 0 or fid >= len(idx):
        raise HTTPException(404)
    stem = idx[fid]["stem"]
    GT_DIR.mkdir(parents=True, exist_ok=True)

    # 정상화 + 파일명 강제
    sections = payload.get("expected_sections") or []
    norm_sections = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        if not name:
            continue
        norm_sections.append({
            "name": name,
            "level": int(s.get("level") or 2),
            "start_line": int(s.get("start_line") or 0),
            "skip": bool(s.get("skip") or False),
        })

    claim_min = payload.get("expected_claim_range", [10, 40])[0]
    claim_max = payload.get("expected_claim_range", [10, 40])[1]

    body = {
        "file": idx[fid]["file"],
        "expected_sections": norm_sections,
        "expected_claim_range": [int(claim_min or 10), int(claim_max or 40)],
        "notes": payload.get("notes") or "",
    }

    gt_path = GT_DIR / f"{stem}.json"
    gt_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved_path": str(gt_path), "sections": len(norm_sections)}


@app.delete("/api/files/{fid}/gt")
def delete_gt(fid: int):
    idx = _index()
    if fid < 0 or fid >= len(idx):
        raise HTTPException(404)
    gt_path = GT_DIR / f"{idx[fid]['stem']}.json"
    if gt_path.exists():
        gt_path.unlink()
        return {"deleted": True}
    return {"deleted": False}


# ---------------------------------------------------------------------------
# 정적 HTML
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("uvicorn 이 설치돼 있지 않습니다. pip install uvicorn", file=sys.stderr)
        sys.exit(1)
    port = 8088
    print(f"GT Editor: http://127.0.0.1:{port}")
    print(f"  진단 덤프: {DIAG_DIR}")
    print(f"  GT 저장:   {GT_DIR}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
