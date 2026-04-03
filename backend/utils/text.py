"""텍스트 처리 유틸리티"""

import re
import html as html_mod


def clean_html(text: str) -> str:
    """HTML 엔티티 디코딩 + <br> 태그 → 줄바꿈 + 태그 제거"""
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = text.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    return text.strip()


def clean_html_to_text(html_str: str) -> str:
    """HTML content → 순수 텍스트 (태그 제거, 공백 정리)"""
    if not html_str:
        return ""
    text = html_mod.unescape(html_str)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
