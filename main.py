
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
import os, json, argparse, logging
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

            # прокси для конкретной страны из отдельного файла (CZ)
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
            try:
                raw_cz = get_next_proxy_for_country("CZ")
                proxy_for_pw_cz = build_pw_proxy_from_raw(raw_cz)
            except Exception:
                proxy_for_pw_cz = None

            def pick_proxy_for_country(cc: str):
                cc = (cc or "").upper()
                if cc == "CZ" and proxy_for_pw_cz:
                    return proxy_for_pw_cz
                return proxy_for_pw_global

            print(f"[PROXY] CZ -> {proxy_for_pw_cz}")
            
            domain_cc = "CZ"
            sms_cc = "CZ"

            print(f"\\n=== Цикл {i} | proxy: {proxy_info.get('server','NONE')} | domain={domain_cc} | sms={sms_cc} ===")

            # Получаем 1 номер и работаем с ним только для Чехии
            try:
                act_id, phone = provider.request_number(sms_cc)
                print(f"[SMS {sms_cc}] Номер: {phone} (act_id={act_id})")
            except Exception as e:
                print(f"[SMS {sms_cc}] proxy/api error: {e} -> rotate proxy and skip run")
                proxy_error = True
                try:
                    proxy_cycler.next()
                except Exception:
                    pass
                except Exception: pass
                continue  
            banned = False
            proxy_error = False
            ok = False
            reason = "not-run"
            file = None

            try:
                ok, file, reason = run_country_flow(
                    domain_cc,
                    phone,
                    lambda timeout_sec=60: provider.wait_for_sms(act_id, timeout_sec),
                    headful=args.headful,
                    proxy=pick_proxy_for_country(domain_cc),
                )
                print(f"[{domain_cc}] {('OK' if ok else 'FAIL')} reason={reason}; cookies: {file}")
            except Exception as e:
                print(f"[RUN] proxy/api error: {e} -> rotate proxy and skip run")
                proxy_error = True

            if reason == "blocked":
                banned = True

            # Финальная очистка после регистрации Чехии
            try:
                provider.finalize(act_id, success=ok, banned=banned)
            except Exception as e:
                print(f"[finalize] {e}")
            try:
                if hasattr(provider, "stop"):
                    provider.stop()
            except Exception:
                pass

            if proxy_error:
                proxy_cycler.next()
                continue

            print(f"[{phone}] result: CZ={'OK' if ok else 'FAIL'} ({reason}); banned={banned}")

            # advance proxy for next run
            proxy_cycler.next()
        except Exception as e:
            print(f"[RUN-LEVEL] unexpected error: {e} -> rotate proxy and continue")
            proxy_cycler.next()
            continue


    print("\\nГотово. Cookies — в ./BazosCookies/Чехия")

if __name__ == "__main__":
    main()
