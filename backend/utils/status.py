"""공고 상태 판정 유틸리티"""

from datetime import datetime


def determine_status(end_date_str: str, date_format: str = "%Y-%m-%d") -> str:
    """마감일 기준 ongoing/closed 판정.
    마감일이 없거나 파싱 실패 시 'ongoing' 반환.
    """
    if not end_date_str:
        return "ongoing"
    try:
        end_dt = datetime.strptime(end_date_str[:10], date_format)
        return "closed" if end_dt < datetime.now() else "ongoing"
    except ValueError:
        return "ongoing"
