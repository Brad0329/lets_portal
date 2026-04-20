"""
Extractors — 제안서/문서에서 회사 역량 claim 추출 (portable 모듈)

공개 API:
    from extractors import (
        ProposalAssetExtractor, ExtractionConfig, SourceMeta, ExtractionResult, Claim,
    )

이식 가이드:
    이 디렉토리 전체를 복사 + `utils/file_parser.py` + `ai/base.py` 복사.
    프로젝트 특정 모듈(DB, router, config) import 없음.
"""

from .base import (
    Claim,
    Section,
    ExtractionConfig,
    SourceMeta,
    ExtractionResult,
    MergeReport,
    BaseExtractor,
)
from .proposal import ProposalAssetExtractor

__all__ = [
    "Claim",
    "Section",
    "ExtractionConfig",
    "SourceMeta",
    "ExtractionResult",
    "MergeReport",
    "BaseExtractor",
    "ProposalAssetExtractor",
]
