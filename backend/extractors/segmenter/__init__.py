"""
Phase D 섹션 분할 패키지 — 3단계 폴백 구조.

    1차: toc_detector (목차 탐지, Python 결정적)   ← D-2
    2차: haiku_segmenter (LLM 마커 패턴 판별)       ← D-3
    3차: flat_chunker (강제 청크)                   ← D-4

bidwatch 이식 원칙(§8-1): `database`·`routers`·`config` 등
lets_portal 특정 모듈 import 금지. 순수 모듈 유지.
"""

from .toc_detector import detect_toc, TocEntry, TocResult  # noqa: F401
from .body_matcher import match_entries_to_body, MatchResult  # noqa: F401
