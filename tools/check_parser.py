"""
Phase D-1 현황 진단 도구 — 현 파서 동작 시각화.

목적:
    - 제안서 샘플에 file_parser.extract_text() + proposal._segment_text() 를 돌려
      섹션 분할이 얼마나 잘 되는지 진단.
    - 섹션 0개로 "조용한 실패" 발생하는 케이스를 찾는다.
    - 목차 앵커("목차/차례/CONTENTS") + 마커 패턴(Ⅰ./1.) 힌트를 수집해
      D-2(목차 탐지) / D-3(Haiku 분할) 설계에 쓴다.

사용법:
    python tools/check_parser.py                    # data/proposal_sample/ 전체
    python tools/check_parser.py path/to/file.hwp   # 단일 파일
    python tools/check_parser.py path/to/dir        # 해당 디렉토리 전체
    python tools/check_parser.py --dump             # 텍스트/JSON을 data/diag_d1/ 에 덤프

출력:
    콘솔:  파일별 요약 + 전체 집계 테이블
    파일:  data/diag_d1/{파일명}.txt    (파싱된 마크다운 텍스트)
           data/diag_d1/{파일명}.json   (섹션·메타 JSON)
           data/diag_d1/_summary.json  (전체 집계)

주의:
    이 도구는 읽기 전용 진단기. DB에 아무것도 쓰지 않는다.
    LLM 호출 없음 (Python 규칙 기반 섹션 분할만 확인).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

# backend/ 를 sys.path에 추가 (utils.file_parser, extractors.proposal 쓰기 위해)
_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from utils.file_parser import extract_text, ParseResult  # noqa: E402
from extractors.proposal import _segment_text  # noqa: E402
from extractors.base import ExtractionConfig  # noqa: E402


# ---------------------------------------------------------------------------
# 앵커/마커 탐지 (D-2 설계용 힌트 수집 — 실제 목차 로직은 아니다)
# ---------------------------------------------------------------------------

_TOC_ANCHOR_RE = re.compile(
    r"^\s*(목\s*차|차\s*례|CONTENTS|Contents|Index|목\s*록)\s*$"
)

_ROMAN_TOP_RE = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\.\s*(.+)$")
_NUM_DOT_RE = re.compile(r"^(\d{1,2})\.\s+(.+)$")           # "1. 제안개요"
_NUM_SPACE_KR_RE = re.compile(r"^([1-9])\s+([가-힣].+)$")   # "1 사업의 필요성" (현 파서 MID)
_NUM_NESTED_RE = re.compile(r"^(\d+)\.(\d+)\s+(.+)$")       # "1.1 xxx"
_CH_HEADING_RE = re.compile(r"^제\s*\d+\s*(장|절|조)\s+(.+)$")  # "제1장 xxx"
_HASH_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")          # "## xxx" (마크다운)

# "... 3" 같이 목차 줄에 붙어 있는 페이지 번호 꼬리
_TOC_PAGE_TAIL_RE = re.compile(r"[\.\s·]+\s*\d{1,3}\s*$")


def _scan_toc_anchor(lines: list[str], head: int = 200) -> Optional[int]:
    """첫 head 줄 안에서 목차 앵커 라인 번호 반환 (없으면 None)."""
    for i, ln in enumerate(lines[:head]):
        if _TOC_ANCHOR_RE.match(ln.strip()):
            return i
    return None


def _sample_toc_entries(lines: list[str], anchor_idx: int, look: int = 80) -> list[str]:
    """앵커 아래 look 줄 중 '목차 항목처럼 보이는' 라인만 수확."""
    out = []
    blank_streak = 0
    for ln in lines[anchor_idx + 1 : anchor_idx + 1 + look]:
        s = ln.strip()
        if not s:
            blank_streak += 1
            if blank_streak >= 3:
                break
            continue
        blank_streak = 0
        # 목차 항목으로 간주하는 조건: 페이지 번호 꼬리 or 로마자/숫자 마커 시작
        if (
            _TOC_PAGE_TAIL_RE.search(s)
            or _ROMAN_TOP_RE.match(s)
            or _NUM_DOT_RE.match(s)
            or _NUM_SPACE_KR_RE.match(s)
            or _CH_HEADING_RE.match(s)
        ):
            out.append(s[:80])
    return out


def _marker_histogram(lines: list[str]) -> dict:
    """전체 텍스트에서 어떤 마커 패턴이 얼마나 나오는지 집계."""
    hist = {
        "roman_top": 0,      # Ⅰ. Ⅱ.
        "num_dot": 0,        # 1. 2.
        "num_space_kr": 0,   # 1 사업의... (현 파서 MID)
        "num_nested": 0,     # 1.1
        "ch_heading": 0,     # 제1장/절/조
        "hash_heading": 0,   # ## (mdnorm)
        "bullet_pipe": 0,    # | (표)
    }
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("|"):
            hist["bullet_pipe"] += 1
            continue
        if _ROMAN_TOP_RE.match(s):
            hist["roman_top"] += 1
        elif _NUM_NESTED_RE.match(s):
            hist["num_nested"] += 1
        elif _NUM_DOT_RE.match(s):
            hist["num_dot"] += 1
        elif _NUM_SPACE_KR_RE.match(s):
            hist["num_space_kr"] += 1
        elif _CH_HEADING_RE.match(s):
            hist["ch_heading"] += 1
        elif _HASH_HEADING_RE.match(s):
            hist["hash_heading"] += 1
    return hist


# ---------------------------------------------------------------------------
# 진단 실행
# ---------------------------------------------------------------------------

def diagnose(path: Path, dump_dir: Optional[Path] = None) -> dict:
    """파일 하나 진단 → 결과 딕셔너리."""
    info: dict = {
        "file": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "ext": path.suffix.lower().lstrip("."),
    }

    t0 = time.monotonic()
    result: ParseResult = extract_text(str(path))
    info["parse_ms"] = int((time.monotonic() - t0) * 1000)
    info["parse_success"] = result.success
    info["parse_error"] = result.error
    info["format"] = result.format
    info["page_count"] = result.page_count
    info["text_len"] = len(result.text or "")

    if not result.success or not result.text:
        info.update({
            "section_count": 0,
            "toc_anchor": None,
            "toc_sample": [],
            "marker_hist": {},
            "silent_fail": False,  # 파싱 자체가 실패라 별도 분류
        })
        return info

    lines = result.text.split("\n")
    info["line_count"] = len(lines)

    # 목차 앵커
    anchor = _scan_toc_anchor(lines, head=min(400, len(lines)))
    info["toc_anchor"] = anchor
    info["toc_anchor_line"] = lines[anchor].strip() if anchor is not None else None
    info["toc_sample"] = _sample_toc_entries(lines, anchor) if anchor is not None else []

    # 마커 히스토그램
    info["marker_hist"] = _marker_histogram(lines)

    # 현 파서로 섹션 분할
    t0 = time.monotonic()
    sections = _segment_text(result.text)
    info["segment_ms"] = int((time.monotonic() - t0) * 1000)
    info["section_count"] = len(sections)
    info["sections"] = [
        {
            "name": s.name,
            "level": s.level,
            "start": s.start_line,
            "end": s.end_line,
            "text_len": len(s.text or ""),
        }
        for s in sections
    ]

    # 스킵 섹션 수 (현 skip_section_keywords 기준)
    cfg = ExtractionConfig()
    skipped = [s for s in sections if any(kw in s.name for kw in cfg.skip_section_keywords)]
    info["skipped_count"] = len(skipped)
    info["target_count"] = len(sections) - len(skipped)

    # 조용한 실패 = 파싱은 됐는데 섹션 0개
    info["silent_fail"] = (info["section_count"] == 0)

    # 텍스트·JSON 덤프
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        stem = path.stem.replace(" ", "_")[:80]
        (dump_dir / f"{stem}.txt").write_text(result.text, encoding="utf-8")
        (dump_dir / f"{stem}.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return info


# ---------------------------------------------------------------------------
# 리포트 포매팅
# ---------------------------------------------------------------------------

def _fmt_size(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f}KB"
    return f"{n}B"


def print_file_report(info: dict) -> None:
    print(f"\n== {info['file']}")
    print(
        f"   fmt={info['ext']}  size={_fmt_size(info['size_bytes'])}  "
        f"parse={info['parse_ms']}ms {'OK' if info['parse_success'] else 'FAIL'}  "
        f"text={info.get('text_len', 0):,}자  lines={info.get('line_count', 0):,}"
    )

    if not info["parse_success"]:
        print(f"   [파싱 실패] {info.get('parse_error', '')}")
        return

    # 목차
    if info["toc_anchor"] is not None:
        print(
            f"   목차앵커: line {info['toc_anchor']}: "
            f"{info['toc_anchor_line']!r}  (수확 {len(info['toc_sample'])}개)"
        )
        for t in info["toc_sample"][:8]:
            print(f"     · {t}")
        if len(info["toc_sample"]) > 8:
            print(f"     ... +{len(info['toc_sample']) - 8}")
    else:
        print("   목차앵커: 없음")

    # 마커
    mh = info["marker_hist"]
    print(
        "   마커 히스토그램: "
        f"roman_top={mh.get('roman_top', 0)}  "
        f"num_dot={mh.get('num_dot', 0)}  "
        f"num_space_kr={mh.get('num_space_kr', 0)}  "
        f"num_nested={mh.get('num_nested', 0)}  "
        f"ch_heading={mh.get('ch_heading', 0)}  "
        f"hash={mh.get('hash_heading', 0)}  "
        f"pipe_tbl={mh.get('bullet_pipe', 0)}"
    )

    # 현 파서 섹션
    tag = "  [조용한 실패]" if info["silent_fail"] else ""
    print(
        f"   현 파서 섹션: {info['section_count']}개  "
        f"(스킵 {info.get('skipped_count', 0)}, 타겟 {info.get('target_count', 0)}, "
        f"{info.get('segment_ms', 0)}ms){tag}"
    )
    for s in info.get("sections", [])[:10]:
        print(f"     - [L{s['level']}] {s['name']}  (lines {s['start']}-{s['end']}, {s['text_len']}자)")
    if info["section_count"] > 10:
        print(f"     ... +{info['section_count'] - 10}")


def print_summary(infos: list[dict]) -> None:
    n = len(infos)
    if n == 0:
        print("\n[요약] 진단한 파일 없음")
        return

    ok = sum(1 for i in infos if i["parse_success"])
    silent_fail = sum(1 for i in infos if i.get("silent_fail"))
    toc_found = sum(1 for i in infos if i.get("toc_anchor") is not None)

    print("\n=============== 요약 ===============")
    print(f"총 {n}건 | 파싱성공 {ok} | 조용한 실패 {silent_fail} | 목차 발견 {toc_found}")
    print(f"{'파일':<40} {'fmt':<5} {'섹션':>4} {'타겟':>4} {'목차':>4} {'상태':<8}")
    print("-" * 80)
    for i in infos:
        status = "ok" if i["parse_success"] and i["section_count"] > 0 else (
            "PARSE_FAIL" if not i["parse_success"] else "0섹션"
        )
        name = i["file"][:38] + ("…" if len(i["file"]) > 38 else "")
        print(
            f"{name:<40} "
            f"{i['ext']:<5} "
            f"{i.get('section_count', 0):>4} "
            f"{i.get('target_count', 0):>4} "
            f"{'Y' if i.get('toc_anchor') is not None else 'N':>4} "
            f"{status:<8}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_targets(arg: Optional[str]) -> list[Path]:
    default = _ROOT / "data" / "proposal_sample"
    if arg is None:
        root = default
    else:
        root = Path(arg)

    if not root.exists():
        print(f"[에러] 경로 없음: {root}", file=sys.stderr)
        return []

    if root.is_file():
        return [root]

    exts = {".hwp", ".hwpx", ".pdf", ".docx", ".pptx"}
    return sorted([p for p in root.iterdir() if p.is_file() and p.suffix.lower() in exts])


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase D-1 파서 현황 진단 도구")
    ap.add_argument("target", nargs="?", default=None,
                    help="파일 경로 또는 디렉토리 (기본: data/proposal_sample/)")
    ap.add_argument("--dump", action="store_true",
                    help="파싱 텍스트·JSON을 data/diag_d1/ 에 덤프")
    ap.add_argument("--json-only", action="store_true",
                    help="콘솔에 JSON만 출력 (사람용 리포트 생략)")
    args = ap.parse_args()

    targets = collect_targets(args.target)
    if not targets:
        print("[경고] 진단 대상 파일이 없습니다.", file=sys.stderr)
        return 1

    dump_dir = _ROOT / "data" / "diag_d1" if args.dump else None
    infos: list[dict] = []
    for p in targets:
        try:
            info = diagnose(p, dump_dir=dump_dir)
        except Exception as e:
            info = {
                "file": p.name, "path": str(p),
                "size_bytes": p.stat().st_size if p.exists() else 0,
                "ext": p.suffix.lower().lstrip("."),
                "parse_success": False, "parse_error": f"진단 예외: {e!r}",
                "section_count": 0, "silent_fail": False,
                "toc_anchor": None, "toc_sample": [], "marker_hist": {},
            }
        infos.append(info)
        if not args.json_only:
            print_file_report(info)

    if args.json_only:
        print(json.dumps(infos, ensure_ascii=False, indent=2))
    else:
        print_summary(infos)

    if dump_dir:
        (dump_dir / "_summary.json").write_text(
            json.dumps(infos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n덤프: {dump_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
