from dataclasses import dataclass
from typing import Optional


@dataclass
class BidNotice:
    source: str
    title: str
    organization: Optional[str] = None
    category: Optional[str] = None
    bid_no: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None
    keywords: Optional[str] = None
    # Phase 3 확장 필드
    file_url: Optional[str] = None
    detail_url: Optional[str] = None
    apply_url: Optional[str] = None
    region: Optional[str] = None
    target: Optional[str] = None
    content: Optional[str] = None
    budget: Optional[str] = None
    contact: Optional[str] = None
    est_price: Optional[str] = None
