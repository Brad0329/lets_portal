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
