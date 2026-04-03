"""
K-Startup (창업진흥원) API 수집기
엔드포인트: https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01
"""

import requests
import logging
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_GO_KR_KEY
from database import get_connection
from collectors.base import BaseCollector
from utils.text import clean_html
from utils.dates import format_date
from utils.keywords import match_keywords

logger = logging.getLogger(__name__)

API_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"


class KstartupCollector(BaseCollector):
    source_name = "K-Startup"

    def collect_and_save(self, keywords=None, days: int = 1, mode: str = "daily") -> dict:
        """K-Startup은 display_settings에서 only_ongoing 읽음."""
        if keywords is None:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT keyword FROM keywords WHERE is_active=1")
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM display_settings WHERE setting_key='status_filter'")
        row = cursor.fetchone()
        only_ongoing = (row[0] == "ongoing") if row else True
        conn.close()

        logger.info(f"K-Startup 수집 시작: 키워드 {len(keywords)}개, 기간 {days}일, 진행중만={only_ongoing}")
        notices = self.fetch_announcements(keywords, days=days, only_ongoing=only_ongoing)
        notices = self.post_filter(notices)
        inserted, updated = self.save_to_db(notices)
        return {"source": self.source_name, "collected": len(notices), "inserted": inserted, "updated": updated}

    def fetch_announcements(self, keywords: list[str], days: int = 30, only_ongoing: bool = True) -> list[dict]:
        """K-Startup 사업공고 수집 (키워드 매칭)"""
        collected = []
        page = 1
        per_page = 100

        while True:
            params = {
                "serviceKey": DATA_GO_KR_KEY,
                "page": page,
                "perPage": per_page,
                "returnType": "json",
            }
            if only_ongoing:
                params["cond[rcrt_prgs_yn::EQ]"] = "Y"

            try:
                resp = requests.get(API_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"K-Startup API 호출 실패 (page={page}): {e}")
                break

            items = data.get("data", [])
            if not items:
                break

            total_count = data.get("totalCount", 0)
            logger.info(f"K-Startup page {page}: {len(items)}건 (전체 {total_count}건)")

            for item in items:
                title = clean_html(item.get("biz_pbanc_nm", ""))
                content = clean_html(item.get("pbanc_ctnt", "") or "")
                target = clean_html(item.get("aply_trgt_ctnt", "") or "")
                search_text = f"{title} {content} {target}".lower()

                matched = match_keywords(search_text, keywords)
                if not matched:
                    continue

                # 날짜 필터 (최근 N일)
                start_dt = item.get("pbanc_rcpt_bgng_dt", "")
                if start_dt and len(start_dt) >= 8:
                    try:
                        start_date = datetime.strptime(start_dt[:8], "%Y%m%d")
                        cutoff = datetime.now() - timedelta(days=days)
                        if start_date < cutoff:
                            continue
                    except ValueError:
                        pass

                end_dt = item.get("pbanc_rcpt_end_dt", "")
                detail_url = item.get("detl_pg_url") or ""
                apply_url = item.get("biz_aply_url") or ""
                main_url = detail_url or apply_url or item.get("biz_gdnc_url") or ""

                status = "ongoing" if item.get("rcrt_prgs_yn") == "Y" else "closed"

                collected.append({
                    "source": "K-Startup",
                    "title": title,
                    "organization": item.get("pbanc_ntrp_nm") or item.get("sprv_inst") or "창업진흥원",
                    "category": item.get("supt_biz_clsfc") or "",
                    "bid_no": str(item.get("pbanc_sn", "")),
                    "start_date": format_date(start_dt),
                    "end_date": format_date(end_dt),
                    "status": status,
                    "url": main_url,
                    "keywords": ",".join(matched),
                    "detail_url": detail_url,
                    "apply_url": apply_url,
                    "region": item.get("supt_regin") or "",
                    "target": item.get("aply_trgt_ctnt") or "",
                    "content": (content[:500] if content else ""),
                    "contact": item.get("prch_cnpl_no") or "",
                    "apply_method": clean_html(item.get("aply_mthd_onli_rcpt_istc") or item.get("aply_mthd_vst_rcpt_istc") or item.get("aply_mthd_etc_istc") or ""),
                    "biz_enyy": item.get("biz_enyy") or "",
                    "target_age": item.get("biz_trgt_age") or "",
                    "department": clean_html(item.get("biz_prch_dprt_nm") or ""),
                    "excl_target": clean_html(item.get("aply_excl_trgt_ctnt") or ""),
                    "biz_name": clean_html(item.get("intg_pbanc_biz_nm") or ""),
                })

            if page * per_page >= total_count:
                break
            page += 1

        logger.info(f"K-Startup 키워드 매칭 결과: {len(collected)}건")
        return collected


# ─── 하위 호환 함수 (collect_all.py에서 호출) ──────────

_collector = KstartupCollector()

def collect_and_save(keywords=None, days: int = 1, mode="daily"):
    return _collector.collect_and_save(keywords=keywords, days=days, mode=mode)

def fetch_announcements(keywords, days=30, only_ongoing=True):
    return _collector.fetch_announcements(keywords, days=days, only_ongoing=only_ongoing)

def save_to_db(notices):
    return _collector.save_to_db(notices)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = collect_and_save()
    print(f"\n===== K-Startup 수집 결과 =====")
    print(f"  수집: {result['collected']}건")
    print(f"  신규: {result['inserted']}건")
    print(f"  업데이트: {result['updated']}건")
