"""AI 클라이언트 추상 인터페이스 — 모델 교체/추가 가능 구조"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AIResponse:
    """AI 호출 결과"""
    content: str = ""              # 응답 텍스트 (JSON 문자열 등)
    input_tokens: int = 0                          # 캐시 미적용 입력 토큰
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0           # 캐시 쓰기 (첫 호출에서 발생)
    cache_read_input_tokens: int = 0               # 캐시 읽기 (2회차 이상)
    model: str = ""
    success: bool = False
    error: str = ""


class BaseAIClient:
    """AI 클라이언트 추상 인터페이스"""

    def analyze_document(self, document_text: str, prompt: str,
                         *, system: Optional[str] = None,
                         use_cache: bool = False) -> AIResponse:
        """문서 파싱 — 텍스트 기반.

        system: system 프롬프트 (고정 부분). 반복 호출 시 캐시 대상.
        use_cache: system 프롬프트에 ephemeral cache_control을 붙임.
        """
        raise NotImplementedError

    def analyze_document_pdf(self, pdf_bytes: bytes, prompt: str) -> AIResponse:
        """PDF 직접 전달 분석 (지원 모델만)"""
        raise NotImplementedError

    def match_profile(self, criteria: dict, profile: dict, prompt: str) -> AIResponse:
        """매칭 분석 — 프로필 vs 평가기준"""
        raise NotImplementedError
