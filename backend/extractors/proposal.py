"""
ProposalAssetExtractor — 제안서에서 회사 역량 claim을 추출.

파이프라인:
    파일 파싱 → 섹션 분할 → (섹션마다 LLM 호출) → 태그 정규화 → 중복 병합 → JSON

portable 의존성:
    - utils.file_parser (ParseResult, extract_text)
    - ai.base (BaseAIClient, AIResponse)
    - 이 패키지 내부 (base, prompts/)

사용 예:
    from ai.claude_client import ClaudeClient
    from extractors import ProposalAssetExtractor, ExtractionConfig, SourceMeta

    client = ClaudeClient(api_key, model="claude-sonnet-4-20250514")
    config = ExtractionConfig()
    ex = ProposalAssetExtractor(client, config)
    result = ex.extract([SourceMeta(path="x.hwp", year=2023, awarded=True)])
    print(ex.to_json(result))
"""

import hashlib
import json
import logging
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

from .base import (
    BaseExtractor,
    Claim,
    ExtractionConfig,
    ExtractionResult,
    MergeReport,
    Section,
    SourceMeta,
)

# portable 의존 — sibling 패키지 (utils/, ai/)
# bidwatch 이식 시에도 동일 구조 기대
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from utils.file_parser import extract_text, ParseResult  # noqa: E402
from ai.base import BaseAIClient, AIResponse  # noqa: E402

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


# ---------------------------------------------------------------------------
# 섹션 분할 — Python 규칙 기반 (결정적)
# ---------------------------------------------------------------------------

# 최상위: Ⅰ. 제안개요
_TOP_RE = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\.\s+(.+)$")

# 중간: 1 사업의 필요성 (한 자릿수 + 공백 + 한글 텍스트)
_MID_RE = re.compile(r"^([1-9])\s+([가-힣][가-힣\s·/]+)$")


def _segment_text(text: str) -> list:
    """제안서 마크다운 텍스트를 섹션 리스트로 분할.

    전략:
    1. 최상위(Ⅰ./Ⅱ./Ⅲ.) + 중간(1/2/3) 헤딩 라인 탐지
    2. 표(`|`로 시작) 라인은 헤딩 후보에서 제외
    3. 중간 섹션 단위로 버퍼링하여 Section 객체 생성
    """
    lines = text.split("\n")
    sections: list[Section] = []
    current_top: Optional[tuple] = None          # (roman, title)
    current_mid: Optional[tuple] = None          # (digit, title, start_line)
    buffer: list[str] = []

    def flush():
        nonlocal buffer, current_mid
        if current_mid and buffer:
            roman = current_top[0] if current_top else ""
            name = f"{roman}.{current_mid[0]} {current_mid[1]}".strip()
            sections.append(Section(
                name=name,
                text="\n".join(buffer).strip(),
                level=2,
                start_line=current_mid[2],
                end_line=len(sections),  # 임시, 아래서 덮어씀
            ))
        buffer = []
        current_mid = None

    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            if current_mid:
                buffer.append(raw)
            continue

        # 표 라인은 헤딩 후보에서 제외 (버퍼에만 추가)
        if stripped.startswith("|"):
            if current_mid:
                buffer.append(raw)
            continue

        m_top = _TOP_RE.match(stripped)
        m_mid = _MID_RE.match(stripped) if not m_top else None

        if m_top:
            flush()
            current_top = (m_top.group(1), m_top.group(2).strip())
            continue

        if m_mid:
            flush()
            current_mid = (m_mid.group(1), m_mid.group(2).strip(), i)
            continue

        # 일반 본문 — 현재 mid 섹션에 버퍼링
        if current_mid:
            buffer.append(raw)

    flush()

    # end_line 채우기
    for idx, s in enumerate(sections):
        if idx + 1 < len(sections):
            s.end_line = sections[idx + 1].start_line
        else:
            s.end_line = len(lines)

    return sections


# ---------------------------------------------------------------------------
# 정량 힌트 (Python 정규식)
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"(20\d{2})\s*년")
# 인증/등록 번호 패턴 — "제 2020-34호", "제2105**-01***호" 등 구체 증거만 (문맥 노이즈 배제)
_CERT_NUMBER_RE = re.compile(r"제\s*[\w\d*\-]+\s*호")
_CERT_CONTEXT_KEYWORDS = ("인증", "등록", "확인서", "Main-Biz", "메인비즈", "벤처기업")


def _detect_quantitative_hints(text: str, src_id: str) -> list:
    """Python 정규식 기반 정량 후보 — LLM 보완용.

    의도적으로 보수적: 번호 패턴(제XXX호)이 있는 인증/등록만 뽑는다.
    문맥 오탐(사업자 등록 여부 등)을 피하기 위해 키워드 단독 매칭은 하지 않는다.
    """
    hints = []
    seen = set()

    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 250 or line.startswith("|"):
            continue
        if not _CERT_NUMBER_RE.search(line):
            continue
        if not any(kw in line for kw in _CERT_CONTEXT_KEYWORDS):
            continue
        key = line[:100]
        if key in seen:
            continue
        seen.add(key)
        y = _YEAR_RE.search(line)
        hints.append({
            "type": "인증/등록",
            "name": line[:120],
            "year": int(y.group(1)) if y else None,
            "source_id": src_id,
            "extractor": "regex",
        })
        if len(hints) >= 20:
            break
    return hints


# ---------------------------------------------------------------------------
# 태그 정규화 — 통제 어휘 매핑
# ---------------------------------------------------------------------------

def _normalize_tags(claim_tags: dict, vocab: dict) -> dict:
    """LLM이 반환한 태그를 통제 어휘에 맞게 필터링 + 치환."""
    out = {"domain": [], "audience": [], "method": []}
    for key in out:
        raw_values = claim_tags.get(key) or []
        if not isinstance(raw_values, list):
            continue
        allowed = set(vocab.get(key, []))
        for v in raw_values:
            if not isinstance(v, str):
                continue
            v = v.strip()
            if not v:
                continue
            # 정확 매칭
            if v in allowed:
                out[key].append(v)
                continue
            # 부분 매칭 (양방향 포함)
            hit = None
            for a in allowed:
                if a in v or v in a:
                    hit = a
                    break
            if hit:
                out[key].append(hit)
    # 중복 제거
    for k in out:
        out[k] = list(dict.fromkeys(out[k]))
    return out


# ---------------------------------------------------------------------------
# 중복 병합 (fuzzy)
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _dedupe_claims(claims: list, threshold: float) -> list:
    """같은 카테고리 내 statement 유사도 기준으로 병합."""
    if not claims:
        return []

    out: list[Claim] = []
    for c in claims:
        merged = False
        for existing in out:
            if existing.category != c.category:
                continue
            if _similarity(existing.statement, c.statement) >= threshold:
                # 병합 — recurrence++, 더 긴 statement 유지, 태그/섹션 합침
                existing.recurrence += 1
                if len(c.statement) > len(existing.statement):
                    existing.statement = c.statement
                for k in ("domain", "audience", "method"):
                    merged_list = list(dict.fromkeys(
                        existing.tags.get(k, []) + c.tags.get(k, [])
                    ))
                    existing.tags[k] = merged_list
                existing.proposal_sections = list(dict.fromkeys(
                    existing.proposal_sections + c.proposal_sections
                ))
                # length_variants는 존재하지 않는 키만 추가
                for lk, lv in (c.length_variants or {}).items():
                    if lk not in existing.length_variants and lv:
                        existing.length_variants[lk] = lv
                existing.confidence = max(existing.confidence, c.confidence)
                merged = True
                break
        if not merged:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# JSON 파싱 유틸
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 추출 (```json 블록 or 범위 추출)."""
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("JSON 파싱 실패: %s", text[:200])
    return {}


def _claim_id(statement: str, src_id: str) -> str:
    h = hashlib.md5(f"{src_id}:{statement}".encode("utf-8")).hexdigest()[:8]
    return f"cl_{h}"


def _cost_krw(model: str, in_tok: int, out_tok: int, pricing: dict, rate: float,
              cache_write_tok: int = 0, cache_read_tok: int = 0) -> float:
    """모델별 단가 + 환율로 원화 환산.

    cache_write_tok: 캐시 쓰기 토큰 — 통상 input×1.25 가격
    cache_read_tok: 캐시 읽기 토큰 — 통상 input×0.1 가격
    """
    price = pricing.get(model)
    if not price:
        for k, v in pricing.items():
            if ("haiku" in k and "haiku" in model) or ("sonnet" in k and "sonnet" in model):
                price = v
                break
    if not price:
        return 0.0
    # 캐시 단가 (pricing에 명시 없으면 Anthropic 기본 배율 적용)
    cache_write_price = price.get("cache_write", price["input"] * 1.25)
    cache_read_price = price.get("cache_read", price["input"] * 0.1)
    usd = (
        (in_tok / 1_000_000) * price["input"]
        + (out_tok / 1_000_000) * price["output"]
        + (cache_write_tok / 1_000_000) * cache_write_price
        + (cache_read_tok / 1_000_000) * cache_read_price
    )
    return round(usd * rate, 1)


# ---------------------------------------------------------------------------
# ProposalAssetExtractor
# ---------------------------------------------------------------------------

class ProposalAssetExtractor(BaseExtractor):
    """제안서 → claim 추출기."""

    def __init__(self, ai_client: BaseAIClient, config: Optional[ExtractionConfig] = None):
        self.ai = ai_client
        self.cfg = config or ExtractionConfig()
        self._system_template, self._user_template = self._load_prompts()

    # -------- 공개 API --------

    def extract(
        self,
        sources: list,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> ExtractionResult:
        """여러 소스 일괄 추출."""
        result = ExtractionResult(model=self.cfg.primary_model)
        for i, src in enumerate(sources):
            if not src.src_id:
                src.src_id = f"src_{i+1:02d}"
            result.sources.append(src)

            self._emit(progress_cb, {"stage": "source_start", "source": src.path, "index": i + 1, "total": len(sources)})
            try:
                claims, hints, tok_in, tok_out, tok_cw, tok_cr, calls = self._process_single(src, progress_cb)
                result.claims.extend(claims)
                result.quantitative_hints.extend(hints)
                result.total_input_tokens += tok_in
                result.total_output_tokens += tok_out
                result.total_cache_creation_tokens += tok_cw
                result.total_cache_read_tokens += tok_cr
                result.total_llm_calls += calls
            except Exception as e:
                logger.exception("source 처리 실패: %s", src.path)
                result.warnings.append({"type": "source_error", "source": src.path, "message": str(e)})

        # 중복 병합
        result.claims = _dedupe_claims(result.claims, self.cfg.dedupe_similarity)

        # claim id 부여 (병합 후 확정)
        for c in result.claims:
            if not c.id:
                c.id = _claim_id(c.statement, c.source.get("src_id", ""))

        # 비용 산출 (캐시 쓰기/읽기 토큰 포함)
        result.total_cost_krw = _cost_krw(
            self.cfg.primary_model,
            result.total_input_tokens,
            result.total_output_tokens,
            self.cfg.pricing,
            self.cfg.exchange_rate,
            cache_write_tok=result.total_cache_creation_tokens,
            cache_read_tok=result.total_cache_read_tokens,
        )

        self._emit(progress_cb, {
            "stage": "done",
            "claims": len(result.claims),
            "cost_krw": result.total_cost_krw,
            "cache_read": result.total_cache_read_tokens,
            "cache_write": result.total_cache_creation_tokens,
        })
        return result

    def extract_single(
        self,
        source: SourceMeta,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> list:
        """단일 소스 — Claim 리스트만 반환."""
        if not source.src_id:
            source.src_id = "src_01"
        claims, _hints, _ti, _to, _cw, _cr, _n = self._process_single(source, progress_cb)
        return _dedupe_claims(claims, self.cfg.dedupe_similarity)

    def to_json(self, result: ExtractionResult) -> str:
        """ExtractionResult → JSON 문자열 (자기서술적)."""
        payload = {
            "meta": {
                "model": result.model,
                "total_cost_krw": result.total_cost_krw,
                "total_llm_calls": result.total_llm_calls,
                "total_input_tokens": result.total_input_tokens,
                "total_output_tokens": result.total_output_tokens,
                "total_cache_creation_tokens": result.total_cache_creation_tokens,
                "total_cache_read_tokens": result.total_cache_read_tokens,
                "prompt_cache_enabled": self.cfg.use_prompt_cache,
            },
            "sources": [
                {
                    "src_id": s.src_id,
                    "path": s.path,
                    "year": s.year,
                    "awarded": s.awarded,
                    "proposal_title": s.proposal_title,
                    "organization": s.organization,
                }
                for s in result.sources
            ],
            "claims": [self._claim_to_dict(c) for c in result.claims],
            "quantitative_hints": result.quantitative_hints,
            "warnings": result.warnings,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # -------- 내부 파이프라인 (테스트/디버그용 공개) --------

    def segment(self, text: str) -> list:
        """섹션 분할 — 테스트 용이하도록 공개."""
        return _segment_text(text)

    def is_skip_section(self, name: str) -> bool:
        """이 섹션을 스킵해야 하는지 판정."""
        for kw in self.cfg.skip_section_keywords:
            if kw in name:
                return True
        return False

    # -------- 내부 --------

    def _load_prompts(self):
        """system(고정, 캐시 대상) + user(가변) 프롬프트 로드.

        하위 호환: 신규 파일이 없으면 기존 통합 파일(`extract_proposal_claims.md`)
        을 system으로, user는 빈 문자열로 폴백.
        """
        sys_p = _PROMPT_DIR / "extract_proposal_claims_system.md"
        usr_p = _PROMPT_DIR / "extract_proposal_claims_user.md"
        legacy_p = _PROMPT_DIR / "extract_proposal_claims.md"

        if sys_p.exists() and usr_p.exists():
            return sys_p.read_text(encoding="utf-8"), usr_p.read_text(encoding="utf-8")
        if legacy_p.exists():
            logger.warning("system/user 분리 파일 없음 — legacy 통합 파일 사용 (prompt caching 비활성)")
            return legacy_p.read_text(encoding="utf-8"), ""
        raise FileNotFoundError(f"프롬프트 파일 없음: {sys_p}")

    def _build_system(self) -> str:
        """고정 프롬프트 — 태그 어휘만 치환 (섹션·소스별로 변하지 않음)."""
        vocab = self.cfg.tag_vocabulary
        filled = self._system_template
        for k, v in {
            "{domain_vocab}": ", ".join(vocab.get("domain", [])),
            "{audience_vocab}": ", ".join(vocab.get("audience", [])),
            "{method_vocab}": ", ".join(vocab.get("method", [])),
        }.items():
            filled = filled.replace(k, v)
        return filled

    def _build_user(self, section: Section, source: SourceMeta) -> str:
        """가변 프롬프트 — 섹션 메타 치환."""
        filled = self._user_template
        for k, v in {
            "{proposal_title}": source.proposal_title or Path(source.path).stem,
            "{section_name}": section.name,
            "{organization}": source.organization or "(정보 없음)",
            "{year}": str(source.year) if source.year else "(정보 없음)",
            "{awarded}": "수주" if source.awarded is True else ("탈락" if source.awarded is False else "모름"),
        }.items():
            filled = filled.replace(k, v)
        return filled

    def _process_single(self, source: SourceMeta, progress_cb):
        """단일 파일 파싱 → 섹션 분할 → 섹션별 LLM → claims+hints."""
        self._emit(progress_cb, {"stage": "parse", "source": source.path})
        parsed: ParseResult = extract_text(source.path)
        if not parsed.success:
            raise RuntimeError(f"파싱 실패: {parsed.error}")

        sections = _segment_text(parsed.text)
        target_sections = [s for s in sections if not self.is_skip_section(s.name)]

        self._emit(progress_cb, {
            "stage": "segment",
            "source": source.path,
            "total_sections": len(sections),
            "target_sections": len(target_sections),
        })

        claims: list[Claim] = []
        hints: list = _detect_quantitative_hints(parsed.text, source.src_id)
        total_in = total_out = total_cw = total_cr = calls = 0

        # system 프롬프트는 소스·섹션 전체에서 불변 → 한 번만 생성
        system_prompt = self._build_system()

        for i, sec in enumerate(target_sections):
            self._emit(progress_cb, {
                "stage": "extract_section",
                "source": source.path,
                "section": sec.name,
                "index": i + 1,
                "total": len(target_sections),
            })
            sec_claims, sec_hints, tok_in, tok_out, tok_cw, tok_cr, ok = self._extract_section(
                sec, source, system_prompt
            )
            if ok:
                claims.extend(sec_claims)
                hints.extend(sec_hints)
                total_in += tok_in
                total_out += tok_out
                total_cw += tok_cw
                total_cr += tok_cr
                calls += 1
            else:
                logger.warning("섹션 추출 실패: %s", sec.name)

        return claims, hints, total_in, total_out, total_cw, total_cr, calls

    def _extract_section(self, section: Section, source: SourceMeta, system_prompt: str):
        """한 섹션 LLM 호출 → (claims, hints, in_tok, out_tok, cache_write, cache_read, ok)."""
        user_prompt = self._build_user(section, source)
        response: AIResponse = self.ai.analyze_document(
            section.text, user_prompt,
            system=system_prompt,
            use_cache=self.cfg.use_prompt_cache,
        )
        if not response.success:
            logger.warning("LLM 호출 실패 (%s): %s", section.name, response.error)
            return [], [], 0, 0, 0, 0, False

        parsed = _extract_json(response.content)
        raw_claims = parsed.get("claims") or []
        out: list[Claim] = []
        for rc in raw_claims:
            if not isinstance(rc, dict):
                continue
            stmt = (rc.get("statement") or "").strip()
            if not stmt:
                continue
            conf = float(rc.get("confidence", 0.8) or 0.8)
            if conf < self.cfg.min_confidence:
                continue
            cat = rc.get("category", "")
            if cat not in self.cfg.categories:
                continue
            c = Claim(
                category=cat,
                statement=stmt,
                tags=_normalize_tags(rc.get("tags") or {}, self.cfg.tag_vocabulary),
                proposal_sections=list(rc.get("proposal_sections") or []),
                length_variants=dict(rc.get("length_variants") or {}),
                confidence=conf,
                source={
                    "src_id": source.src_id,
                    "section": section.name,
                    "section_start_line": section.start_line,
                },
                recurrence=1,
            )
            out.append(c)

        # 섹션당 최대 claim 수 제한
        if len(out) > self.cfg.max_claims_per_section:
            out = sorted(out, key=lambda c: c.confidence, reverse=True)[:self.cfg.max_claims_per_section]

        # LLM이 반환한 quantitative_hints도 수집
        llm_hints = []
        for h in parsed.get("quantitative_hints") or []:
            if not isinstance(h, dict):
                continue
            llm_hints.append({
                **h,
                "source_id": source.src_id,
                "section": section.name,
                "extractor": "llm",
            })

        return (
            out,
            llm_hints,
            response.input_tokens,
            response.output_tokens,
            response.cache_creation_input_tokens,
            response.cache_read_input_tokens,
            True,
        )

    def _claim_to_dict(self, c: Claim) -> dict:
        return {
            "id": c.id,
            "category": c.category,
            "statement": c.statement,
            "tags": c.tags,
            "proposal_sections": c.proposal_sections,
            "length_variants": c.length_variants,
            "evidence_refs": c.evidence_refs,
            "source": c.source,
            "recurrence": c.recurrence,
            "confidence": c.confidence,
            "user_verified": c.user_verified,
        }

    def _emit(self, cb, payload: dict):
        if cb:
            try:
                cb(payload)
            except Exception:
                logger.exception("progress_cb 실패")
