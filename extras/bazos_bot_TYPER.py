
from __future__ import annotations
import os, time, json, random, re, datetime
from typing import Tuple, List, Optional, Union
from playwright.sync_api import sync_playwright, Page, BrowserContext

# Папки для стран
FOLDER_NAMES = {"CZ": "Чехия", "SK": "Словакия", "PL": "Польша", "DE": "Германия"}

# --- конфиг ---
def load_runtime_config() -> dict:
    for p in (os.path.join(os.getcwd(), "config.json"),
              os.path.join(os.path.dirname(__file__), "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

# --- утилиты UI ---
def _any_contains(text: str, needles: List[str]) -> bool:
    t = (text or "").lower()
    return any(n and n.lower() in t for n in needles)

def accept_cookies(page: Page) -> None:
    words = ["Souhlas", "Přijm", "Rozumím", "Súhlas", "Prijať", "OK", "Accept", "Agree"]
    for _ in range(3):
        try:
            # Кнопки/инпуты
            for sel in ["button", "input[type=button]", "input[type=submit]", "[role='button']"]:
                for el in page.query_selector_all(sel):
                    try:
                        txt = (el.inner_text() or el.get_attribute("value") or "").strip()
                        if txt and _any_contains(txt, words):
                            el.click(timeout=800); return
                    except Exception:
                        pass
            # Частые селекторы CMP
            for sel in [
                "#onetrust-accept-btn-handler",
                "button[aria-label*='accept' i]",
                "button[aria-label*='souhlas' i]",
                "button[title*='souhlas' i]",
            ]:
                el = page.query_selector(sel)
                if el:
                    el.click(timeout=800); return
        except Exception:
            pass
        time.sleep(0.25)

def type_slow(el, text: str, min_delay_ms=40, max_delay_ms=120):
    """Печать «как человек»: по символу с задержкой"""
    import random
    try:
        el.click(timeout=1500)
    except Exception:
        pass
    try:
        el.fill("")  # очистим поле
    except Exception:
        pass
    for ch in str(text):
        try:
            el.type(ch, delay=random.randint(min_delay_ms, max_delay_ms))
        except Exception:
            # резерв: через evaluate (редко нужно)
            pass

def find_phone_input(page: Page):
    sels = [
        "input[name*='tel' i]","input[id*='tel' i]",
        "input[name*='phone' i]","input[id*='phone' i]",
        "input[placeholder*='tel' i]",
        "input[placeholder*='telefon' i]",
        "input[placeholder*='telefón' i]",
        "input[placeholder*='telefonní' i]",
    ]
    for sel in sels:
        el = page.query_selector(sel)
        if el: return el
    return None

def find_code_input(page: Page):
    sels = [
        "input[placeholder*='kód' i]","input[placeholder*='kod' i]","input[placeholder*='code' i]",
        "input[name*='code' i]","input[name*='kod' i]",
        "input[id*='code' i]","input[id*='kod' i]",
    ]
    for sel in sels:
        el = page.query_selector(sel)
        if el: return el
    return None

def click_by_text(page: Page, words: List[str], timeout=1500) -> bool:
    # 1) обычные кнопки
    for sel in ["button", "input[type=button]", "input[type=submit]", "[role='button']","a"]:
        for el in page.query_selector_all(sel):
            try:
                txt = (el.inner_text() or el.get_attribute("value") or "").strip()
                if txt and _any_contains(txt, words):
                    el.click(timeout=timeout); return True
            except Exception: pass
    # 2) прицельный локатор
    for w in words:
        try:
            page.locator(f"button:has-text('{w}')").first.click(timeout=timeout); return True
        except Exception: pass
        try:
            page.locator(f"a:has-text('{w}')").first.click(timeout=timeout); return True
        except Exception: pass
    return False

def click_show_phone_or_reply(page: Page) -> None:
    # На объявлении сначала пробуем «показать телефон», затем «ответить/контакт».
    show_phone_words = [
        "Zobrazit tel", "Zobrazit telefon", "Zobrazit číslo",
        "Zobraziť tel", "Zobraziť telefón", "Zobraziť číslo",
        "Ukázat číslo", "Ukázať číslo",
        "Tel.", "Telefon"
    ]
    reply_words = [
        "Odpovědět","Odpovedať","Reagovat","Kontaktovat","Kontaktovať",
        "Napísať","Napsat","Poslat zprávu","Odoslať správu"
    ]
    if click_by_text(page, show_phone_words, timeout=1500):
        time.sleep(0.5)
        return
    click_by_text(page, reply_words, timeout=1500)
    time.sleep(0.5)

def save_cookies_txt(context: BrowserContext, folder: str, country: str) -> str:
    os.makedirs(folder, exist_ok=True)
    cookies = context.cookies()
    lines = []
    for c in cookies:
        parts = [
            f"name={c.get('name','')}", f"value={c.get('value','')}",
            f"domain={c.get('domain','')}", f"path={c.get('path','/')}",
            f"secure={str(c.get('secure', False)).lower()}",
            f"httpOnly={str(c.get('httpOnly', False)).lower()}",
            f"sameSite={c.get('sameSite','')}", f"expirationDate={c.get('expires','')}",
        ]
        lines.append('; '.join(parts))
    stamp = datetime.datetime.utcnow().isoformat().replace(':', '-').replace('.', '-')
    filename = os.path.join(folder, f"cookies-{country}-{stamp}.txt")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return filename

# --- навигация ---
def random_category_click(page: Page, country: str) -> bool:
    base = "bazos.cz" if country == "CZ" else "bazos.sk"
    anchors = page.query_selector_all("a[href]") or []
    candidates = []
    for a in anchors:
        try:
            href = (a.get_attribute("href") or "").strip()
            if href.startswith("/"):
                href = f"https://www.{base}{href}"
            if not href.startswith("http"):
                continue
            if re.search(r"/inzerat/", href, re.I):
                continue
            # вид вида https://www.bazos.cz/auto/  (категория)
            if re.match(rf"^https?://(www\.)?{re.escape(base)}/[a-z0-9\-]+/?$", href, re.I):
                candidates.append(href)
        except Exception:
            pass
    random.shuffle(candidates)
    for url in candidates[:20]:
        try:
            page.goto(url, timeout=30000, wait_until="load")
            accept_cookies(page)
            return True
        except Exception:
            continue
    return False

def random_ad_click(page: Page) -> bool:
    links = page.query_selector_all("a[href*='/inzerat/']") or []
    urls = []
    for l in links:
        try:
            u = l.get_attribute("href") or ""
            if "/inzerat/" in u:
                urls.append(u)
        except Exception:
            pass
    random.shuffle(urls)
    for u in urls[:20]:
        try:
            page.goto(u, timeout=30000, wait_until="load")
            accept_cookies(page); return True
        except Exception:
            continue
    return False

# --- основной поток ---
def run_country_flow(
    country: str,
    phone: str,
    get_code_fn=None,
    headful: bool=False,
    proxy: Optional[Union[dict,str]]=None,
    profile: Optional[dict]=None,
    cycle_index: Optional[int]=None,
    **kwargs
) -> Tuple[bool, str]:
    cfg = load_runtime_config()
    base_url = "https://www.bazos.cz" if country == "CZ" else "https://www.bazos.sk"
    retry_delay = int(cfg.get("retry_delay_sec", 60))
    max_attempts = int(cfg.get("max_attempts", 3))

    try:
        with sync_playwright() as pw:
            launch_args = {"headless": (not headful)}
            if proxy:
                if isinstance(proxy, dict):
                    launch_args["proxy"] = proxy
                else:
                    srv = str(proxy)
                    if srv.startswith("socks5h://"):
                        srv = "socks5://" + srv[len("socks5h://"):]
                    launch_args["proxy"] = {"server": srv}
            print(f"[playwright] launching headful={headful} proxy={launch_args.get('proxy')}")
            browser = pw.chromium.launch(**launch_args)

            context_args = {}
            if profile:
                if profile.get("locale"): context_args["locale"] = profile["locale"]
                if profile.get("timezoneId"): context_args["timezone_id"] = profile["timezoneId"]
                if profile.get("userAgent"): context_args["user_agent"] = profile["userAgent"]
                if profile.get("viewport"): context_args["viewport"] = profile["viewport"]
                if profile.get("colorScheme"): context_args["color_scheme"] = profile["colorScheme"]
            context = browser.new_context(**context_args)
            page = context.new_page()

            success = False
            cookie_file = ""

            for attempt in range(1, max_attempts+1):
                print(f"[{country}] attempt {attempt}/{max_attempts}")
                page.goto(base_url, timeout=45000, wait_until="load")
                accept_cookies(page)

                # категория → объявление
                if not random_category_click(page, country):
                    print("[flow] Не удалось открыть категорию, пробуем снова после паузы.")
                else:
                    if not random_ad_click(page):
                        print("[flow] Не удалось открыть объявление, пробуем снова после паузы.")

                # на странице объявления
                click_show_phone_or_reply(page)

                # ввод телефона «как человек»
                tel_el = find_phone_input(page)
                if tel_el and phone:
                    type_slow(tel_el, phone)

                # получить код
                click_by_text(page, ["Získat kód","Získať kód","Odeslat kód","Poslať кód","Send code","Poslat kód"], timeout=1500)

                code = None
                if get_code_fn:
                    try:
                        code = get_code_fn(timeout_sec=int(cfg.get("onlinesim",{}).get("timeout_sec", 120)))
                    except Exception:
                        code = None

                # ввести код
                if code:
                    ci = find_code_input(page)
                    if ci:
                        type_slow(ci, str(code))
                        click_by_text(page, ["Potvrdit","Overit","Ověřit","Overiť","Confirm"], timeout=1500)
                        time.sleep(1.5)

                # определить успех/ошибку
                html = (page.content() or "").lower()
                success_words = ["ďakujem","dakujem","úspeš","úspěš","overen","ověřen","správa odoslaná","zpráva odeslána"]
                error_words   = ["chybn","nespráv","neplat","znovu","error","chyba","nesprávny kód","kód není platný","neplatný kód"]
                success = any(w in html for w in success_words) and not any(w in html for w in error_words)

                if success:
                    folder = os.path.join(os.getcwd(), "BazosCookies", FOLDER_NAMES.get(country, country))
                    cookie_file = save_cookies_txt(context, folder, country)
                    print(f"[{country}] SUCCESS; cookies: {cookie_file}")
                    break
                else:
                    print(f"[{country}] not success; wait {retry_delay}s and retry…")
                    time.sleep(retry_delay)
                    try:
                        page.reload(timeout=15000); accept_cookies(page)
                    except Exception:
                        pass

            context.close()
            browser.close()
            return success, cookie_file

    except Exception as e:
        print(f"[run_country_flow] error: {e}")
        return False, ""

