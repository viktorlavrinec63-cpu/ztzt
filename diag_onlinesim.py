
# diag_onlinesim.py
import os, sys, json, time
import requests

def main():
    if len(sys.argv) < 2:
        print("Usage: py diag_onlinesim.py YOUR_API_KEY [service] [country]")
        print("Example: py diag_onlinesim.py ABC123 bazos CZ")
        sys.exit(1)

    api_key = sys.argv[1]
    service = sys.argv[2] if len(sys.argv) > 2 else "bazos"
    country = (sys.argv[3] if len(sys.argv) > 3 else "CZ").upper()
    country_map = {"CZ":420,"SK":421,"PL":48,"DE":49}
    code = country_map.get(country, 420)

    sess = requests.Session()
    base = "https://onlinesim.io"

    def get(p, **params):
        params["apikey"] = api_key
        try:
            r = sess.get(base + p, params=params, timeout=30)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                import json as _json
                return _json.loads(r.text)
        except Exception as e:
            print(f"HTTP ERROR {p}: {e}")
            return {"error": str(e)}

    print(f"[1] getNum country={country} code={code} service={service!r}")
    resp = get("/api/getNum.php", country=code, service=service, lang="en")
    print(" ->", resp)

    tzid = None
    if isinstance(resp, dict):
        tzid = resp.get("tzid") or resp.get("Tzid") or resp.get("tz_id")
    if not tzid:
        print("No tzid from getNum -> probably wrong service or no slots/balance.")
        return

    print(f"[2] getState tzid={tzid}")
    t0 = time.time()
    last = None
    while time.time() - t0 < 30:
        st = get("/api/getState.php", tzid=tzid, lang="en")
        print("   state:", st)
        last = st
        # try to extract number
        it = st[0] if isinstance(st, list) and st else st
        num = (it.get("number") or it.get("tel")) if isinstance(it, dict) else None
        if num:
            print("   number =", num)
            break
        time.sleep(3)

    print(f"[3] finalize tzid={tzid}")
    fin = get("/api/setOperationOk.php", tzid=tzid, lang="en")
    print("   finalize:", fin)

if __name__ == "__main__":
    main()
