"""
Extractor 추상 인터페이스 + 공통 데이터 클래스.

portable 설계 — utils.file_parser, ai.base만 의존.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    """회사 역량 진술 단위.

    6개 카테고리 중 하나로 분류 (Identity/Methodology/USP/Philosophy/Story/Operational).
    """
    id: str = ""                                # "cl_001" — 추출 후 부여
    category: str = ""                          # 6개 중 하나
    statement: str = ""                         # 주장 본문 (한 문장)
    tags: dict = field(default_factory=dict)    # {"domain":[...], "audience":[...], "method":[...]}
    proposal_sections: list = field(default_factory=list)  # 제안서 어느 섹션에 쓸 수 있는지
    length_variants: dict = field(default_factory=dict)    # {"tagline":..., "summary":..., "detail":...}
    evidence_refs: list = field(default_factory=list)      # ["실적#14", ...] — 정량 프로필 ID 참조
    source: dict = field(default_factory=dict)             # {"src_id":..., "section":..., "page":...}
    recurrence: int = 1                         # 여러 제안서에 등장한 횟수
    confidence: float = 0.8                     # 0.0~1.0 — AI 추출 신뢰도
    user_verified: bool = False                 # 사용자 검토 완료


@dataclass
class Section:
    """섹션 분할 결과 — LLM 추출 단위"""
    name: str              # e.g. "Ⅲ.1 업체 현황"
    text: str              # 본문 (마크다운)
    level: int = 2         # 1=최상위(Ⅰ/Ⅱ/Ⅲ), 2=숫자, 3=하위번호(1-1 등)
    start_line: int = 0
    end_line: int = 0


@dataclass
class SourceMeta:
    """추출 대상 파일 + 메타 정보"""
    path: str
    year: Optional[int] = None
    awarded: Optional[bool] = None              # 수주=True, 탈락=False, 모름=None
    proposal_title: Optional[str] = None
    organization: Optional[str] = None          # 발주처
    src_id: str = ""                            # "src_01" — extract 시 부여


@dataclass
class ExtractionConfig:
    """추출 동작 설정 — 전역 상수 대신 주입"""
    categories: tuple = ("Identity", "Methodology", "USP", "Philosophy", "Story", "Operational")

    # 통제 어휘 — LLM이 임의 태그 생성 방지
    tag_vocabulary: dict = field(default_factory=lambda: {
        "domain": [
            "ESG", "창업교육", "창업컨설팅", "액셀러레이팅", "관광", "문화콘텐츠",
            "메이커", "소상공인", "지역혁신", "여성창업", "기술창업", "탄소중립",
        ],
        "audience": [
            "예비창업자", "초기창업자", "스타트업", "소상공인", "청소년", "대학생",
            "여성", "시니어", "재창업자", "관광벤처",
        ],
        "method": [
            "PBL", "멘토링", "컨설팅", "피칭", "해커톤", "IR", "데모데이",
            "그룹멘토링", "사후추적조사", "자가진단", "역량진단",
        ],
    })

    # 회사 claim이 거의 없는 섹션명 패턴 (스킵 대상)
    skip_section_keywords: tuple = (
        "사업의 필요성", "사업필요성", "추진배경",
        "사업목표", "사업목적",
        "기대효과", "파급효과",
        "제안개요",  # 상위 목차 헤더
    )

    # LLM 설정
    primary_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    max_claims_per_section: int = 12

    # 중복/품질 임계치
    min_confidence: float = 0.6
    dedupe_similarity: float = 0.85

    # 최적화 플래그
    use_prompt_cache: bool = True

    # 비용 산출 (원화)
    exchange_rate: float = 1400.0
    pricing: dict = field(default_factory=lambda: {
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    })


@dataclass
class ExtractionResult:
    """추출 최종 결과 — JSON 직렬화 가능"""
    claims: list = field(default_factory=list)                # list[Claim]
    quantitative_hints: list = field(default_factory=list)    # [{"type":"실적","name":...}, ...]
    sources: list = field(default_factory=list)               # list[SourceMeta]
    total_cost_krw: float = 0.0
    total_input_tokens: int = 0                               # 캐시 미적용 입력 토큰
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0                      # 캐시 쓰기 (통상 첫 호출)
    total_cache_read_tokens: int = 0                          # 캐시 히트로 재사용된 토큰
    total_llm_calls: int = 0
    warnings: list = field(default_factory=list)              # [{"type":"...", "message":"..."}]
    model: str = ""


@dataclass
class MergeReport:
    """기존 결과에 새 결과 병합 시 요약"""
    merged: int = 0            # 같은 claim으로 병합된 개수
    new_added: int = 0         # 새로 추가된 claim
    strengthened: int = 0      # recurrence 증가
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 추상 인터페이스
# ---------------------------------------------------------------------------

class BaseExtractor(ABC):
    """추출기 추상 인터페이스.

    구현체 규약:
    - 단일 진입점 extract(sources) -> ExtractionResult
    - DB/HTTP I/O 금지 (호출 측이 저장/업로드 담당)
    - 진행률은 progress_cb 콜백으로 통보 (dict 전달)
    - 실패는 예외 대신 ExtractionResult.warnings에 기록
    """

    @abstractmethod
    def extract(
        self,
        sources: list,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> ExtractionResult:
        """여러 소스 일괄 추출."""
        ...

    @abstractmethod
    def extract_single(
        self,
        source: SourceMeta,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> list:
        """단일 소스 추출 — claims 리스트 반환."""
        ...
