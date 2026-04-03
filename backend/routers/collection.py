"""수집 실행 API 라우터"""

import threading
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from auth import require_admin

router = APIRouter(tags=["collection"])

# 전역 수집 상태 관리
_collect_lock = threading.Lock()
_collecting_targets = set()


def _calc_days(start_date: str, end_date: str) -> int:
    """start_date~end_date를 days(오늘 기준 며칠 전)로 변환. 기본 1일."""
    from datetime import datetime as _dt, date as _date
    if start_date:
        try:
            sd = _dt.strptime(start_date, "%Y-%m-%d").date()
            days = (_date.today() - sd).days + 1
            return max(days, 1)
        except ValueError:
            pass
    return 1  # 기본: 당일 1일


@router.post("/api/collect")
def run_collect(
    request: Request,
    target: str = Query(default="all"),
    start_date: str = Query(default="", description="수집 시작일 (yyyy-MM-dd)"),
    end_date: str = Query(default="", description="수집 종료일 (yyyy-MM-dd)"),
):
    """수집 실행 (관리자 전용). target: all=전체, scrapers=개별기관 스크래퍼만"""
    require_admin(request)

    days = _calc_days(start_date, end_date)

    with _collect_lock:
        if target in _collecting_targets:
            return JSONResponse(status_code=409, content={"error": "이미 수집이 진행 중입니다. 완료 후 다시 시도해주세요."})
        _collecting_targets.add(target)

    try:
        if target == "scrapers":
            from collectors.generic_scraper import collect_all_scrapers
            from datetime import datetime as _dt
            batch_time = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            return collect_all_scrapers(days=days, batch_time=batch_time)

        from collectors.collect_all import collect_all
        results = collect_all()
        return {"results": results}
    finally:
        with _collect_lock:
            _collecting_targets.discard(target)


@router.post("/api/scraper/{source_name}/collect")
def collect_single_scraper(
    request: Request,
    source_name: str,
    start_date: str = Query(default="", description="수집 시작일"),
    end_date: str = Query(default="", description="수집 종료일"),
):
    """개별 스크래퍼 기관 단건 수집 (재시도용)"""
    require_admin(request)
    days = _calc_days(start_date, end_date)

    from collectors.generic_scraper import collect_single_by_name
    try:
        result = collect_single_by_name(source_name, days=days)
        return result
    except Exception as e:
        return {"source": source_name, "collected": 0, "matched": 0, "inserted": 0, "updated": 0, "error": str(e)}
