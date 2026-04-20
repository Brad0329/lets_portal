"""Prompt caching 효과 측정 — 업로드 1회 + 완료 대기 + 비용 로그."""
import json, sys, time, requests
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except: pass

BASE = "http://localhost:8001"
SAMPLE = r"C:\Users\user\OneDrive\바탕 화면\[대외비]제안서 샘플\제안서 샘플\샘플 8 _ 경과원 ESG 교육\제안서(사본).hwp"


def req(method, url, **kw):
    for i in range(5):
        try:
            hdr = kw.pop("headers", {}) or {}
            hdr.setdefault("Connection", "close")
            return requests.request(method, url, headers=hdr, **kw)
        except (requests.ConnectionError, requests.Timeout):
            if i == 4: raise
            time.sleep(2 ** i)


def main():
    cookies = req("POST", f"{BASE}/api/auth/login",
                  json={"username":"admin","password":"admin1234"}).cookies

    print("[업로드]")
    with open(SAMPLE, "rb") as f:
        r = req("POST", f"{BASE}/api/ai/extractor/upload",
                files={"file": (Path(SAMPLE).name, f, "application/octet-stream")},
                data={"year":"2023","awarded":"true","organization":"경기도경제과학진흥원",
                      "proposal_title":"2023 ESG (cache test)"},
                cookies=cookies)
    src = r.json()
    src_id = src["src_id"]
    print(f"  src_id={src_id}")

    print("[완료 대기]")
    start = time.time()
    while time.time() - start < 600:
        r = req("GET", f"{BASE}/api/ai/extractor/sources/{src_id}", cookies=cookies)
        s = r.json()
        print(f"  [{int(time.time()-start):3d}s] {s['status']:11s} {int((s.get('progress') or 0)*100):3d}% "
              f"{s['processed_sections']}/{s['total_sections']} {s['cost_krw']:.1f}원")
        if s["status"] == "completed":
            break
        if s["status"] == "failed":
            print(f"  ❌ {s.get('error_message')}"); sys.exit(1)
        time.sleep(8)

    elapsed = time.time() - start
    print(f"\n[결과] {elapsed:.1f}초 · claims={s['claim_count']} · {s['cost_krw']}원")
    print(f"       tokens: in={s['input_tokens']} out={s['output_tokens']}")
    print(f"       (캐시 쓰기/읽기 토큰은 서버 로그 확인 — logger.info)")


if __name__ == "__main__":
    main()
