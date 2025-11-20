
# bazos_bot.py — save cookies ONLY on success
from __future__ import annotations
import os, time, json, random, re, hashlib, datetime
from typing import Tuple, List, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext

FOLDER_NAMES = {"CZ": "Чехия", "SK": "Словакия", "PL": "Польша", "DE": "Германия"}

def load_runtime_config() -> dict:
    for p in (os.path.join(os.getcwd(), "config.json"),
              os.path.join(os.path.dirname(__file__), "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _any_contains(text: str, needles: List[str]) -> bool:
    t = (text or "").lower()
    return any((n.lower() in t) for n in needles if n)

def click_button_with_text(page: Page, texts: List[str], timeout: int = 2000) -> bool:
    selectors = ["button", "input[type=button]", "input[type=submit]", "[role='button']"]
    for sel in selectors:
        for el in page.query_selector_all(sel):
            try:
                txt = (el.inner_text() or el.get_attribute("value") or "").strip()
                if txt and _any_contains(txt, texts):
                    el.click(timeout=timeout); return True
            except Exception: pass
    for t in texts:
        try:
            page.locator(f"button:has-text('{t}')").first.click(timeout=timeout); return True
        except Exception: pass
    return False

def accept_cookies(page: Page) -> None:
    words = ["Souhlas","Přijm","Rozumím","Súhlas","Prijať","OK","Accept","Agree"]
    for _ in range(3):
        if click_button_with_text(page, words, 1000): return
        for sel in ["#onetrust-accept-btn-handler","button[aria-label*='accept' i]",
                    "button[aria-label*='souhlas' i]","button[title*='souhlas' i]"]:
            try:
                el = page.query_selector(sel); 
                if el: el.click(timeout=1000); return
            except Exception: pass
        time.sleep(0.3)

def find_phone_input(page: Page):
    sels = ["input[name*='tel' i]","input[id*='tel' i]","input[name*='phone' i]","input[id*='phone' i]",
            "input[placeholder*='tel' i]","input[placeholder*='telefon' i]",
            "input[placeholder*='telefonní' i]","input[placeholder*='telefón' i]"]
    for sel in sels:
        el = page.query_selector(sel)
        if el: return el
    return None

def find_code_input(page: Page):
    sels = ["input[placeholder*='kód' i]","input[placeholder*='kod' i]","input[placeholder*='code' i]",
            "input[name*='code' i]","input[name*='kod' i]","input[id*='code' i]","input[id*='kod' i]"]
    for sel in sels:
        el = page.query_selector(sel)
        if el: return el
    return None

def random_category_click(page: Page, country: str) -> bool:
    try: anchors = page.query_selector_all("a[href]")
    except Exception: anchors = []
    base = "bazos.cz" if country == "CZ" else "bazos.sk"
    candidates = []
    for a in anchors:
        try:
            href = (a.get_attribute("href") or "").strip()
            if href.startswith("/"): href = f"https://www.{base}{href}"
            if not href.startswith("http"): continue
            if re.search(r"/inzerat/", href, re.I): continue
            if re.match(rf"^https?://(www\.)?{re.escape(base)}/[a-z0-9\-]+/?$", href, re.I):
                candidates.append(href)
        except Exception: pass
    random.shuffle(candidates)
    for url in candidates[:20]:
        try:
            page.goto(url, timeout=30000, wait_until="load")
            accept_cookies(page)
            if page.query_selector("a[href*='/inzerat/']"): return True
            return True
        except Exception: continue
    return False

def random_ad_click(page: Page) -> bool:
    links = page.query_selector_all("a[href*='/inzerat/']")
    urls = []
    for l in links:
        try:
            u = l.get_attribute("href") or ""
            if "/inzerat/" in u: urls.append(u)
        except Exception: pass
    random.shuffle(urls)
    for u in urls[:20]:
        try:
            page.goto(u, timeout=30000, wait_until="load"); accept_cookies(page); return True
        except Exception: continue
    return False

def open_reply_form(page: Page) -> bool:
    words = ["Odpovědět","Odpovedať","Reagovat","Kontaktovat","Kontaktovať","Napísať","Napsat","Poslat zprávu","Odoslať správu"]
    if click_button_with_text(page, words, 2000): time.sleep(0.5); return True
    for w in words:
        try: page.locator(f\"a:has-text('{w}')\").first.click(timeout=1500); time.sleep(0.5); return True
        except Exception: pass
    return False

def save_cookies_txt(context: BrowserContext, folder: str, country: str) -> str:
    os.makedirs(folder, exist_ok=True)
    cookies = context.cookies()
    lines = []
    for c in cookies:
        parts = [f\"name={c.get('name','')}\", f\"value={c.get('value','')}\",
                 f\"domain={c.get('domain','')}\", f\"path={c.get('path','/')}\",
                 f\"secure={str(c.get('secure', False)).lower()}\",
                 f\"httpOnly={str(c.get('httpOnly', False)).lower()}\",
                 f\"sameSite={c.get('sameSite','')}\", f\"expirationDate={c.get('expires','')}\"]
        lines.append('; '.join(parts))
    stamp = datetime.datetime.utcnow().isoformat().replace(':','-').replace('.','-')
    filename = os.path.join(folder, f\"cookies-{country}-{stamp}.txt\")
    with open(filename, 'w', encoding='utf-8') as f: f.write('\\n'.join(lines))
    return filename

def run_country_flow(country: str, phone: str, get_code_fn=None, headful: bool=False,
                     proxy: Optional[dict|str]=None, profile: Optional[dict]=None,
                     cycle_index: Optional[int]=None, **kwargs) -> Tuple[bool,str]:
    base_url = \"https://www.bazos.cz\" if country == \"CZ\" else \"https://www.bazos.sk\"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            launch_args = {\"headless\": (not headful)}
            if proxy:
                if isinstance(proxy, dict): launch_args[\"proxy\"] = proxy
                else:
                    srv = str(proxy)
                    if srv.startswith(\"socks5h://\"): srv = \"socks5://\" + srv[len(\"socks5h://\"):]
                    launch_args[\"proxy\"] = {\"server\": srv}
            print(f\"[playwright] launching headful={headful} proxy={launch_args.get('proxy')}\")
            browser = pw.chromium.launch(**launch_args)

            context = browser.new_context()
            page = context.new_page()

            page.goto(base_url, timeout=45000, wait_until=\"load\")
            accept_cookies(page)

            if not random_category_click(page, country):
                print(\"[flow] No category found\")
            else:
                accept_cookies(page)

            if not random_ad_click(page):
                page.goto(base_url, timeout=30000); accept_cookies(page)
                random_category_click(page, country); random_ad_click(page)
            accept_cookies(page)

            open_reply_form(page)

            phone_input = find_phone_input(page)
            if phone_input and phone:
                try: phone_input.fill(phone)
                except Exception: pass

            click_button_with_text(page, [\"Získat kód\",\"Získať кód\",\"Odeslat кód\",\"Poslať кód\",\"Send code\",\"Poslat кód\"])  # accents may vary

            code = None
            if get_code_fn:
                try: code = get_code_fn(timeout_sec=120)
                except Exception: code = None

            success = False
            if code:
                ci = find_code_input(page)
                if ci:
                    try:
                        ci.fill(str(code))
                        click_button_with_text(page, [\"Potvrdit\",\"Overit\",\"Ověřit\",\"Overiť\",\"Confirm\"])
                        time.sleep(1.0)
                        html = (page.content() or \"\").lower()
                        success = any(x in html for x in [\"ďakujem\",\"dakujem\",\"úspeš\",\"úspěš\",\"overen\",\"ověřen\",\"správa odoslaná\",\"zpráva odeslána\"]) 
                                  and not any(x in html for x in [\"chybn\",\"nespráv\",\"neplat\",\"znovu\",\"error\",\"chyba\"])
                    except Exception: pass

            cookie_file = \"\"
            if success:
                folder = os.path.join(os.getcwd(), \"BazosCookies\", FOLDER_NAMES.get(country, country))
                cookie_file = save_cookies_txt(context, folder, country)

            context.close(); browser.close()
            return success, cookie_file
    except Exception as e:
        print(f\"[run_country_flow] error: {e}\")
        return False, \"\"
