"""
Phase C-5 프로토타입 2 — 전체 섹션 extract + dedupe + JSON 저장 검증.

경과원 ESG HWP의 8개 타깃 섹션을 모두 Sonnet에 전달.
기대 비용: 5~8백원.

실행:
    cd C:/Users/user/Documents/lets_portal
    python tmp/test_extractor_proto2.py
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from extractors import ProposalAssetExtractor, ExtractionConfig, SourceMeta  # noqa
from extractors.proposal import _segment_text, extract_text  # noqa


def _progress(payload: dict):
    stage = payload.get("stage")
    if stage == "parse":
        print(f"  [parse] {payload['source']}")
    elif stage == "segment":
        print(f"  [segment] 전체 {payload['total_sections']} → 타깃 {payload['target_sections']}")
    elif stage == "extract_section":
        print(f"  [extract] ({payload['index']}/{payload['total']}) {payload['section']}")
    elif stage == "source_start":
        print(f"  [source] {payload['source']}")
    elif stage == "done":
        print(f"  [done] claims={payload['claims']}, cost={payload['cost_krw']}원")


def main():
    # 실제 HWP 파일 파싱 대신 캐시된 마크다운으로 세팅
    # → file_parser 우회를 위해 임시 방식: SourceMeta에 가짜 경로 넣고 segment만 직접 호출
    #   하지만 추출기는 내부적으로 extract_text(path)를 부르므로, 캐시가 아닌 실제 HWP를 파싱해야 함

    hwp_path = Path("C:/Users/user/OneDrive/바탕 화면/[대외비]제안서 샘플/제안서 샘플/샘플 8 _ 경과원 ESG 교육/제안서(사본).hwp")
    if not hwp_path.exists():
        print(f"ERROR: HWP 없음: {hwp_path}")
        return

    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: CLAUDE_API_KEY 없음")
        return

    cfg = ExtractionConfig()
    print(f"모델: {cfg.primary_model}")
    print(f"대상 파일: {hwp_path.name}")
    print()

    from ai.claude_client import ClaudeClient  # noqa
    client = ClaudeClient(api_key, model=cfg.primary_model)
    ex = ProposalAssetExtractor(client, cfg)

    source = SourceMeta(
        path=str(hwp_path),
        year=2023,
        awarded=True,
        proposal_title="2023 경기창업허브 스타트업 ESG 교육(비즈니스)",
        organization="경기도경제과학진흥원",
    )

    t0 = time.time()
    result = ex.extract([source], progress_cb=_progress)
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print(f"추출 완료 — {elapsed:.1f}초")
    print(f"  총 LLM 호출: {result.total_llm_calls}")
    print(f"  input tokens:  {result.total_input_tokens:,}")
    print(f"  output tokens: {result.total_output_tokens:,}")
    print(f"  총 비용: {result.total_cost_krw:.1f}원")
    print(f"  claims (dedupe 후): {len(result.claims)}")
    print(f"  quantitative_hints: {len(result.quantitative_hints)}")
    print(f"  warnings: {len(result.warnings)}")
    print()

    # 카테고리별 분포
    from collections import Counter
    cat_counts = Counter(c.category for c in result.claims)
    print("카테고리 분포:")
    for cat in cfg.categories:
        n = cat_counts.get(cat, 0)
        bar = "█" * n
        print(f"  {cat:12} {n:>2} {bar}")
    print()

    # recurrence > 1 (중복 병합된 것)
    merged = [c for c in result.claims if c.recurrence > 1]
    if merged:
        print(f"중복 병합 발견: {len(merged)}건")
        for c in merged:
            print(f"  [{c.category}] recurrence={c.recurrence}: {c.statement[:80]}")
        print()

    # JSON 저장
    out_path = ROOT / "tmp" / "extractor_proto2_output.json"
    out_path.write_text(ex.to_json(result), encoding="utf-8")
    print(f"JSON 저장: {out_path}")

    # 상위 5개 claim 프리뷰
    print()
    print("상위 5개 claim (confidence 내림차순):")
    top5 = sorted(result.claims, key=lambda c: c.confidence, reverse=True)[:5]
    for c in top5:
        print(f"  [{c.category:12}] conf={c.confidence:.2f} rec={c.recurrence}")
        print(f"    {c.statement}")
        print(f"    tags: {c.tags}")
        print()


if __name__ == "__main__":
    main()
