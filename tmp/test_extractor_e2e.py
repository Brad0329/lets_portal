"""
Phase C-5 E2E 테스트 — 실제 제안서 업로드 → 백그라운드 추출 → claim 조회 플로우.
사용: python tmp/test_extractor_e2e.py
"""
import json
import sys
import time
from pathlib import Path
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://localhost:8001"
SAMPLE = r"C:\Users\user\OneDrive\바탕 화면\[대외비]제안서 샘플\제안서 샘플\샘플 8 _ 경과원 ESG 교육\제안서(사본).hwp"


def check(cond, msg):
    if cond:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
        sys.exit(1)


def main():
    s = requests.Session()
    print("[1] 로그인")
    r = s.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin1234"})
    check(r.status_code == 200, f"login status={r.status_code} body={r.text[:200]}")

    print("[2] 업로드")
    file_path = Path(SAMPLE)
    check(file_path.exists(), f"샘플 존재: {file_path}")
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/octet-stream")}
        data = {
            "year": "2023",
            "awarded": "true",
            "organization": "경기도경제과학진흥원",
            "proposal_title": "2023 ESG 창업교육 (E2E 테스트)",
        }
        r = s.post(f"{BASE}/api/ai/extractor/upload", files=files, data=data)
    check(r.status_code == 200, f"upload status={r.status_code}")
    src = r.json()
    src_id = src["src_id"]
    db_id = src["id"]
    print(f"     src_id={src_id} db_id={db_id}")

    print("[3] 진행률 폴링 (최대 10분)")
    start = time.time()
    last_state = None
    while time.time() - start < 600:
        r = s.get(f"{BASE}/api/ai/extractor/sources/{src_id}")
        if r.status_code != 200:
            print(f"  polling error: {r.status_code}")
            time.sleep(5)
            continue
        state = r.json()
        status = state["status"]
        progress = state.get("progress", 0) or 0
        processed = state.get("processed_sections", 0) or 0
        total = state.get("total_sections", 0) or 0
        cost = state.get("cost_krw", 0) or 0
        current = state.get("current_section") or ""
        stamp = f"[{int(time.time() - start):3d}s] {status} {int(progress*100):3d}% {processed}/{total} {cost:.1f}원 {current[:40]}"
        if stamp != last_state:
            print(f"  {stamp}")
            last_state = stamp
        if status == "completed":
            break
        if status == "failed":
            print(f"  ❌ 실패: {state.get('error_message')}")
            sys.exit(1)
        time.sleep(5)
    else:
        print("  ❌ 타임아웃")
        sys.exit(1)

    elapsed = time.time() - start
    print(f"\n[4] 완료 — {elapsed:.1f}초")
    final = state
    print(f"     claims: {final.get('claim_count')}")
    print(f"     cost: {final.get('cost_krw')}원")
    print(f"     tokens: in={final.get('input_tokens')} out={final.get('output_tokens')}")
    check((final.get("claim_count") or 0) > 10, "claim이 10개 이상 추출됨")
    check((final.get("cost_krw") or 0) > 100, "비용 > 100원 (실제 API 호출됨)")

    print("\n[5] claims 조회")
    r = s.get(f"{BASE}/api/ai/extractor/claims", params={"verified": 0, "source_id": db_id})
    check(r.status_code == 200, f"claims status={r.status_code}")
    cdata = r.json()
    print(f"     미검토 claim: {len(cdata['claims'])}개")
    print(f"     카테고리 카운트: {json.dumps(cdata['counts'], ensure_ascii=False)}")
    check(len(cdata["claims"]) > 0, "미검토 claim 존재")

    # 첫 claim의 포맷 확인
    first = cdata["claims"][0]
    print(f"\n     예시 claim:")
    print(f"     [{first['category']}] \"{first['statement'][:70]}...\" (conf={first['confidence']})")
    check(first["category"] in ("Identity", "Methodology", "USP", "Philosophy", "Story", "Operational"),
          f"유효 카테고리: {first['category']}")
    check(isinstance(first["tags"], dict), "tags dict 형식")

    print("\n[6] claim 편집 (PATCH)")
    target_id = first["claim_id"]
    new_stmt = first["statement"] + " [E2E 편집]"
    r = s.patch(f"{BASE}/api/ai/extractor/claims/{target_id}",
                json={"statement": new_stmt})
    check(r.status_code == 200, f"patch status={r.status_code}")
    r = s.get(f"{BASE}/api/ai/extractor/claims", params={"source_id": db_id})
    edited = next((c for c in r.json()["claims"] if c["claim_id"] == target_id), None)
    check(edited and edited["statement"].endswith("[E2E 편집]"), "편집 statement 반영")
    check(edited["statement_original"] != edited["statement"], "원본 statement 보존")

    print("\n[7] 일괄 승인 (신뢰도 0.9+)")
    r = s.post(f"{BASE}/api/ai/extractor/claims/bulk-verify",
               json={"filter": {"min_confidence": 0.9, "source_id": db_id}, "user_verified": 1})
    check(r.status_code == 200, f"bulk-verify status={r.status_code}")
    approved_count = r.json().get("updated", 0)
    print(f"     승인: {approved_count}건")
    check(approved_count > 0, "1건 이상 승인됨")

    print("\n[8] 병합 제안 조회")
    r = s.get(f"{BASE}/api/ai/extractor/claims/merge-suggestions", params={"threshold": 0.6})
    check(r.status_code == 200, f"merge-suggestions status={r.status_code}")
    suggestions = r.json().get("suggestions", [])
    print(f"     병합 후보: {len(suggestions)}개 (threshold=0.6)")

    print("\n[9] 정량 힌트 조회")
    r = s.get(f"{BASE}/api/ai/extractor/quantitative-hints", params={"source_id": db_id})
    check(r.status_code == 200, f"hints status={r.status_code}")
    hints = r.json().get("hints", [])
    print(f"     힌트: {len(hints)}개")
    if hints:
        for h in hints[:3]:
            print(f"     · {h['type']} / {h['name'][:60]} / {h.get('year')}")

    print("\n[10] 정리 — 테스트 소스 삭제")
    r = s.delete(f"{BASE}/api/ai/extractor/sources/{src_id}")
    check(r.status_code == 200, f"delete status={r.status_code}")

    # 삭제 검증
    r = s.get(f"{BASE}/api/ai/extractor/sources/{src_id}")
    check(r.status_code == 404, "삭제 후 404")
    r = s.get(f"{BASE}/api/ai/extractor/claims", params={"source_id": db_id})
    leftover = len(r.json().get("claims", []))
    check(leftover == 0, f"관련 claim 모두 삭제됨 (남은: {leftover})")

    print(f"\n🎉 E2E 전체 통과 — {elapsed:.1f}초 · {final.get('claim_count')} claims · {final.get('cost_krw')}원")


if __name__ == "__main__":
    main()
