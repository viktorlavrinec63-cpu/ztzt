
# main.py (v6) — keep same number until both countries succeed or "blocked"; retry on errors
from __future__ import annotations
import os, json, time, argparse
from typing import Optional, Tuple, List, Dict
from sms_providers import ManualSmsProvider, ProviderA, ProviderB, GenericSmsProvider, SmsProviderBase, OnlineSimProvider, SmsHubProvider
from bazos_bot import run_country_flow
from proxy_utils import parse_proxy_line, derive_country_from_proxy

class _ProxyCycler:
    def __init__(self, raw_list):
        self.raw = list(raw_list)
        self.i = 0
    def current(self):
        if not self.raw: return {}
        return parse_proxy_line(self.raw[self.i % len(self.raw)])
    def next(self):
        if not self.raw: return {}
        self.i = (self.i + 1) % max(1, len(self.raw))
        return parse_proxy_line(self.raw[self.i])

import sys
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass


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
    elif provider_name in ("smshub","sms-hub","sms_hub"):
        sh = cfg.get("smshub", {})
        return SmsHubProvider(
            api_key=sh.get("api_key",""),
            service=sh.get("service","cb"),
            base_url=sh.get("base_url","https://smshub.org/stubs/handler_api.php"),
            country_map=sh.get("country_map", {"CZ":63,"SK":141,"PL":15,"DE":43}),
            operator=sh.get("operator","any"),
            poll_interval_sec=int(sh.get("poll_interval_sec",5)),
            max_price=sh.get("max_price"),
            random_issue=bool(sh.get("random", False)),
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

    # round-robin proxy cycler
    proxy_cycler = _ProxyCycler([p for p in proxies_raw if p.strip()])

    runs = max(1, int(args.runs))
    delay_between = int(cfg.get("delay_between_countries_sec", 30))
    max_number_cycles = 1  # one attempt per number (no multi-cycles)

    for i in range(1, runs+1):
        try:
                proxy_info = proxy_cycler.current()
                # bind OnlineSim HTTP to the same proxy
                try:
                    provider.set_http_proxy_from_parsed(proxy_info)
                except Exception:
                    pass
                proxy_for_pw = None
                if proxy_info:
                    proxy_for_pw = {"server": proxy_info["server"]}
                    if proxy_info.get("username"): proxy_for_pw["username"] = proxy_info["username"]
                    if proxy_info.get("password"): proxy_for_pw["password"] = proxy_info["password"]
        
                domain_cc = 'CZ' if ((i % 2) == 1) else 'SK'  # alternate pairs: 1: CZ+SK, 2: SK+CZ, etc.
                pair_cc   = "SK" if domain_cc == "CZ" else "CZ"
                sms_cc    = decide_sms_country(cfg, domain_cc)       # PL/CZ/SK/DE
        
                print(f"\\n=== Цикл {i} | proxy: {proxy_info.get('server','NONE')} | domain={domain_cc}->{pair_cc} | sms={sms_cc} ===")
        
                # Получаем 1 номер и работаем с ним, пока не успех на обеих или «blocked»
                try:
                    act_id, phone = provider.request_number(sms_cc)
                    print(f"[SMS {sms_cc}] Номер: {phone} (act_id={act_id})")
                except Exception as e:
                    print(f"[SMS {sms_cc}] proxy/api error: {e} -> rotate proxy and skip pair")
                    proxy_error = True
                    break
        
                cz_done = (domain_cc == "SK")  # если начинаем со SK, то CZ считается «второй»
                sk_done = (domain_cc == "CZ")  # это условие влияет только на порядок
                # точнее, будем хранить флаги успеха отдельно:
                success_cz = False
                success_sk = False
        
                cycles = 0
                banned = False
                finalized = False
                proxy_error = False
        
                while cycles < max_number_cycles and not (success_cz and success_sk):
                    cycles += 1
                    print(f"[{phone}] cycle {cycles}/1")  # fixed: no 5 tries
        
                    # 1) Всегда сначала домен domain_cc до успеха
                    if ((not success_cz and domain_cc == "CZ") or (not success_sk and domain_cc == "SK")):
                        try:
                            ok, file, reason = run_country_flow(domain_cc, phone, lambda timeout_sec=60: provider.wait_for_sms(act_id, timeout_sec), headful=args.headful, proxy=proxy_for_pw)
                            print(f"[{domain_cc}] {('OK' if ok else 'FAIL')} reason={reason}; cookies: {file}")
                        except Exception as e:
                            print(f"[RUN] proxy/api error: {e} -> rotate proxy and skip pair")
                            proxy_error = True
                            break
                        if reason == "blocked":
                            banned = True; break
                        if ok:
                            if domain_cc == "CZ": success_cz = True
                            else: success_sk = True
                        else:
                            if reason == "no_sms":
                                # No SMS for second country: pair fails, finalize and break
                                try:
                                    provider.finalize(act_id, success=(success_cz and success_sk), banned=banned)
                                    finalized = True
                                except Exception as e:
                                    print(f"[finalize] {e}")
                                break  # идём на новый круг
        
                    # 2) Пауза и вторая страна только после успеха первой
                    if (domain_cc == "CZ" and success_cz and not success_sk) or (domain_cc == "SK" and success_sk and not success_cz):
                        second = pair_cc
                        try: provider.request_new_code(act_id, second)
                        except Exception as e: print(f"[{second}] request_new_code: {e}")
        
                        try:
                            ok, file, reason = run_country_flow(second, phone, lambda timeout_sec=60: provider.wait_for_sms(act_id, timeout_sec), headful=args.headful, proxy=proxy_for_pw)
                            print(f"[{second}] {('OK' if ok else 'FAIL')} reason={reason}; cookies: {file}")
                        except Exception as e:
                            print(f"[RUN] proxy/api error: {e} -> rotate proxy and skip pair")
                            proxy_error = True
                            break
                        if reason == "blocked":
                            banned = True; break
                        if ok:
                            if second == "CZ": success_cz = True
                            else: success_sk = True
                        else:
                            if reason == "no_sms":
                                # Close current activation and get a NEW number for the SECOND country only
                                try:
                                    provider.finalize(act_id, success=(success_cz and success_sk), banned=banned)
        
                                    finalized = True
                                except Exception as e:
                                    print(f"[finalize] {e}")
                                try:
                                    act2, phone2 = provider.request_number(decide_sms_country(cfg, second))
                                    print(f"[SMS {decide_sms_country(cfg, second)}] NEW number for {second}: {phone2} (act_id={act2})")
                                except Exception as e:
                                    print(f"[{second}] failed to get new number: {e}")
                                    continue
                                try:
                                    ok2, file2, reason2 = run_country_flow(
                                        second, phone2,
                                        lambda timeout_sec=60: provider.wait_for_sms(act2, timeout_sec),
                                        headful=args.headful, proxy=proxy_for_pw)
                                    print(f"[{second}] NEW {('OK' if ok2 else 'FAIL')} reason={reason2}; cookies: {file2}")
                                except Exception as e:
                                    print(f"[RUN-NEW] proxy/api error: {e} -> rotate proxy and skip pair")
                                    proxy_error = True
                                    break
                            if ok2:
                                if second == 'CZ': success_cz = True
                                else: success_sk = True
                                # Pair this NEW number with the FIRST country as well
                                first_again = domain_cc
                                try:
                                    provider.request_new_code(act2, first_again)
                                except Exception as e:
                                    print(f"[{first_again}] request_new_code: {e}")
                                try:
                                    okA, fileA, reasonA = run_country_flow(
                                        first_again, phone2,
                                        lambda timeout_sec=60: provider.wait_for_sms(act2, timeout_sec),
                                        headful=args.headful, proxy=proxy_for_pw)
                                    print(f"[{first_again}] {('OK' if okA else 'FAIL')} reason={reasonA}; cookies: {fileA}")
                                except Exception as e:
                                    print(f"[RUN-PAIR] proxy/api error: {e} -> rotate proxy and skip pair")
                                    proxy_error = True
                                    break
                                    if okA:
                                        if first_again == 'CZ': success_cz = True
                                        else: success_sk = True
                                    # finalize
                                    try:
                                        provider.finalize(act2, success=(ok2 and okA), banned=banned)
        
                                        finalized = True
                                    except Exception as e:
                                        print(f"[finalize] {e}")
                                    continue
                                # finalize the new activation (failed second)
                                try:
                                    provider.finalize(act2, success=False, banned=banned)
        
                                    finalized = True
                                except Exception as e:
                                    print(f"[finalize] {e}")
                                continue
                            else:
                                print(f"[{second}] will request a NEW number next…")
                                time.sleep(delay_between)
                                try: provider.request_new_code(act_id, second)
                                except Exception as e: print(f"[{second}] request_new_code: {e}")
                                continue
        
                # Финал для этого номера
                if not finalized:
                    try:
                        provider.finalize(act_id, success=(success_cz and success_sk), banned=banned)
        
                        finalized = True
                    except Exception as e:
                        print(f"[finalize] {e}")
        
                if proxy_error:
                    proxy_cycler.next()
                    continue
                print(f"[{phone}] result: CZ={'OK' if success_cz else 'FAIL'}; SK={'OK' if success_sk else 'FAIL'} (banned={banned})")
        
                # advance proxy for next run
                proxy_cycler.next()
        except Exception as e:
            print(f"[RUN-LEVEL] unexpected error: {e} -> rotate proxy and continue")
            proxy_cycler.next()
            continue


    print("\\nГотово. Cookies — в ./BazosCookies/<Чехия|Словакия>")

if __name__ == "__main__":
    main()