"""비용 산출 로직 — 토큰 수 → 원화 변환 (순수 함수, DB 의존 없음)"""


# 모델별 단가 (USD per 1M tokens) — ai_config 테이블에서 오버라이드 가능
DEFAULT_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}

DEFAULT_EXCHANGE_RATE = 1400  # USD → KRW


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: dict = None,
    exchange_rate: float = None,
) -> float:
    """토큰 수 → 원화 비용 (소수점 1자리)

    Args:
        model: 모델 ID
        input_tokens: 입력 토큰 수
        output_tokens: 출력 토큰 수
        pricing: {model: {input: $, output: $}} — None이면 기본값
        exchange_rate: 환율 — None이면 기본값 1400

    Returns:
        비용 (원, KRW)
    """
    pricing = pricing or DEFAULT_PRICING
    rate = exchange_rate or DEFAULT_EXCHANGE_RATE

    model_price = pricing.get(model)
    if not model_price:
        # 모델 ID 부분 매칭 시도 (haiku, sonnet 등)
        for key, price in pricing.items():
            if "haiku" in key and "haiku" in model:
                model_price = price
                break
            elif "sonnet" in key and "sonnet" in model:
                model_price = price
                break

    if not model_price:
        return 0.0

    input_cost_usd = (input_tokens / 1_000_000) * model_price["input"]
    output_cost_usd = (output_tokens / 1_000_000) * model_price["output"]
    total_krw = (input_cost_usd + output_cost_usd) * rate

    return round(total_krw, 1)
