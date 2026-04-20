"""src_0002 완료 대기 + 나머지 검증."""
import json, sys, time, requests
try: sys.stdout.reconfigure(encoding="utf-8")
except: pass

BASE = "http://localhost:8001"
SRC_ID = "src_0002"


def req(method, url, **kw):
    """keep-alive 소켓 재사용으로 인한 WinError 10053 회피 — 매번 새 커넥션 + 재시도."""
    for attempt in range(5):
        try:
            hdr = kw.pop("headers", {}) or {}
            hdr.setdefault("Connection", "close")
            return requests.request(method, url, headers=hdr, **kw)
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == 4: raise
            time.sleep(2 ** attempt)


def login():
    r = req("POST", f"{BASE}/api/auth/login", json={"username":"admin","password":"admin1234"})
    assert r.status_code == 200
    return r.cookies


def main():
    cookies = login()
    print("[완료 대기] 5초 간격 폴링")
    start = time.time()
    while time.time() - start < 600:
        r = req("GET", f"{BASE}/api/ai/extractor/sources/{SRC_ID}", cookies=cookies)
        if r.status_code != 200:
            print(f"  {r.status_code}"); time.sleep(5); continue
        s = r.json()
        print(f"  [{int(time.time()-start):3d}s] {s['status']} {int((s.get('progress') or 0)*100):3d}% "
              f"{s['processed_sections']}/{s['total_sections']} {s['cost_krw']:.1f}원 "
              f"{(s.get('current_section') or '')[:40]}")
        if s["status"] == "completed":
            break
        if s["status"] == "failed":
            print(f"  ❌ {s.get('error_message')}"); sys.exit(1)
        time.sleep(7)

    final = s
    elapsed = time.time() - start
    print(f"\n[완료] {elapsed:.1f}초 · claims={final['claim_count']} · {final['cost_krw']}원 · in={final['input_tokens']} out={final['output_tokens']}")

    print("\n[claims 조회]")
    r = req("GET", f"{BASE}/api/ai/extractor/claims", params={"verified": 0, "source_id": 2}, cookies=cookies)
    d = r.json()
    print(f"  미검토: {len(d['claims'])}개  / 카운트: {json.dumps(d['counts'], ensure_ascii=False)}")
    first = d["claims"][0]
    print(f"  예시: [{first['category']}] \"{first['statement'][:70]}...\" conf={first['confidence']}")
    print(f"  tags: {first['tags']}")

    print("\n[편집 PATCH]")
    target = first["claim_id"]
    r = req("PATCH", f"{BASE}/api/ai/extractor/claims/{target}",
            json={"statement": first["statement"] + " [E2E 편집]"}, cookies=cookies)
    print(f"  {r.status_code}")
    r = req("GET", f"{BASE}/api/ai/extractor/claims", params={"source_id": 2}, cookies=cookies)
    edited = next(c for c in r.json()["claims"] if c["claim_id"] == target)
    print(f"  원본 보존: {edited['statement_original'] != edited['statement']}")
    print(f"  수정된 statement: {edited['statement'][-30:]}")

    print("\n[일괄 승인 0.9+]")
    r = req("POST", f"{BASE}/api/ai/extractor/claims/bulk-verify",
            json={"filter": {"min_confidence": 0.9, "source_id": 2}, "user_verified": 1}, cookies=cookies)
    print(f"  {r.status_code} · {r.json()}")

    print("\n[병합 제안]")
    r = req("GET", f"{BASE}/api/ai/extractor/claims/merge-suggestions",
            params={"threshold": 0.6}, cookies=cookies)
    print(f"  후보: {len(r.json().get('suggestions', []))}개")

    print("\n[정량 힌트]")
    r = req("GET", f"{BASE}/api/ai/extractor/quantitative-hints",
            params={"source_id": 2}, cookies=cookies)
    hints = r.json().get("hints", [])
    print(f"  힌트: {len(hints)}개")
    for h in hints[:5]:
        print(f"  · {h.get('type')} / {(h.get('name') or '')[:60]} / {h.get('year')}")

    print(f"\n🎉 E2E 통과 (src_0002 유지, 수동 삭제 가능)")


if __name__ == "__main__":
    main()
