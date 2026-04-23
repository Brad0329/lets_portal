"""
목차 엔트리 → 본문 라인 매칭 — Phase D-2.

목적:
    TocEntry 리스트를 받아 각 엔트리가 본문에서 처음 나타나는 라인을 찾는다.
    이후 Section 객체로 변환해 LLM 호출 단위로 쓴다.

매칭 전략 (순서대로 시도):
    1) 엄격: "<로마자>. <제목>" or "<숫자>. <제목>" 형태 완전 일치
    2) 완화: 제목만 일치 (마커 변형 대응 — HWP 파서가 "1 " 과 "1." 혼용)
    3) 근사: 제목의 앞 토큰 몇 개만 일치 (제목이 본문에서 줄바꿈된 경우)

단조성:
    이미 매칭된 엔트리 다음 라인부터만 탐색 → 역순 매칭 방지 & 같은 제목 반복 대응.

표 라인 스킵:
    HWP→마크다운 표는 `|`로 시작. 헤딩 후보에서 제외.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .toc_detector import TocEntry


_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"


@dataclass
class MatchedSection:
    """매칭된 섹션 — Section 과 유사하나 extractors.base 를 직접 import 하지 않음."""
    name: str
    level: int
    start_line: int
    end_line: int = 0
    matched_mode: str = ""    # "strict" | "relaxed" | "approx" | "missed"
    toc_entry: Optional[TocEntry] = None


@dataclass
class MatchResult:
    sections: list = field(default_factory=list)  # list[MatchedSection]
    match_count: int = 0
    total_entries: int = 0

    @property
    def match_rate(self) -> float:
        return self.match_count / self.total_entries if self.total_entries else 0.0

    def summary(self) -> dict:
        by_mode = {}
        for s in self.sections:
            by_mode[s.matched_mode] = by_mode.get(s.matched_mode, 0) + 1
        return {
            "total": self.total_entries,
            "matched": self.match_count,
            "rate": round(self.match_rate, 3),
            "by_mode": by_mode,
        }


def match_entries_to_body(
    text: str,
    entries: list,
    body_start_line: int = 0,
) -> MatchResult:
    """엔트리 리스트를 본문에 매칭.

    Args:
        text: 파싱된 마크다운 전체.
        entries: TocEntry 리스트 (toc_detector.detect_toc 결과).
        body_start_line: 목차 이후 본문 시작으로 추정된 라인.

    Returns:
        MatchResult — 각 TocEntry 에 대응하는 MatchedSection.
    """
    lines = text.split("\n")
    cursor = body_start_line
    sections: list[MatchedSection] = []

    # 상위 로마자 저장 (level 2 매칭 시 "<로마자>. <제목>" 와 "<숫자>. <제목>" 둘 다 시도)
    current_roman = ""

    for entry in entries:
        if entry.level == 1:
            current_roman = entry.marker.rstrip(".")

        hit_line, mode = _find_line(
            lines, entry, current_roman, start_from=cursor
        )

        name = entry.normalized_name(parent_roman=current_roman)

        if hit_line >= 0:
            sections.append(MatchedSection(
                name=name,
                level=entry.level,
                start_line=hit_line,
                matched_mode=mode,
                toc_entry=entry,
            ))
            cursor = hit_line + 1
        else:
            sections.append(MatchedSection(
                name=name,
                level=entry.level,
                start_line=-1,
                matched_mode="missed",
                toc_entry=entry,
            ))

    # end_line 계산 — 다음 매칭된 섹션의 start_line
    for i, s in enumerate(sections):
        if s.start_line < 0:
            continue
        nxt = next(
            (ns.start_line for ns in sections[i + 1:] if ns.start_line >= 0),
            len(lines),
        )
        s.end_line = nxt

    matched = sum(1 for s in sections if s.start_line >= 0)
    return MatchResult(
        sections=sections,
        match_count=matched,
        total_entries=len(entries),
    )


# ---------------------------------------------------------------------------
# 내부 — 라인 매칭
# ---------------------------------------------------------------------------

_RE_TITLE_SANITIZE = re.compile(r"[·.,()\s]+")


def _find_line(
    lines: list,
    entry: TocEntry,
    current_roman: str,
    start_from: int,
) -> tuple:
    """주어진 엔트리에 해당하는 본문 라인 찾기. (line_idx, mode) 반환."""
    title_norm = _RE_TITLE_SANITIZE.sub("", entry.title)
    if not title_norm:
        return -1, "missed"

    # 허용 매칭 패턴 — 엄격 → 완화 순
    # level 1 (Ⅰ.): "Ⅰ. <제목>" 또는 "Ⅰ . <제목>" (공백 허용)
    # level 2 (1.): "1. <제목>", "1 <제목>", "1.<제목>"
    # level 3 (1-1)): "1-1) <제목>" ...

    for li in range(start_from, len(lines)):
        raw = lines[li].strip()
        if not raw or raw.startswith("|"):
            continue
        if len(raw) > 200:  # 섹션 제목이 200자 넘는 일은 없다
            continue

        # 1) 엄격 매칭
        if _match_strict(raw, entry):
            return li, "strict"

        # 2) 완화 매칭 — 제목만 유사
        if _match_relaxed(raw, entry, title_norm):
            return li, "relaxed"

    # 3) 근사 — 제목 앞 토큰 n개만 일치
    n_tokens = min(3, len(entry.title.split()))
    if n_tokens >= 2:
        prefix = " ".join(entry.title.split()[:n_tokens])
        prefix_norm = _RE_TITLE_SANITIZE.sub("", prefix)
        for li in range(start_from, min(start_from + 500, len(lines))):
            raw = lines[li].strip()
            if not raw or raw.startswith("|") or len(raw) > 200:
                continue
            raw_norm = _RE_TITLE_SANITIZE.sub("", raw)
            if prefix_norm in raw_norm and _has_marker_prefix(raw, entry):
                return li, "approx"

    return -1, "missed"


def _match_strict(line: str, entry: TocEntry) -> bool:
    """라인이 <마커>. <제목> 형태로 정확히 시작하는지."""
    marker = entry.marker
    # 로마자 마커의 경우 "Ⅰ." 또는 "Ⅰ . " 변형 허용
    if entry.level == 1:
        roman = marker.rstrip(".")
        patterns = [
            rf"^{re.escape(roman)}\s*\.\s*{re.escape(entry.title)}$",
            rf"^{re.escape(roman)}\s*\.\s*{re.escape(entry.title)}\s*$",
        ]
        for p in patterns:
            if re.match(p, line):
                return True
    elif entry.level == 2:
        num = marker.rstrip(".")
        # "1 제목", "1. 제목", "1.제목"
        patterns = [
            rf"^{re.escape(num)}\s*\.?\s+{re.escape(entry.title)}$",
            rf"^{re.escape(num)}\s*\.?\s+{re.escape(entry.title)}\s*$",
        ]
        for p in patterns:
            if re.match(p, line):
                return True
    else:  # level 3
        patterns = [
            rf"^{re.escape(marker)}\s+{re.escape(entry.title)}$",
            rf"^{re.escape(entry.title)}$",  # 일부 파싱에선 "1-1)"가 앞 라인으로 분리
        ]
        for p in patterns:
            if re.match(p, line):
                return True
    return False


def _match_relaxed(line: str, entry: TocEntry, title_norm: str) -> bool:
    """마커는 무시하고 제목만 근사 일치 + 라인에 번호 흔적이 있을 때."""
    line_norm = _RE_TITLE_SANITIZE.sub("", line)
    if title_norm not in line_norm:
        return False
    # 라인이 섹션 제목으로 보이는 형식인지 (너무 긴 본문 라인 배제)
    if len(line) > 80:
        return False
    return _has_marker_prefix(line, entry)


def _has_marker_prefix(line: str, entry: TocEntry) -> bool:
    """라인이 마커(로마자·숫자·하위번호) 로 시작하는지 대략 확인."""
    stripped = line.lstrip()
    if not stripped:
        return False
    if entry.level == 1:
        return stripped[0] in _ROMAN
    if entry.level == 2:
        num = entry.marker.rstrip(".")
        # "1 제목", "1. 제목", "1.제목", ".1 제목"(상위 로마자 분리), "1-" 모두 허용
        return bool(re.match(rf"^\.?{re.escape(num)}\b", stripped))
    if entry.level == 3:
        return stripped.startswith(entry.marker) or bool(re.match(r"^\d+[-.]", stripped))
    return False
