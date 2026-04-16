"""Claude API 구현 (Haiku/Sonnet)"""

import json
import base64
import logging
from .base import BaseAIClient, AIResponse

logger = logging.getLogger(__name__)


class ClaudeClient(BaseAIClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def analyze_document(self, document_text: str, prompt: str) -> AIResponse:
        """텍스트 기반 문서 분석"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": f"{prompt}\n\n---\n\n{document_text}"
                }],
            )
            return AIResponse(
                content=response.content[0].text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self.model,
                success=True,
            )
        except Exception as e:
            logger.exception("Claude API 호출 실패")
            return AIResponse(error=str(e), model=self.model)

    def analyze_document_pdf(self, pdf_bytes: bytes, prompt: str) -> AIResponse:
        """PDF를 base64로 Claude에 직접 전달"""
        try:
            b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }],
            )
            return AIResponse(
                content=response.content[0].text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self.model,
                success=True,
            )
        except Exception as e:
            logger.exception("Claude PDF API 호출 실패")
            return AIResponse(error=str(e), model=self.model)

    def match_profile(self, criteria: dict, profile: dict, prompt: str) -> AIResponse:
        """매칭 분석 — 프롬프트에 criteria/profile 삽입"""
        filled_prompt = prompt.replace("{criteria_json}", json.dumps(criteria, ensure_ascii=False, indent=2))
        filled_prompt = filled_prompt.replace("{profile_json}", json.dumps(profile, ensure_ascii=False, indent=2))

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": filled_prompt,
                }],
            )
            return AIResponse(
                content=response.content[0].text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self.model,
                success=True,
            )
        except Exception as e:
            logger.exception("Claude 매칭 API 호출 실패")
            return AIResponse(error=str(e), model=self.model)
