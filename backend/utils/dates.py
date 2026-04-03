"""날짜 포맷 유틸리티"""

from datetime import datetime


def format_date(dt_str: str) -> str:
    """다양한 날짜 형식 → yyyy-MM-dd 통합 변환.

    지원 형식:
    - yyyyMMddHHmm (나라장터)
    - yyyyMMdd
    - yyyy.MM.dd
    - yyyy-MM-dd (이미 정규 형식)
    """
    if not dt_str:
        return ""
    dt_str = dt_str.strip()

    # 이미 yyyy-MM-dd 형식이면 그대로
    if len(dt_str) >= 10 and dt_str[4] == "-" and dt_str[7] == "-":
        return dt_str[:10]

    # yyyy.MM.dd 형식
    if len(dt_str) >= 10 and dt_str[4] == ".":
        return dt_str[:10].replace(".", "-")

    # 구분자 제거 후 숫자만 추출
    cleaned = dt_str.replace("-", "").replace(" ", "").replace(":", "")

    try:
        if len(cleaned) >= 12:
            return datetime.strptime(cleaned[:12], "%Y%m%d%H%M").strftime("%Y-%m-%d")
        elif len(cleaned) >= 8 and cleaned[:8].isdigit():
            return datetime.strptime(cleaned[:8], "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        pass

    return dt_str
