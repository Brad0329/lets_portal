"""
목차 탐지 — Phase D-2 1차 폴백 (Python 결정적, LLM 비용 0).

D-1 에서 확인된 특수 조건:
    HWP→마크다운 파싱이 "목     차" + 모든 목차 엔트리를 한 줄에 밀어넣는다.
    따라서 "라인 단위 수확"(설계 §3-2 의사코드)은 동작하지 않는다.
    대신 앵커 이후 구간을 토큰화해 상태 기계로 파싱.

마커 종류 (D-1 샘플 9건 전부 관찰 기준):
    "Ⅰ." "Ⅱ." ... 로마자 + 점             → level 1
    "1." "2." ... 숫자 + 점                 → level 2
    "1-1)" "2-10)" ... 숫자-숫자 + 우괄호   → level 3

엔트리 포맷:
    <마커> <제목 단어들> <페이지번호>
    페이지는 1~3자리 숫자 (01, 03, 100 포함)

안전장치:
    - 목차 영역(앵커 이후 4000자) 바깥은 보지 않음 → 본문 시작부의 마커와 혼동 방지
    - 동일 marker+title 쌍 연속 중복은 1회로 축약 (`| < 목차 >` 표 라인 중복 대응)
    - 제목 토큰 0개 or 페이지 없는 엔트리는 버림
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"

# 앵커 — "목차", "목 차", "차례", "CONTENTS", "목록"
_ANCHOR_RE = re.compile(r"목\s*차|차\s*례|CONTENTS|Contents|목\s*록")

# 토큰별 마커 판별
_RE_ROMAN = re.compile(rf"^([{_ROMAN}])\.$")       # "Ⅰ."
_RE_NUM = re.compile(r"^(\d{1,2})\.$")              # "1."
_RE_SUB = re.compile(r"^(\d{1,2})-(\d{1,2})\)$")   # "1-1)"

# 순수 페이지 숫자 (선행 0 허용: 01, 03)
_RE_PAGE = re.compile(r"^\d{1,3}$")

# 토큰화 — 공백 분리 + 앞뒤 장식문자 제거
_STRIP_CHARS = "<>·«»()〈〉"


@dataclass
class TocEntry:
    marker: str                # "Ⅰ.", "1.", "1-1)"
    title: str                 # "제안 개요", "기관연혁"
    page: int                  # 목차에 적힌 페이지
    level: int                 # 1=로마자, 2=숫자, 3=하위번호
    toc_position: int          # 목차 내 순서 (0-based)

    def normalized_name(self, parent_roman: str = "") -> str:
        """Section.name 과 같은 형식의 정규화 이름.

        parent_roman: 상위 level=1 엔트리의 로마자 (e.g. "Ⅰ").
                      level=2 엔트리에 붙여 "Ⅰ.1 제목" 형태로 반환.
        """
        if self.level == 1:
            return f"{self.marker} {self.title}".strip()
        if self.level == 2:
            num = self.marker.rstrip(".")
            return f"{parent_roman}.{num} {self.title}".strip()
        # level 3
        return f"{parent_roman}.{self.marker} {self.title}".strip()


@dataclass
class TocResult:
    found: bool = False
    reason: str = ""
    anchor_char_pos: int = -1       # 앵커 시작 문자 위치 (text 기준)
    anchor_line: int = -1           # 앵커 라인 번호
    body_start_line: int = -1       # "본문" 추정 시작 라인 (목차 영역 끝 이후)
    entries: list = field(default_factory=list)  # list[TocEntry]

    def summary(self) -> dict:
        if not self.found:
            return {"found": False, "reason": self.reason}
        by_level = {}
        for e in self.entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
        return {
            "found": True,
            "anchor_line": self.anchor_line,
            "body_start_line": self.body_start_line,
            "entries_total": len(self.entries),
            "by_level": by_level,
        }


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def detect_toc(text: str, head_chars: int = 8000, toc_span_chars: int = 4000) -> TocResult:
    """파싱된 마크다운 텍스트에서 목차 엔트리 추출.

    Args:
        text: `file_parser.extract_text()` 결과 마크다운.
        head_chars: 앵커 탐지 대상 (문서 앞부분 N자). 기본 8000.
        toc_span_chars: 앵커 이후 목차 영역 길이. 기본 4000.

    Returns:
        TocResult. found=False면 reason 확인.
    """
    head = text[:head_chars]

    anchor = _ANCHOR_RE.search(head)
    if not anchor:
        return TocResult(found=False, reason="앵커 없음")

    toc_region = head[anchor.end() : anchor.end() + toc_span_chars]
    entries = _parse_tokens(toc_region)

    if not entries:
        return TocResult(
            found=False,
            reason="앵커 발견, 엔트리 추출 실패",
            anchor_char_pos=anchor.start(),
            anchor_line=_line_of(text, anchor.start()),
        )

    anchor_line = _line_of(text, anchor.start())

    # 본문 시작 라인 추정 — 앵커 라인 바로 뒤.
    # HWP 파서가 목차를 1~3줄에 밀어넣으므로 앵커 이후 매우 가까이 본문 시작됨.
    # 과도하게 보수적으로 잡으면 본문 앞단 섹션을 전부 miss 함(#8 경남 47%의 원인).
    # 단조성은 match_entries_to_body 의 cursor 가 보장하므로 start_line 작아도 안전.
    body_start_line = anchor_line + 1

    return TocResult(
        found=True,
        anchor_char_pos=anchor.start(),
        anchor_line=anchor_line,
        body_start_line=body_start_line,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# 내부 — 토큰 파서
# ---------------------------------------------------------------------------

_DECORATION_CHARS = set("▸▶▼▽◇◆◈○●◎◦ㅇ★☆♦♠♣♥〓〒〓→←↑↓⇒⇐⇑⇓")


def _parse_tokens(region: str) -> list:
    """토큰 상태 기계로 목차 영역 파싱.

    품질 필터 (D-2 튜닝):
    - 제목 토큰 10개 초과 → 본문이 새어들어온 False positive 로 간주 후 엔트리 버림
    - 제목에 장식문자(▸, ○ 등) 포함 → 본문 성격 → 엔트리 버림
    - 페이지 단조 감소가 2회 연속 → 이후 엔트리 수확 중단 (목차 끝에 본문 합류)
    """
    tokens = [tok.strip(_STRIP_CHARS) for tok in region.split()]
    tokens = [t for t in tokens if t]

    raw_entries: list[TocEntry] = []
    cur: dict | None = None

    def commit():
        nonlocal cur
        if not cur:
            return
        toks = cur["title_toks"]
        page = cur["page"]
        if not toks or page is None:
            cur = None
            return
        title = " ".join(toks).strip()
        # 필터 1: 제목 토큰 수 (긴 본문 문장이 아닌 진짜 섹션 제목)
        if len(toks) > 10:
            cur = None
            return
        # 필터 2: 장식문자 — 본문 자동 배치된 기호
        if any(ch in _DECORATION_CHARS for ch in title):
            cur = None
            return
        level = {"roman": 1, "num": 2, "sub": 3}[cur["type"]]
        raw_entries.append(TocEntry(
            marker=cur["marker"],
            title=title,
            page=page,
            level=level,
            toc_position=len(raw_entries),
        ))
        cur = None

    for tok in tokens:
        m_roman = _RE_ROMAN.match(tok)
        m_num = _RE_NUM.match(tok)
        m_sub = _RE_SUB.match(tok)

        if m_roman or m_num or m_sub:
            commit()
            typ = "roman" if m_roman else ("sub" if m_sub else "num")
            cur = {"marker": tok, "type": typ, "title_toks": [], "page": None}
            continue

        if cur is None:
            continue

        if _RE_PAGE.match(tok):
            if cur["title_toks"]:
                cur["page"] = int(tok)
                commit()
            continue

        if tok == "|" or set(tok) <= {"-"}:
            continue

        cur["title_toks"].append(tok)

    commit()

    # 단조성 체크 — 페이지가 2회 연속 크게 감소하면 목차 끝 이후로 판단, 절단
    if raw_entries:
        truncated = [raw_entries[0]]
        decrease_streak = 0
        for prev, cur_e in zip(raw_entries, raw_entries[1:]):
            if cur_e.page < prev.page - 5:  # 5페이지 이상 역행
                decrease_streak += 1
                if decrease_streak >= 2:
                    break
            else:
                decrease_streak = 0
            truncated.append(cur_e)
        raw_entries = truncated

    # 중복 축약
    dedup: list[TocEntry] = []
    for e in raw_entries:
        key = (e.marker, e.title, e.page)
        if any((d.marker, d.title, d.page) == key for d in dedup):
            continue
        e.toc_position = len(dedup)
        dedup.append(e)

    return dedup


# ---------------------------------------------------------------------------
# 보조 유틸
# ---------------------------------------------------------------------------

def _line_of(text: str, char_pos: int) -> int:
    """문자 위치 → 라인 번호 (0-based)."""
    if char_pos <= 0:
        return 0
    return text.count("\n", 0, char_pos)


def _estimate_body_start_line(text: str, from_char: int) -> int:
    """목차 영역 종료 후 첫 논-빈 라인."""
    lines = text.split("\n")
    # 문자 위치 → 라인 번호
    acc = 0
    start_line = 0
    for i, ln in enumerate(lines):
        acc += len(ln) + 1
        if acc >= from_char:
            start_line = i + 1
            break
    for i in range(start_line, len(lines)):
        if lines[i].strip() and not lines[i].strip().startswith("|"):
            return i
    return start_line
