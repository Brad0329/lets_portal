"""
Phase C-5 프로토타입 1 — ProposalAssetExtractor 검증.

단계:
    (1) 캐시된 파싱 결과(tmp/hwp_parsed.md)로 섹션 분할 검증
    (2) 섹션 스킵 규칙 확인
    (3) 1개 섹션(Ⅲ.1 업체 현황)을 LLM에 전달 → JSON claim 추출 검증
    (4) 결과 출력

실행:
    cd C:/Users/user/Documents/lets_portal
    python tmp/test_extractor_proto1.py [full]
        - 'full' 인자 주면 LLM 호출까지 실행 (~70원)
        - 미지정 시 분할 검증까지만
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from extractors import ProposalAssetExtractor, ExtractionConfig, SourceMeta  # noqa
from extractors.proposal import _segment_text  # noqa


def main():
    run_llm = len(sys.argv) > 1 and sys.argv[1] == "full"

    # (1) 캐시된 파싱 결과 로드
    cache = ROOT / "tmp" / "hwp_parsed.md"
    text = cache.read_text(encoding="utf-8")
    print(f"[1] 캐시 로드: {len(text):,}자, {len(text.splitlines()):,}줄")

    # (2) 섹션 분할
    sections = _segment_text(text)
    print(f"\n[2] 섹션 분할 결과: {len(sections)}개")
    for s in sections:
        print(f"    - {s.name:30} ({len(s.text):>6,}자, line {s.start_line:>4}~{s.end_line})")

    # (3) 스킵 필터
    cfg = ExtractionConfig()
    from extractors.proposal import ProposalAssetExtractor as _Ex
    # AI client 주입 없이 is_skip_section만 테스트하려고 더미 사용
    class _Dummy:
        def analyze_document(self, t, p): pass
    ex = ProposalAssetExtractor(_Dummy(), cfg)
    target = [s for s in sections if not ex.is_skip_section(s.name)]
    skipped = [s.name for s in sections if ex.is_skip_section(s.name)]
    print(f"\n[3] 스킵 적용: 전체 {len(sections)} → 타깃 {len(target)}")
    print(f"    스킵: {skipped}")
    print(f"    타깃: {[s.name for s in target]}")

    if not run_llm:
        print("\n(LLM 호출 없이 종료. 'python tmp/test_extractor_proto1.py full' 로 LLM 테스트)")
        return

    # (4) LLM 호출 — 1개 섹션 (Ⅲ.1 업체 현황 우선, 없으면 첫 타깃)
    pick = next((s for s in target if "업체 현황" in s.name), target[0] if target else None)
    if not pick:
        print("타깃 섹션 없음 — 종료")
        return
    print(f"\n[4] LLM 추출 대상: '{pick.name}' ({len(pick.text):,}자)")

    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: CLAUDE_API_KEY 없음")
        return

    from ai.claude_client import ClaudeClient  # noqa
    client = ClaudeClient(api_key, model=cfg.primary_model)
    real_ex = ProposalAssetExtractor(client, cfg)

    source = SourceMeta(
        path=str(ROOT / "tmp" / "hwp_parsed.md"),
        year=2023,
        awarded=True,
        proposal_title="2023 경기창업허브 스타트업 ESG 교육(비즈니스)",
        organization="경기도경제과학진흥원",
        src_id="src_01",
    )

    claims, hints, tok_in, tok_out, ok = real_ex._extract_section(pick, source)
    if not ok:
        print("LLM 호출 실패")
        return

    print(f"\n[5] LLM 응답:")
    print(f"    input_tokens={tok_in}, output_tokens={tok_out}")
    from extractors.proposal import _cost_krw
    cost = _cost_krw(cfg.primary_model, tok_in, tok_out, cfg.pricing, cfg.exchange_rate)
    print(f"    비용: {cost:.1f}원")
    print(f"    추출 claim: {len(claims)}개")
    print(f"    LLM quantitative_hints: {len(hints)}개")
    for h in hints[:5]:
        print(f"      - {h}")

    print("\n[6] claims JSON:")
    claims_json = [real_ex._claim_to_dict(c) for c in claims]
    print(json.dumps(claims_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
