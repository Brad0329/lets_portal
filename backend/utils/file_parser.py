"""
문서 파싱 모듈 — 독립 패키지(lets_doc_parser)로 분리 가능하도록 설계

지원 포맷:
    - PDF  : pdfplumber
    - HWPX : lxml (XML 직접 파싱)
    - DOCX : python-docx
    - HWP  : pyhwp (1차, 한/글 불필요) → 한/글 COM 자동화 (2차, 한/글 설치 시)

공개 인터페이스:
    from utils.file_parser import extract_text, ParseResult
    result = extract_text("제안요청서.pdf")
    if result.success:
        print(result.text)

이식 가이드 (bidwatch 등):
    1) 이 파일 하나만 복사
    2) 의존성 설치:
       pdfplumber, lxml, python-docx, pyhwp, beautifulsoup4
       (선택) pywin32 — Windows + 한/글 설치 시 HWP 품질 향상
    3) 프로젝트 특정 모듈 import 없음 — 바로 동작

설계 원칙:
    - 파일 경로만 받고 ParseResult만 반환 (프레임워크/DB 무관)
    - 선택 의존성은 import 시점에 로드 (pywin32 미설치 환경 대응)
    - 파싱 실패 시 예외가 아닌 ParseResult(success=False, error=...)로 반환
"""

from dataclasses import dataclass, field
from pathlib import Path
import logging

__all__ = ["extract_text", "ParseResult"]

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
        return parser(p, raw)
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
# HWP(구형) 파서 — pyhwp(1차) → 한/글 COM(2차 폴백)
# ---------------------------------------------------------------------------

def _parse_hwp(path: Path, raw: bytes) -> ParseResult:
    """HWP 구형 바이너리 파싱.

    전략:
      1차: pyhwp — hwp5html(XSLT)로 XHTML 추출 후 BeautifulSoup로 마크다운 변환
           한/글 프로그램 불필요, 모든 OS에서 동작, 표 내용까지 추출
      2차 폴백: pywin32 COM 자동화 — 한/글 설치 환경에서만 동작, 품질 최상
    """
    # 1차: pyhwp 시도
    result = _parse_hwp_pyhwp(path, raw)
    if result.success:
        return result
    pyhwp_error = result.error

    # 2차: COM 폴백
    com_result = _parse_hwp_com(path, raw)
    if com_result.success:
        return com_result

    # 둘 다 실패
    return ParseResult(
        error=f"HWP 파싱 실패 — pyhwp: {pyhwp_error} | COM: {com_result.error}",
        format="hwp",
        raw_bytes=raw,
    )


def _parse_hwp_pyhwp(path: Path, raw: bytes) -> ParseResult:
    """pyhwp로 HWP → XHTML 변환 후 마크다운 추출 (한/글 설치 불필요)"""
    try:
        from hwp5.hwp5html import HTMLTransform
        from hwp5.xmlmodel import Hwp5File
    except ImportError as e:
        return ParseResult(error=f"pyhwp 미설치: {e}", format="hwp", raw_bytes=raw)

    import tempfile

    try:
        transform = HTMLTransform()
        hwp5file = Hwp5File(str(path))
        with tempfile.TemporaryDirectory() as tmpdir:
            transform.transform_hwp5_to_dir(hwp5file, tmpdir)
            html_path = Path(tmpdir) / "index.xhtml"
            if not html_path.exists():
                return ParseResult(error="pyhwp 출력 파일 없음", format="hwp", raw_bytes=raw)
            html = html_path.read_text(encoding="utf-8")

        text = _xhtml_to_markdown(html)
        if not text.strip():
            return ParseResult(error="pyhwp 텍스트 추출 실패 (빈 문서)", format="hwp", raw_bytes=raw)

        return ParseResult(
            text=text,
            format="hwp",
            raw_bytes=raw,
            success=True,
        )
    except Exception as e:
        return ParseResult(error=f"pyhwp 파싱 실패: {e}", format="hwp", raw_bytes=raw)


def _parse_hwp_com(path: Path, raw: bytes) -> ParseResult:
    """pywin32로 한/글 COM 자동화하여 텍스트 추출 (한/글 설치 환경 전용)"""
    import platform
    if platform.system() != "Windows":
        return ParseResult(error="COM 폴백은 Windows + 한/글 설치 환경에서만 동작", format="hwp", raw_bytes=raw)

    try:
        import win32com.client
    except ImportError:
        return ParseResult(error="pywin32 미설치", format="hwp", raw_bytes=raw)

    hwp = None
    try:
        hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        hwp.Open(str(path.resolve()), "HWP", "forceopen:true")

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
            return ParseResult(error="COM 텍스트 추출 실패", format="hwp", raw_bytes=raw)

        return ParseResult(
            text=full_text,
            format="hwp",
            raw_bytes=raw,
            success=True,
        )
    except Exception as e:
        return ParseResult(error=f"COM 자동화 실패: {e}", format="hwp", raw_bytes=raw)
    finally:
        if hwp:
            try:
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# XHTML → 마크다운 변환 (HWP/향후 DOCX HTML 변환 등에 공용)
# ---------------------------------------------------------------------------

def _xhtml_to_markdown(html: str) -> str:
    """XHTML 문자열을 마크다운 텍스트로 변환.

    - <p>: 단락 텍스트
    - <table>: 마크다운 테이블 (중첩 표는 셀 내부 텍스트로 flatten)
    - 표 안의 <p>는 표 셀이 흡수하므로 최상위 레벨에서 중복되지 않도록 스킵
    """
    import warnings
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body is None:
        return ""

    parts = []
    # 상위 표가 이미 처리한 자식 요소는 스킵
    processed = set()

    for elem in body.find_all(["p", "table"]):
        # 다른 table/p의 하위면 스킵 (상위 요소가 처리)
        if any(id(ancestor) in processed for ancestor in elem.parents):
            continue

        if elem.name == "table":
            md = _html_table_to_markdown(elem)
            if md:
                parts.append(md)
            # 이 표의 모든 하위 요소를 처리됨으로 마킹
            processed.add(id(elem))
            for descendant in elem.descendants:
                if hasattr(descendant, "name"):
                    processed.add(id(descendant))
        elif elem.name == "p":
            text = elem.get_text(separator=" ", strip=True)
            if text:
                parts.append(text)

    return "\n\n".join(parts)


def _html_table_to_markdown(table_elem) -> str:
    """BeautifulSoup <table> 요소를 마크다운 표 문자열로 변환.

    중첩 표 처리: 셀 내부의 텍스트만 flatten하여 추출 (중첩 table 자체는 무시).
    """
    rows = []
    for tr in table_elem.find_all("tr", recursive=True):
        # 이 tr이 우리 표의 직접 자식인지 확인 (중첩 table의 tr 제외)
        # tr의 가장 가까운 table 조상이 현재 table_elem과 같아야 함
        closest_table = tr.find_parent("table")
        if closest_table is not table_elem:
            continue

        cells = []
        for cell in tr.find_all(["td", "th"], recursive=False):
            text = cell.get_text(separator=" ", strip=True).replace("|", "\\|")
            cells.append(text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # 열 수 정규화
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    lines = []
    lines.append("| " + " | ".join(normalized[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


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
