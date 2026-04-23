"""
Phase D-2 실행 CLI — 목차 탐지 + 본문 매칭 프로토타입을 10건에 돌린다.

사용법:
    python tools/run_toc.py                      # 전체 10건
    python tools/run_toc.py --id 5               # 경과원 ESG만
    python tools/run_toc.py --dump               # data/diag_d2/ 에 파일별 JSON 덤프

전제:
    D-1 덤프가 있어야 함: python tools/check_parser.py --dump
    (이미 data/diag_d1/*.txt 에 있으면 재파싱 없이 재사용)

출력:
    파일별 요약 + 전체 집계표 (콘솔 깨짐 방지 위해 ASCII 위주)
    `--dump` 시 data/diag_d2/{stem}.json 생성 (엔트리+매칭결과 전체)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from extractors.segmenter.toc_detector import detect_toc  # noqa: E402
from extractors.segmenter.body_matcher import match_entries_to_body  # noqa: E402


DIAG1 = _ROOT / "data" / "diag_d1"
DIAG2 = _ROOT / "data" / "diag_d2"
SUMMARY1 = DIAG1 / "_summary.json"


def run_one(rec: dict) -> dict:
    """단일 파일에 D-2 파이프라인 실행 → 결과 dict."""
    out: dict = {
        "id": rec.get("id", 0),
        "file": rec["file"],
        "stem": Path(rec["file"]).stem.replace(" ", "_")[:80],
        "ext": rec.get("ext", ""),
        "d1_section_count": rec.get("section_count", 0),
        "d1_silent_fail": rec.get("silent_fail", False),
    }

    if not rec.get("parse_success"):
        out.update({"status": "parse_fail", "reason": "D-1에서 파싱 실패"})
        return out

    stem = out["stem"]
    txt_path = DIAG1 / f"{stem}.txt"
    if not txt_path.exists():
        out.update({"status": "no_dump", "reason": f"덤프 없음: {txt_path.name}"})
        return out

    text = txt_path.read_text(encoding="utf-8")

    t0 = time.monotonic()
    toc = detect_toc(text)
    t_toc_ms = int((time.monotonic() - t0) * 1000)

    if not toc.found:
        out.update({
            "status": "toc_not_found",
            "reason": toc.reason,
            "toc_ms": t_toc_ms,
        })
        return out

    t1 = time.monotonic()
    mr = match_entries_to_body(text, toc.entries, body_start_line=toc.body_start_line)
    t_match_ms = int((time.monotonic() - t1) * 1000)

    out.update({
        "status": "ok",
        "toc_ms": t_toc_ms,
        "match_ms": t_match_ms,
        "toc_anchor_line": toc.anchor_line,
        "toc_body_start_line": toc.body_start_line,
        "toc_entries": len(toc.entries),
        "toc_by_level": toc.summary().get("by_level", {}),
        "match_total": mr.total_entries,
        "match_hits": mr.match_count,
        "match_rate": round(mr.match_rate, 3),
        "match_by_mode": mr.summary()["by_mode"],
        "entries": [
            {
                "marker": e.marker, "title": e.title,
                "page": e.page, "level": e.level,
                "position": e.toc_position,
            }
            for e in toc.entries
        ],
        "sections": [
            {
                "name": s.name, "level": s.level,
                "start": s.start_line, "end": s.end_line,
                "mode": s.matched_mode,
            }
            for s in mr.sections
        ],
    })
    return out


def print_report(items: list) -> None:
    print("\n" + "=" * 78)
    print(f"D-2 results: {len(items)} files")
    print("=" * 78)
    print(f"{'#':>2} {'ext':<5} {'D1sec':>5} {'TocE':>5} {'Hit':>5} {'Rate':>5}  {'Modes':<30} status")
    print("-" * 78)

    status_count = {}
    total_entries = 0
    total_hits = 0

    for it in items:
        s = it.get("status", "unknown")
        status_count[s] = status_count.get(s, 0) + 1
        if s == "ok":
            total_entries += it["match_total"]
            total_hits += it["match_hits"]

        if s == "ok":
            modes = it.get("match_by_mode", {})
            mode_str = " ".join(f"{k[:3]}={v}" for k, v in sorted(modes.items()))
            print(
                f"{it['id']:>2} {it['ext']:<5} "
                f"{it['d1_section_count']:>5} "
                f"{it['toc_entries']:>5} "
                f"{it['match_hits']:>5} "
                f"{it['match_rate']*100:>4.0f}%  "
                f"{mode_str:<30} ok"
            )
        else:
            reason = it.get("reason", "")[:30]
            print(
                f"{it['id']:>2} {it['ext']:<5} "
                f"{it.get('d1_section_count', 0):>5} "
                f"{'-':>5} {'-':>5} {'-':>5}  "
                f"{'':<30} {s} ({reason})"
            )

    print("-" * 78)
    rate = (total_hits / total_entries * 100) if total_entries else 0.0
    print(
        f"total entries: {total_entries}, "
        f"total hits: {total_hits} ({rate:.1f}%), "
        f"statuses: {status_count}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase D-2 TOC detection runner")
    ap.add_argument("--id", type=int, default=None, help="단일 파일 id (0~9)")
    ap.add_argument("--dump", action="store_true",
                    help="data/diag_d2/ 에 파일별 JSON + _summary.json 저장")
    args = ap.parse_args()

    if not SUMMARY1.exists():
        print(f"[에러] {SUMMARY1} 없음. 먼저 실행:\n  python tools/check_parser.py --dump",
              file=sys.stderr)
        return 1

    d1_records = json.loads(SUMMARY1.read_text(encoding="utf-8"))
    # id 주입
    for i, r in enumerate(d1_records):
        r["id"] = i

    if args.id is not None:
        if args.id < 0 or args.id >= len(d1_records):
            print(f"[에러] id {args.id} 범위 밖", file=sys.stderr)
            return 1
        records = [d1_records[args.id]]
    else:
        records = d1_records

    items = [run_one(r) for r in records]

    print_report(items)

    if args.dump:
        DIAG2.mkdir(parents=True, exist_ok=True)
        for it in items:
            stem = it.get("stem") or f"id_{it['id']}"
            (DIAG2 / f"{stem}.json").write_text(
                json.dumps(it, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        (DIAG2 / "_summary.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n덤프: {DIAG2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
