"""
문서 파싱 모듈 — 향후 독립 패키지(lets_doc_parser) 분리 대비
PDF, HWPX, DOCX, HWP(구형) 문서에서 텍스트를 추출한다.

사용법:
    from utils.file_parser import extract_text
    result = extract_text("제안요청서.pdf")
    if result.success:
        print(result.text)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    text: str = ""              # 추출된 텍스트 (마크다운)
    format: str = ""            # 원본 포맷 (pdf/hwpx/docx/hwp)
    page_count: int = 0         # 페이지 수 (알 수 있는 경우)
    raw_bytes: bytes = field(default=b"", repr=False)  # 원본 바이너리 (PDF→Claude 직접 전달용)
    success: bool = False       # 파싱 성공 여부
    error: str = ""             # 실패 시 에러 메시지


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def extract_text(file_path: str) -> ParseResult:
    """확장자 판별 → 적절한 파서 호출 → ParseResult 반환"""
    p = Path(file_path)
    if not p.exists():
        return ParseResult(error=f"파일 없음: {file_path}", format=p.suffix.lstrip("."))

    suffix = p.suffix.lower()
    raw = p.read_bytes()

    parsers = {
        ".pdf": _parse_pdf,
        ".hwpx": _parse_hwpx,
        ".docx": _parse_docx,
        ".hwp": _parse_hwp,
    }

    parser = parsers.get(suffix)
    if parser is None:
        return ParseResult(
            error=f"지원하지 않는 포맷: {suffix}",
            format=suffix.lstrip("."),
            raw_bytes=raw,
        )

    try:
        result = parser(p, raw)
        return result
    except Exception as e:
        logger.exception("파싱 실패: %s", file_path)
        return ParseResult(
            error=f"파싱 실패: {e}",
            format=suffix.lstrip("."),
            raw_bytes=raw,
        )


# ---------------------------------------------------------------------------
# PDF 파서 (pdfplumber)
# ---------------------------------------------------------------------------

def _parse_pdf(path: Path, raw: bytes) -> ParseResult:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""

            # 표 추출 — 마크다운 테이블로 변환
            tables = page.extract_tables()
            table_md = ""
            for table in tables:
                table_md += _table_to_markdown(table) + "\n\n"

            if text.strip() or table_md.strip():
                page_text = f"--- 페이지 {i} ---\n"
                if text.strip():
                    page_text += text.strip() + "\n"
                if table_md.strip():
                    page_text += "\n" + table_md.strip() + "\n"
                pages.append(page_text)

    full_text = "\n\n".join(pages)
    if not full_text.strip():
        return ParseResult(
            error="텍스트 추출 실패 (이미지 PDF일 수 있음)",
            format="pdf",
            page_count=page_count,
            raw_bytes=raw,
        )

    return ParseResult(
        text=full_text,
        format="pdf",
        page_count=page_count,
        raw_bytes=raw,
        success=True,
    )


# ---------------------------------------------------------------------------
# HWPX 파서 (XML 직접 파싱 — lxml)
# ---------------------------------------------------------------------------

def _parse_hwpx(path: Path, raw: bytes) -> ParseResult:
    import zipfile
    from lxml import etree

    if not zipfile.is_zipfile(path):
        return ParseResult(error="유효하지 않은 HWPX 파일", format="hwpx", raw_bytes=raw)

    sections = []
    with zipfile.ZipFile(path) as zf:
        # HWPX는 ZIP 안에 Contents/sectionN.xml 파일들이 있음
        section_files = sorted(
            [n for n in zf.namelist() if n.startswith("Contents/") and n.endswith(".xml") and "section" in n.lower()]
        )
        if not section_files:
            # 대체: 모든 XML에서 텍스트 시도
            section_files = sorted(
                [n for n in zf.namelist() if n.endswith(".xml") and "Contents/" in n]
            )

        for sf in section_files:
            xml_bytes = zf.read(sf)
            try:
                root = etree.fromstring(xml_bytes)
            except etree.XMLSyntaxError:
                continue

            # 네임스페이스 제거 후 텍스트 추출
            texts = _hwpx_extract_node(root)
            if texts:
                sections.append(texts)

    full_text = "\n\n".join(sections)
    if not full_text.strip():
        return ParseResult(error="HWPX 텍스트 추출 실패", format="hwpx", raw_bytes=raw)

    return ParseResult(
        text=full_text,
        format="hwpx",
        page_count=len(sections) or 1,
        raw_bytes=raw,
        success=True,
    )


def _hwpx_extract_node(node) -> str:
    """HWPX XML 노드에서 텍스트를 재귀 추출 (표 포함)"""
    # 로컬 이름 기준으로 처리 (네임스페이스 무시)
    local = _local_name(node)
    result_parts = []

    if local == "tbl":
        # 표 → 마크다운 테이블로 변환
        table_data = _hwpx_parse_table(node)
        if table_data:
            result_parts.append(_table_to_markdown(table_data))
        return "\n".join(result_parts)

    if local == "t":
        # 텍스트 노드
        return (node.text or "").strip()

    if local == "p":
        # 단락 — 하위 텍스트 수집 후 줄바꿈
        line_parts = []
        for child in node:
            t = _hwpx_extract_node(child)
            if t:
                line_parts.append(t)
        line = " ".join(line_parts).strip()
        return line + "\n" if line else ""

    # 그 외: 재귀
    for child in node:
        t = _hwpx_extract_node(child)
        if t:
            result_parts.append(t)

    return "\n".join(result_parts)


def _hwpx_parse_table(tbl_node) -> list:
    """HWPX <tbl> 노드에서 2D 리스트 추출"""
    rows = []
    for child in tbl_node:
        if _local_name(child) == "tr":
            cells = []
            for cell in child:
                if _local_name(cell) == "tc":
                    cell_texts = []
                    for sub in cell.iter():
                        if _local_name(sub) == "t" and sub.text:
                            cell_texts.append(sub.text.strip())
                    cells.append(" ".join(cell_texts))
            if cells:
                rows.append(cells)
    return rows


def _local_name(node) -> str:
    """네임스페이스 제거한 로컬 태그명"""
    tag = node.tag if isinstance(node.tag, str) else ""
    if "}" in tag:
        return tag.split("}")[-1]
    return tag


# ---------------------------------------------------------------------------
# DOCX 파서 (python-docx)
# ---------------------------------------------------------------------------

def _parse_docx(path: Path, raw: bytes) -> ParseResult:
    import docx

    doc = docx.Document(str(path))
    parts = []

    for element in doc.element.body:
        tag = _local_name(element)

        if tag == "p":
            # 단락
            para = docx.oxml.ns.qn("w:p")  # noqa: F841
            text = element.text or ""
            # 하위 run 텍스트 수집
            runs = element.findall(".//" + docx.oxml.ns.qn("w:t"))
            text = "".join(r.text or "" for r in runs)
            if text.strip():
                parts.append(text.strip())

        elif tag == "tbl":
            # 표 → 마크다운
            table_data = _docx_parse_table(element, docx.oxml.ns.qn)
            if table_data:
                parts.append(_table_to_markdown(table_data))

    full_text = "\n\n".join(parts)
    if not full_text.strip():
        return ParseResult(error="DOCX 텍스트 추출 실패", format="docx", raw_bytes=raw)

    return ParseResult(
        text=full_text,
        format="docx",
        page_count=0,  # DOCX는 페이지 수 알기 어려움
        raw_bytes=raw,
        success=True,
    )


def _docx_parse_table(tbl_element, qn) -> list:
    """DOCX <w:tbl> 요소에서 2D 리스트 추출"""
    rows = []
    for tr in tbl_element.findall(qn("w:tr")):
        cells = []
        for tc in tr.findall(qn("w:tc")):
            runs = tc.findall(".//" + qn("w:t"))
            cell_text = "".join(r.text or "" for r in runs)
            cells.append(cell_text.strip())
        if cells:
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# HWP(구형) 파서 — pywin32 변환 시도, 실패 시 스킵
# ---------------------------------------------------------------------------

def _parse_hwp(path: Path, raw: bytes) -> ParseResult:
    """HWP(구형 바이너리) → pywin32로 한/글 COM 자동화하여 텍스트 추출 시도"""
    import platform
    if platform.system() != "Windows":
        return ParseResult(
            error="HWP 파싱은 Windows에서만 지원됩니다",
            format="hwp",
            raw_bytes=raw,
        )

    try:
        import win32com.client
    except ImportError:
        return ParseResult(
            error="pywin32 미설치 — pip install pywin32",
            format="hwp",
            raw_bytes=raw,
        )

    hwp = None
    try:
        hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        hwp.Open(str(path.resolve()), "HWP", "forceopen:true")

        # 전체 텍스트 추출
        hwp.InitScan()
        texts = []
        while True:
            state, text = hwp.GetText()
            if state <= 0:
                break
            if text.strip():
                texts.append(text.strip())
        hwp.ReleaseScan()

        full_text = "\n".join(texts)
        if not full_text.strip():
            return ParseResult(error="HWP 텍스트 추출 실패", format="hwp", raw_bytes=raw)

        return ParseResult(
            text=full_text,
            format="hwp",
            raw_bytes=raw,
            success=True,
        )

    except Exception as e:
        return ParseResult(
            error=f"HWP COM 자동화 실패: {e}",
            format="hwp",
            raw_bytes=raw,
        )
    finally:
        if hwp:
            try:
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _table_to_markdown(table: list) -> str:
    """2D 리스트 → 마크다운 테이블 문자열"""
    if not table:
        return ""

    # 열 수 통일 + None → 빈 문자열
    max_cols = max(len(row) for row in table)
    normalized = [
        [(cell or "").replace("\n", " ") for cell in row] + [""] * (max_cols - len(row))
        for row in table
    ]

    lines = []
    # 헤더
    header = normalized[0]
    lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    # 데이터
    for row in normalized[1:]:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")

    return "\n".join(lines)
