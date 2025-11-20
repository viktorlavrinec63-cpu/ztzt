
# main.py — start SK only after CZ success & cookie saved; wait delay
from __future__ import annotations
import os, json, time, argparse
from typing import Optional, Tuple, List, Dict
from sms_providers import ManualSmsProvider, ProviderA, ProviderB, GenericSmsProvider, SmsProviderBase, OnlineSimProvider
from bazos_bot import run_country_flow
from proxy_utils import parse_proxy_line, derive_country_from_proxy

def load_config(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_provider(cfg: dict) -> SmsProviderBase:
    on = cfg.get("onlinesim", {})
    provider_name = (cfg.get("sms_provider") or "onlinesim").lower()
    if provider_name in ("onlinesim","online-sim","online_sim"):
        return OnlineSimProvider(
            api_key=on.get("api_key",""),
            base_url=on.get("base_url","https://onlinesim.io"),
            service=on.get("service","bazos"),
            country_map=on.get("country_map", {"CZ":420,"SK":421,"PL":48,"DE":49}),
            poll_interval_sec=int(on.get("poll_interval_sec",5)),
        )
    elif provider_name == "manual":
        return ManualSmsProvider()
    elif provider_name == "providera":
        return ProviderA(api_key=cfg.get("providerA",{}).get("api_key",""), base_url=cfg.get("providerA",{}).get("base_url",""))
    elif provider_name == "providerb":
        return ProviderB(api_key=cfg.get("providerB",{}).get("api_key",""), base_url=cfg.get("providerB",{}).get("base_url",""))
    else:
        return GenericSmsProvider()

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []

def decide_domain_country(cfg: dict, proxy_info: Dict[str,str]) -> str:
    on = cfg.get("onlinesim", {})
    mode = (on.get("activation_country_mode") or "manual").lower()
    if mode == "manual":
        cc = (on.get("activation_country") or "CZ").upper()
    else:
        cc = (derive_country_from_proxy(proxy_info) or on.get("activation_country") or "CZ").upper()
    return "CZ" if cc not in ("CZ","SK") else cc

def decide_sms_country(cfg: dict, domain_cc: str) -> str:
    on = cfg.get("onlinesim", {})
    mode = (on.get("sms_number_country_mode") or "manual").lower()
    if mode == "manual":
        cc = (on.get("sms_number_country") or domain_cc).upper()
    else:
        cc = domain_cc.upper()
    return cc if cc in ("CZ","SK","PL","DE") else domain_cc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--proxies", default="proxies.txt")
    ap.add_argument("--profiles", default="profiles.json")
    args = ap.parse_args()

    cfg = load_config(args.config)
    proxies_raw = read_lines(args.proxies)
    provider = get_provider(cfg)

    runs = max(1, int(args.runs))
    delay_between = int(cfg.get("delay_between_countries_sec", 60))

    for i in range(1, runs+1):
        raw = proxies_raw[i-1] if i-1 < len(proxies_raw) else ""
        proxy_info = parse_proxy_line(raw) if raw else {}
        proxy_for_pw = None
        if proxy_info:
            proxy_for_pw = {"server": proxy_info["server"]}
            if proxy_info.get("username"):
                proxy_for_pw["username"] = proxy_info["username"]
            if proxy_info.get("password"):
                proxy_for_pw["password"] = proxy_info["password"]

        domain_cc = decide_domain_country(cfg, proxy_info)   # CZ or SK (defines site & cookie folder)
        sms_cc = decide_sms_country(cfg, domain_cc)          # PL/CZ/SK/DE — number source only
        pair_cc = "SK" if domain_cc == "CZ" else ("CZ" if domain_cc == "SK" else None)

        print(f"\n=== Цикл {i} | proxy: {proxy_info.get('server','NONE')} | domain={domain_cc} | sms={sms_cc} ===")

        # 1) Buy number (sms_cc) and run FIRST country (domain_cc)
        act_id, phone = provider.request_number(sms_cc)
        print(f"[SMS {sms_cc}] Номер: {phone} (act_id={act_id})")

        def get_code_first(timeout_sec: int = 180):
            return provider.wait_for_sms(act_id, timeout_sec=timeout_sec)

        ok_first, file_first = run_country_flow(
            domain_cc, phone, get_code_first, headful=args.headful,
            proxy=proxy_for_pw, profile=None, cycle_index=i
        )
        print(f"[{domain_cc}] {'OK' if ok_first else 'FAIL'}; cookies: {file_first}")

        # 2) SECOND country only AFTER success (cookie saved), on the SAME number
        if pair_cc and ok_first and file_first:
            print(f"[{pair_cc}] waiting {delay_between}s after {domain_cc} success before starting...")
            time.sleep(delay_between)
            try:
                provider.request_new_code(act_id, pair_cc)
            except Exception as e:
                print(f"[{pair_cc}] request_new_code: {e}")

            def get_code_second(timeout_sec: int = 180):
                return provider.wait_for_sms(act_id, timeout_sec=timeout_sec)

            ok_second, file_second = run_country_flow(
                pair_cc, phone, get_code_second, headful=args.headful,
                proxy=proxy_for_pw, profile=None, cycle_index=i
            )
            print(f"[{pair_cc}] {'OK' if ok_second else 'FAIL'}; cookies: {file_second}")
            try:
                provider.finalize(act_id, success=(ok_first and ok_second))
            except Exception as e:
                print(f"[finalize] {e}")
        else:
            print(f"[{domain_cc}] not successful or no cookies — SKIP second country.")
            try:
                provider.finalize(act_id, success=ok_first)
            except Exception as e:
                print(f"[finalize] {e}")

    print("\nГотово. Cookies — в ./BazosCookies/<Чехия|Словакия>")

if __name__ == "__main__":
    main()
