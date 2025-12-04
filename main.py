
# main.py (v6) — keep same number until both countries succeed or "blocked"; retry on errors
from __future__ import annotations
from pathlib import Path
import logging

def _setup_logging_main():
    try:
        base_dir = Path(__file__).resolve().parent
        logs_dir = base_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        fp = logs_dir / "bot.log"
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            handlers=[logging.FileHandler(fp, encoding="utf-8")])
    except Exception:
        # не шумим в stdout — просто игнорируем проблемы с логами
        pass
_setup_logging_main()
import os, json, time, argparse, logging
from typing import Optional, Tuple, List, Dict
from sms_providers import ManualSmsProvider, GenericSmsProvider, SmsProviderBase, OnlineSimProvider, SmsHubProvider, SecondNoProvider
from bazos_bot import run_country_flow
from proxy_utils import parse_proxy_line, derive_country_from_proxy, get_next_proxy_for_country

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
import time
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
    elif provider_name in ("secondno","2ndno","2nd-no"):
        sn = cfg.get("secondno", {})
        return SecondNoProvider(
            chrome_portable_dir=sn.get("chrome_dir","GoogleChromePortable"),
            ext_dir=sn.get("ext_dir","chrome_ext/secondno_bridge"),
            port=int(sn.get("port",8765)),
            start_timeout=int(sn.get("start_timeout",10)),
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
    ap.add_argument("--ws-mode", action="store_true", help="use extension WS bridge", default=False)
    args = ap.parse_args()

    cfg = load_config(args.config)
    proxies_raw = read_lines(args.proxies)
    provider = get_provider(cfg)

    # round-robin proxy cycler
    proxy_cycler = _ProxyCycler([p for p in proxies_raw if p.strip()])

    runs = max(1, int(args.runs))
    delay_between = int(cfg.get("delay_between_countries_sec", 40))
    max_number_cycles = 1  # one attempt per number (no multi-cycles)

    for i in range(1, runs+1):
        try:
            proxy_info = proxy_cycler.current()
            # bind OnlineSim HTTP to the same proxy
            try:
                provider.set_http_proxy_from_parsed(proxy_info)
            except Exception:
                pass

            # глобальный fallback-прокси (как раньше)
            proxy_for_pw_global = None
            if proxy_info:
                proxy_for_pw_global = {"server": proxy_info["server"]}
                if proxy_info.get("username"):
                    proxy_for_pw_global["username"] = proxy_info["username"]
                if proxy_info.get("password"):
                    proxy_for_pw_global["password"] = proxy_info["password"]

            # прокси для конкретных стран из отдельных файлов (CZ / SK)
            def build_pw_proxy_from_raw(raw: str):
                if not raw:
                    return None
                info = parse_proxy_line(raw)
                if not info or not info.get("server"):
                    return None
                d = {"server": info["server"]}
                if info.get("username"):
                    d["username"] = info["username"]
                if info.get("password"):
                    d["password"] = info["password"]
                return d

            proxy_for_pw_cz = None
            proxy_for_pw_sk = None
            try:
                raw_cz = get_next_proxy_for_country("CZ")
                proxy_for_pw_cz = build_pw_proxy_from_raw(raw_cz)
            except Exception:
                proxy_for_pw_cz = None

            try:
                raw_sk = get_next_proxy_for_country("SK")
                proxy_for_pw_sk = build_pw_proxy_from_raw(raw_sk)
            except Exception:
                proxy_for_pw_sk = None

            def pick_proxy_for_country(cc: str):
                cc = (cc or "").upper()
                if cc == "CZ" and proxy_for_pw_cz:
                    return proxy_for_pw_cz
                if cc == "SK" and proxy_for_pw_sk:
                    return proxy_for_pw_sk
                return proxy_for_pw_global

            print(f"[PROXY] CZ -> {proxy_for_pw_cz}")
            print(f"[PROXY] SK -> {proxy_for_pw_sk}")
            
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
                try:
                    proxy_cycler.next()
                except Exception:
                    pass
                except Exception: pass
                continue  
    
            cz_done = (domain_cc == "SK")  # если начинаем со SK, то CZ считается «второй»
            sk_done = (domain_cc == "CZ")  # это условие влияет только на порядок
            # точнее, будем хранить флаги успеха отдельно:
            success_cz = False
            success_sk = False
    
            country_ok = {"CZ": False, "SK": False}
            country_reason = {"CZ": "not-run", "SK": "not-run"}
    
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
                        ok, file, reason = run_country_flow(domain_cc, phone, lambda timeout_sec=60: provider.wait_for_sms(act_id, timeout_sec), headful=args.headful, proxy=pick_proxy_for_country(domain_cc))
                        country_ok[domain_cc] = ok
                        country_reason[domain_cc] = reason
                        print(f"[{domain_cc}] {('OK' if ok else 'FAIL')} reason={reason}; cookies: {file}")
                    except Exception as e:
                        print(f"[RUN] proxy/api error: {e} -> rotate proxy and skip pair")
                        proxy_error = True
                        try:
                            proxy_cycler.next()
                        except Exception:
                            pass
                        except Exception: pass
                        continue  
                    if reason == "blocked":
                        banned = True
                        try:
                            proxy_cycler.next()
                        except Exception:
                            pass
                        continue
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
                                try:
                                    proxy_cycler.next()
                                except Exception:
                                    pass
                            except Exception: pass
                            continue    # идём на новый круг
    
                # 2) Пауза и вторая страна только после успеха первой
                if (domain_cc == "CZ" and success_cz and not success_sk) or (domain_cc == "SK" and success_sk and not success_cz):
                    second = pair_cc
                    print('[pair] wait 40s before second country...')
                    time.sleep(delay_between)
                    try:
                        provider.request_new_code(act_id, second)
                    except Exception as e:
                        print(f"[{second}] request_new_code (noop for WS): {e}")
    
                    try:
                        ok, file, reason = run_country_flow(second, phone, lambda timeout_sec=60: provider.wait_for_sms(act_id, timeout_sec), headful=args.headful, proxy=pick_proxy_for_country(second))
                        country_ok[second] = ok
                        country_reason[second] = reason
                        print(f"[{second}] {('OK' if ok else 'FAIL')} reason={reason}; cookies: {file}")
                    except Exception as e:
                        print(f"[RUN] proxy/api error: {e} -> rotate proxy and skip pair")
                        proxy_error = True
                        try:
                            proxy_cycler.next()
                        except Exception:
                            pass
                        except Exception: pass
                        continue  
                    if reason == "blocked":
                        banned = True
                        try:
                            proxy_cycler.next()
                        except Exception:
                            pass
                        continue
                    if ok:
                        if second == "CZ": success_cz = True
                        else: success_sk = True
                    else:
                        if reason == "no_sms":
                            # second-country failed -> finalize this activation and skip to next pair
                            try:
                                provider.finalize(act_id, success=(success_cz and success_sk), banned=banned)
                                finalized = True
                            except Exception as e:
                                print(f"[finalize] {e}")
                            continue
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
                            ok2 = False
                            reason2 = "not-run"
                            try:
                                ok2, file2, reason2 = run_country_flow(
                                    second, phone2,
                                    lambda timeout_sec=60: provider.wait_for_sms(act2, timeout_sec),
                                    headful=args.headful, proxy=pick_proxy_for_country(second))
                                country_ok[second] = ok2
                                country_reason[second] = reason2
                                print(f"[{second}] NEW {('OK' if ok2 else 'FAIL')} reason={reason2}; cookies: {file2}")
                            except Exception as e:
                                reason2 = f"exception: {e}"
                                country_ok[second] = False
                                country_reason[second] = reason2
                                print(f"[RUN-NEW] proxy/api error: {e} -> rotate proxy and skip pair")
                                proxy_error = True
                                try:
                                    proxy_cycler.next()
                                except Exception:
                                    pass
                                except Exception: pass
                                continue  
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
                                    headful=args.headful, proxy=pick_proxy_for_country(first_again))
                                country_ok[first_again] = okA
                                country_reason[first_again] = reasonA
                                print(f"[{first_again}] {('OK' if okA else 'FAIL')} reason={reasonA}; cookies: {fileA}")
                            except Exception as e:
                                print(f"[RUN-PAIR] proxy/api error: {e} -> rotate proxy and skip pair")
                                proxy_error = True
                                try:
                                    proxy_cycler.next()
                                except Exception:
                                    pass
                                except Exception: pass
                                continue  
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
                            # second-country failed -> finalize this activation and skip to next pair
                            try:
                                provider.finalize(act_id, success=(success_cz and success_sk), banned=banned)
                                finalized = True
                            except Exception as e:
                                print(f"[finalize] {e}")
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
                    print(
                        f"[{phone}] result: CZ={'OK' if country_ok['CZ'] else 'FAIL'} ({country_reason['CZ']}); "
                        f"SK={'OK' if country_ok['SK'] else 'FAIL'} ({country_reason['SK']}); banned={banned}"
                    )
            
                    # advance proxy for next run
                    proxy_cycler.next()
        except Exception as e:
            print(f"[RUN-LEVEL] unexpected error: {e} -> rotate proxy and continue")
            proxy_cycler.next()
            continue


    print("\\nГотово. Cookies — в ./BazosCookies/<Чехия|Словакия>")

if __name__ == "__main__":
    main()
