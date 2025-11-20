
# bazos_bot.py (v2) — returns (ok, cookie_file, reason) where reason in {"success","blocked","error"}
from __future__ import annotations
from playwright.sync_api import sync_playwright, Page, BrowserContext
# === FP helpers (profile-seeded) ===
def _seed_from_profile(profile: dict | None) -> int:
    import hashlib, json as _json, os as _os
    if not profile:
        return int.from_bytes((_os.urandom(4)), 'big')
    key = profile.get('id') or profile.get('name') or profile.get('email') or _json.dumps(profile, sort_keys=True)[:128]
    h = hashlib.sha256(str(key).encode('utf-8')).digest()
    return int.from_bytes(h[:4], 'big')

def _pick_viewport_from_seed(seed: int):
    import random as _r
    _r.seed(seed ^ 0xA5A5C3C3)
    candidates = [
        (1920,1080),(1366,768),(1536,864),(1600,900),(1440,900),
        (1280,720),(1280,800),(1680,1050),(1920,1200),(2560,1440)
    ]
    w,h = _r.choice(candidates)
    dprs = [1.0, 1.25, 1.5, 2.0]
    dpr = _r.choice(dprs)
    aw = max(0, w - _r.randrange(0, 60))
    ah = max(0, h - _r.randrange(0, 60))
    return int(w), int(h), float(dpr), int(aw), int(ah)

def _fp_extra_js(seed: int, locale: str, vw: int, vh: int, dpr: float, aw: int, ah: int) -> str:
    # build JS without Python f-strings to avoid brace escaping issues
    tmpl = """
    (() => {
      try {
        const SEED = SEEDVAL;
        function rint(n){ let x = (SEED ^ 0x9e3779b9) + n; x ^= x<<13; x^=x>>>17; x^=x<<5; return x>>>0; }
        function pick(arr,n){ return arr[Math.abs(n)%arr.length]; }
        // userAgentData
        const brands = [
          {brand: 'Chromium', version: (navigator.userAgent.match(/Chrome\/([\d.]+)/)||[])[1] || '124'},
          {brand: 'Not.A/Brand', version: '99'},
          {brand: 'Google Chrome', version: (navigator.userAgent.match(/Chrome\/([\d.]+)/)||[])[1] || '124'}
        ];
        Object.defineProperty(navigator, 'userAgentData', { get: () => ({ brands, mobile: false, platform: navigator.platform || 'Windows' }) });
        // languages
        const loc = 'LOCALEVAL';
        Object.defineProperty(navigator, 'languages', { get: () => [loc, loc.split('-')[0], 'en-US'] });
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        // Screen & DPR
        const _w = VWVAL, _h = VHVAL, _aw = AWVAL, _ah = AHVAL, _dpr = DPRVAL;
        ['width','height','availWidth','availHeight','colorDepth','pixelDepth'].forEach((k,i)=>{
          let val = (k==='width'?_w:k==='height'?_h:k==='availWidth'?_aw:k==='availHeight'?_ah:24);
          Object.defineProperty(screen, k, { get: () => val });
        });
        Object.defineProperty(window, 'devicePixelRatio', { get: () => _dpr });
        // Hardware-like fields
        const HCs = [2,4,8,12,16];
        const DMs = [2,4,8];
        const MTP = [0,0,0,1,2];
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => pick(HCs, rint(10)) });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => pick(DMs, rint(11)) });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: () => pick(MTP, rint(12)) });
        const PLAT = ['Win32','Windows','Linux x86_64'];
        Object.defineProperty(navigator, 'platform', { get: () => pick(PLAT, rint(13)) });
        // Plugins/MimeTypes stubs
        const Plug = function(n){ this.name=n; this.filename=n+'.dll'; this.description=n; };
        const plugins = [new Plug('Chrome PDF Viewer'), new Plug('Chromium PDF Viewer'), new Plug('PDF Viewer')];
        Object.defineProperty(navigator, 'plugins', { get: () => plugins });
        Object.defineProperty(navigator, 'mimeTypes', { get: () => [{type:'application/pdf'},{type:'text/pdf'}] });
        // Canvas noise (seeded)
        function noise(i){ return (((rint(100+i)%7)-3)/255); }
        const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(...args){
          try{ const ctx = this.getContext('2d'); if(ctx){ const w=Math.min(8,this.width),h=Math.min(8,this.height); const imgd=ctx.getImageData(0,0,w,h); const d=imgd.data; for(let i=0;i<d.length;i+=4){ d[i]+=noise(i); d[i+1]+=noise(i+1); d[i+2]+=noise(i+2);} ctx.putImageData(imgd,0,0);} }catch(e){}
          return _toDataURL.apply(this, args);
        };
        // WebGL vendor/renderer
        const VEND = ['Google Inc. (Intel)','Google Inc. (NVIDIA)','ATI Technologies Inc.','Intel Inc.'];
        const REND = ['ANGLE (Intel, Intel(R) HD Graphics 530 Direct3D11 vs_5_0 ps_5_0)','ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Direct3D11 vs_5_0 ps_5_0)','AMD Radeon(TM) RX 560','Intel(R) Iris(R) Plus'];
        const vend = pick(VEND, rint(20)); const rend = pick(REND, rint(21));
        const wrap = (proto) => { if(!proto) return;
          const _gp=proto.getParameter, _ge=proto.getExtension;
          proto.getExtension=function(name){ if(String(name).toLowerCase()==='webgl_debug_renderer_info') return { UNMASKED_VENDOR_WEBGL:0x9245, UNMASKED_RENDERER_WEBGL:0x9246 }; return _ge.call(this,name); };
          proto.getParameter=function(p){ try{ const ext=this.getExtension && this.getExtension('WEBGL_debug_renderer_info'); if(ext){ if(p===ext.UNMASKED_VENDOR_WEBGL) return vend; if(p===ext.UNMASKED_RENDERER_WEBGL) return rend; } }catch(e){} return _gp.call(this,p); };
        };
        if (window.WebGLRenderingContext) wrap(window.WebGLRenderingContext.prototype);
        if (window.WebGL2RenderingContext) wrap(window.WebGL2RenderingContext.prototype);
        // Font metrics jitter (tiny)
        const _mt = CanvasRenderingContext2D.prototype.measureText;
        CanvasRenderingContext2D.prototype.measureText = function(t){ const m=_mt.call(this,t); try{ const j=((rint(33)%5)-2)*0.01; Object.defineProperty(m,'width',{value:Math.max(0,m.width*(1+j))}); }catch(e){} return m; };
      } catch(e) {}
    })();
    """
    js = (tmpl
          .replace('SEEDVAL', str(int(seed)))
          .replace('LOCALEVAL', str(locale))
          .replace('VWVAL', str(int(vw)))
          .replace('VHVAL', str(int(vh)))
          .replace('AWVAL', str(int(aw)))
          .replace('AHVAL', str(int(ah)))
          .replace('DPRVAL', str(float(dpr)))
         )
    return js
# === /FP helpers ===


# === Fingerprint rotation ===
UA_DATABASE = {
    "chrome": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/124.0.0.0 Chrome/124.0.0.0 Safari/537.36",
    ]
}
LOCALE_BY_CC = {"CZ": "cs-CZ", "SK": "sk-SK"}
TZ_BY_CC = {"CZ": "Europe/Prague", "SK": "Europe/Bratislava"}
GEO_BY_CC = {"CZ": {"latitude": 50.0755, "longitude": 14.4378}, "SK": {"latitude": 48.1486, "longitude": 17.1077}}
def pick_user_agent():
    import random as _r
    return _r.choice(UA_DATABASE["chrome"])
def build_fingerprint(country_cc: str):
    ua = pick_user_agent()
    locale = LOCALE_BY_CC.get(country_cc, "en-US")
    tz = TZ_BY_CC.get(country_cc, "Europe/Prague")
    geo = GEO_BY_CC.get(country_cc, {"latitude": 50.09, "longitude": 14.42})
    # Small JS to spoof extra fields and userAgentData.brands
    init_js = f"""
    (() => {{
      try {{
        const brands = [
          {{brand: 'Chromium', version: (navigator.userAgent.match(/Chrome\/([\d.]+)/)||[])[1] || '124'}},
          {{brand: 'Not.A/Brand', version: '99'}},
          {{brand: 'Google Chrome', version: (navigator.userAgent.match(/Chrome\/([\d.]+)/)||[])[1] || '124'}}
        ];
        Object.defineProperty(navigator, 'userAgentData', {{
          get: () => ({{ brands, mobile: false, platform: navigator.platform || 'Windows' }})
        }});
        Object.defineProperty(navigator, 'plugins', {{ get: () => [{{name:'Chrome PDF Viewer'}}, {{name:'Chromium PDF Viewer'}}] }});
        Object.defineProperty(screen, 'colorDepth', {{ get: () => 24 }});
        Object.defineProperty(navigator, 'platform', {{ get: () => 'Win32' }});
        // languages
        Object.defineProperty(navigator, 'languages', {{ get: () => ['{locale}', '{locale.split('-')[0]}', 'en-US'] }});
      }} catch(e) {{}}
    }})();
    """
    return ua, locale, tz, geo, init_js
import os, time, json, random, re, datetime, threading

# Feature flag requested by the user: disable the SMS guard that blocks form
# submissions until an OTP is entered. Flip to True if we ever need to restore
# the guard behaviour.
SMS_GUARD_ENABLED = False
from typing import Tuple, List, Optional, Union

def _is_success_phone_shown(page: Page) -> bool:
    """
    Heuristic success: input[name='klic'] is gone AND <a class="teldetail"> has 6+ digits.
    """
    try:
        code_input_exists = page.locator("input[name='klic']").count() > 0
    except Exception:
        code_input_exists = False
    phone_txt = ""
    try:
        el = page.locator("a.teldetail").first
        if el:
            phone_txt = el.inner_text() or ""
    except Exception:
        pass
    digits = "".join(ch for ch in phone_txt if ch.isdigit())
    return (len(digits) >= 6) and (not code_input_exists)


def _wait_phone_visible_after_confirm(page: Page, max_wait_sec: int = 15) -> bool:
    """
    Success heuristic: after submit/confirm, the code input disappears,
    and a phone number like +420... or +421... is shown on the page.
    """
    import re as _re, time as _time
    deadline = _time.time() + max_wait_sec
    while _time.time() < deadline:
        try:
            html = (page.content() or "")
        except Exception:
            html = ""
        hlow = html.lower()
        # No verification input
        code_input_absent = ("type=\"tel\"" not in hlow) and ("name=\"tel\"" not in hlow) and ("id=\"tel\"" not in hlow)
        # Phone pattern
        phone_shown = bool(_re.search(r"\+\d{9,15}", html))
        if code_input_absent and phone_shown:
            return True
        try:
            page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass
    return False

FOLDER_NAMES = {"CZ": "Чехия", "SK": "Словакия", "PL": "Польша", "DE": "Германия"}

def load_runtime_config() -> dict:
    for p in (os.path.join(os.getcwd(), "config.json"),
              os.path.join(os.path.dirname(__file__), "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return {}

def _any_contains(text: str, needles: List[str]) -> bool:
    t = (text or "").lower()
    return any(n and n.lower() in t for n in needles)

def accept_cookies(page: Page) -> None:
    words = ["Souhlas","Přijm","Rozumím","Súhlas","Prijať","OK","Accept","Agree"]
    for _ in range(3):
        try:
            for sel in ["button","input[type=button]","input[type=submit]","[role='button']"]:
                for el in page.query_selector_all(sel):
                    try:
                        txt = (el.inner_text() or el.get_attribute("value") or "").strip()
                        if txt and _any_contains(txt, words):
                            el.click(timeout=800); return
                    except Exception: pass
            for sel in ["#onetrust-accept-btn-handler","button[aria-label*='accept' i]","button[aria-label*='souhlas' i]","button[title*='souhlas' i]"]:
                el = page.query_selector(sel)
                if el: el.click(timeout=800); return
        except Exception: pass
        time.sleep(0.25)


def _click_random_listing(page: Page) -> bool:
    """Open a random listing on current category page. Returns True on success.
       Ensures host (subdomain) stays the same as current page (e.g., motorky.bazos.cz)."""
    import random
    from urllib.parse import urlparse, urlunparse, urljoin

    cur = urlparse(page.url)
    current_host = cur.hostname or ""
    base_for_join = f"{cur.scheme}://{current_host}/"

    selectors = [
        'div.inzeraty.inzeratyflex h2.nadpis a[href^="/inzerat/"]',
        'div.inzeraty.inzeratyflex a.obrazek[href^="/inzerat/"]',
        'a[href^="/inzerat/"]'
    ]
    hrefs = []
    for sel in selectors:
        try:
            for el in page.query_selector_all(sel) or []:
                href = (el.get_attribute("href") or "").strip()
                if not href:
                    continue
                # Join relative link against the **current subdomain** base
                abs_url = urljoin(base_for_join, href)
                u = urlparse(abs_url)
                # Force host to current subdomain if it's a bazos domain
                if (u.hostname or "").endswith(("bazos.cz","bazos.sk","bazos.pl","bazos.at")) and u.hostname != current_host:
                    u = u._replace(netloc=current_host)
                    abs_url = urlunparse(u)
                hrefs.append(abs_url)
        except Exception:
            pass

    random.shuffle(hrefs)
    for url in hrefs[:30]:
        try:
            page.goto(url, timeout=30000, wait_until="load")
            accept_cookies(page)
            return True
        except Exception:
            continue

    # Try next page and repeat
    try:
        next_el = page.query_selector("div.strankovani a:last-child")
        href = next_el.get_attribute("href") if next_el else None
        if href:
            next_url = urljoin(base_for_join, href)
            u = urlparse(next_url)
            if (u.hostname or "").endswith(("bazos.cz","bazos.sk","bazos.pl","bazos.at")) and u.hostname != current_host:
                u = u._replace(netloc=current_host)
                next_url = urlunparse(u)
            page.goto(next_url, timeout=30000, wait_until="load")
            accept_cookies(page)
            return _click_random_listing(page)
    except Exception:
        pass

    return False


def type_slow(el, text: str, min_delay_ms=40, max_delay_ms=120):
    import random
    try:
        el.scroll_into_view_if_needed(timeout=1500)
        el.click(timeout=1500)
    except Exception:
        pass
    try: el.fill("")
    except Exception: pass
    for ch in str(text):
        try: el.type(ch, delay=random.randint(min_delay_ms, max_delay_ms))
        except Exception: pass

def find_phone_input(page: Page):
    scoped = [
        "#overlaytel input#teloverit",
        "#overlaytel input[name='teloverit']",
        "#overlaytel input[name*='tel' i]",
        "#overlaytel input[id*='tel' i]",
        "#overlaytel input[placeholder*='tel' i]",
        "#overlaytel input[placeholder*='telefon' i]",
        "#overlaytel input[type='text']",
    ]
    for sel in scoped:
        el = page.query_selector(sel)
        if el: return el
    for sel in ["input#teloverit","input[name='teloverit']","input[name*='tel' i]","input[id*='tel' i]","input[placeholder*='tel' i]","input[placeholder*='telefon' i]"]:
        el = page.query_selector(f"#overlaytel {sel}")
        if el: return el
    return None

def find_code_input(page: Page):
    scoped = [
        "#overlaytel input[name*='code' i]",
        "#overlaytel input[id*='code' i]",
        "#overlaytel input[placeholder*='kód' i]",
        "#overlaytel input[placeholder*='kod' i]",
        "#overlaytel input[type='text']",
    ]
    for sel in scoped:
        el = page.query_selector(sel)
        if el: return el
    for sel in ["input[name*='code' i]","input[id*='code' i]","input[placeholder*='kód' i]","input[placeholder*='kod' i]"]:
        el = page.query_selector(f"#overlaytel {sel}")
        if el: return el
    return None

def click_by_text(page: Page, words: List[str], timeout=1500) -> bool:
    for sel in ["button","input[type=button]","input[type=submit]","[role='button']","a"]:
        for el in page.query_selector_all(sel):
            try:
                txt = (el.inner_text() or el.get_attribute("value") or "").strip()
                if txt and _any_contains(txt, words):
                    el.click(timeout=timeout); return True
            except Exception: pass
    for w in words:
        try: page.locator(f"button:has-text('{w}')").first.click(timeout=timeout); return True
        except Exception: pass
        try: page.locator(f"a:has-text('{w}')").first.click(timeout=timeout); return True
        except Exception: pass
    return False



def click_show_phone_or_reply(page: Page) -> None:
    """
    Open phone overlay on listing (CZ/SK). Click inside #overlaytel only.
    """
    candidates = [
        "xpath=//*[@id='overlaytel']/td[2]/span/span",
        "css=#overlaytel td:nth-child(2) span span",
    ]
    for sel in candidates:
        try:
            el = page.locator(sel).first
            if el and el.count() > 0:
                el.scroll_into_view_if_needed(timeout=1500)
                el.click(timeout=1500)
                page.wait_for_selector("input#teloverit, input[name='teloverit']", timeout=2500)
                return
        except Exception:
            pass
    try:
        el = page.locator("#overlaytel :text('Zobrazit')").first
        if el and el.count() > 0:
            el.scroll_into_view_if_needed(timeout=1500)
            el.click(timeout=1500)
            return
    except Exception:
        pass



def save_cookies_txt(context: BrowserContext, folder: str, country: str) -> str:
    import json as _json, datetime as _dt
    from collections import OrderedDict as _OD
    os.makedirs(folder, exist_ok=True)
    # Read cookies (retry a bit to catch **bkod** specifically)
    cookies = []
    for _ in range(12):
        try:
            cookies = context.cookies()
        except Exception:
            cookies = []
        names = {c.get("name","") for c in (cookies or [])}
        if cookies and ("bkod" in names):
            break
        time.sleep(0.5)
    # Ensure success cookie present; if not, do not create a file
    names_final = {c.get("name","") for c in (cookies or [])}
    if "bkod" not in names_final:
        return ""
    def _same(val):
        if not val: return "unspecified"
        v = str(val).strip().lower()
        if v.startswith("strict"): return "strict"
        if v.startswith("lax"): return "lax"
        return "unspecified"
    out = []
    idx = 1
    for c in cookies:
        domain = c.get("domain","")
        host_only = False if str(domain).startswith(".") else True
        expires = c.get("expires", None)
        session = True if expires in (None, "", 0, -1) else False
        item = _OD()
        item["domain"] = domain
        if not session:
            try:
                item["expirationDate"] = float(expires)
            except Exception:
                pass
        item["hostOnly"] = host_only
        item["httpOnly"] = bool(c.get("httpOnly", False))
        item["name"] = c.get("name","")
        item["path"] = c.get("path","/")
        item["sameSite"] = _same(c.get("sameSite"))
        item["secure"] = bool(c.get("secure", False))
        item["session"] = session
        item["storeId"] = "0"
        item["value"] = c.get("value","")
        item["id"] = idx
        idx += 1
        out.append(item)
    stamp = _dt.datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")
    filename = os.path.join(folder, f"cookies-{country}-{stamp}.txt")
    payload = _json.dumps(out, ensure_ascii=False, indent=4)
    # Force CRLF for Notepad vertical view
    payload = payload.replace("\n", "\r\n")
    with open(filename, "w", encoding="utf-8", newline="") as f:
        f.write(payload)
        if not payload.endswith("\r\n"):
            f.write("\r\n")
    return filename
def random_category_click(page: Page, country: str) -> bool:
    """Open a random top-level category subdomain for CZ/SK (no parsing of homepage to avoid bad redirects)."""
    import random
    FALLBACK = {
        "CZ": [
            "https://auto.bazos.cz/","https://pc.bazos.cz/","https://mobil.bazos.cz/","https://reality.bazos.cz/",
            "https://prace.bazos.cz/","https://zvirata.bazos.cz/","https://dum.bazos.cz/","https://stroje.bazos.cz/",
            "https://elektro.bazos.cz/","https://sport.bazos.cz/","https://foto.bazos.cz/","https://hudba.bazos.cz/",
            "https://nabytek.bazos.cz/","https://obleceni.bazos.cz/","https://sluzby.bazos.cz/","https://ostatni.bazos.cz/",
        ],
        "SK": [
            "https://auto.bazos.sk/","https://pc.bazos.sk/","https://mobil.bazos.sk/","https://reality.bazos.sk/",
            "https://praca.bazos.sk/","https://zvierata.bazos.sk/","https://dom.bazos.sk/","https://stroje.bazos.sk/",
            "https://elektro.bazos.sk/","https://sport.bazos.sk/","https://foto.bazos.sk/","https://hudba.bazos.sk/",
            "https://nabytok.bazos.sk/","https://oblecenie.bazos.sk/","https://sluzby.bazos.sk/","https://ostatne.bazos.sk/",
        ],
    }
    urls = FALLBACK.get(country, FALLBACK["CZ"])[:]
    random.shuffle(urls)
    for url in urls:
        try:
            page.goto(url, timeout=30000, wait_until="load")
            accept_cookies(page)
            return True
        except Exception:
            continue
    return False



def random_ad_click(page: Page) -> bool:
    """Open a random ad from the listing. Preserves current subdomain."""
    import random
    from urllib.parse import urlparse, urljoin, urlunparse

    cur = urlparse(page.url)
    base = f"{cur.scheme}://{cur.hostname}/"
    current_host = cur.hostname or ""

    links = page.query_selector_all("a[href*='/inzerat/']") or []
    urls = []
    for l in links:
        try:
            href = (l.get_attribute("href") or "").strip()
            if not href or "/inzerat/" not in href:
                continue
            abs_url = urljoin(base, href)
            u = urlparse(abs_url)
            # Force same subdomain for bazos.*
            if (u.hostname or "").endswith(("bazos.cz","bazos.sk","bazos.pl","bazos.at")) and u.hostname != current_host:
                u = u._replace(netloc=current_host)
                abs_url = urlunparse(u)
            urls.append(abs_url)
        except Exception:
            pass

    random.shuffle(urls)
    for u in urls[:30]:
        try:
            page.goto(u, timeout=30000, wait_until="load")
            accept_cookies(page)
            return True
        except Exception:
            continue
    # Fallback: pagination 'Další'
    try:
        next_href = page.locator("div.strankovani a:last-child").first.get_attribute("href")
        if next_href:
            next_url = urljoin(base, next_href)
            uu = urlparse(next_url)
            if (uu.hostname or "").endswith(("bazos.cz","bazos.sk","bazos.pl","bazos.at")) and uu.hostname != current_host:
                uu = uu._replace(netloc=current_host)
                next_url = urlunparse(uu)
            page.goto(next_url, timeout=30000, wait_until="load")
            accept_cookies(page)
            return random_ad_click(page)
    except Exception:
        pass
    return False


def run_country_flow(country: str, phone: str, get_code_fn=None, headful: bool=False,
                     proxy: Optional[Union[dict,str]]=None, profile: Optional[dict]=None,
                     cycle_index: Optional[int]=None, **kwargs) -> Tuple[bool,str,str]:
    base_url = "https://www.bazos.cz" if country == "CZ" else "https://www.bazos.sk"
    retry_delay = int(load_runtime_config().get("retry_delay_sec", 60))
    reason = "error"
    cancel_watchdog = lambda reason="": None
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
            browser = pw.chromium.launch(**launch_args)
            ua, loc, tz, geo, _init_js = build_fingerprint(country)
            # FP viewport tied to profile
            _seed = _seed_from_profile(profile)
            _vw, _vh, _dpr, _aw, _ah = _pick_viewport_from_seed(_seed)
            context = browser.new_context(user_agent=ua, locale=loc, timezone_id=tz, geolocation=geo, permissions=['geolocation'], viewport={'width': int(_vw), 'height': int(_vh)}, device_scale_factor=float(_dpr))
            try:
                context.add_init_script(_init_js)
                context.add_init_script(_fp_extra_js(_seed, loc, _vw, _vh, _dpr, _aw, _ah))
            except Exception:
                pass
            try:
                def _block_assets(route, request):
                    if request.resource_type in ('image',):
                        return route.abort()
                    url_l = (request.url or '').lower()
                    if url_l.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg','.ico','.avif')):
                        return route.abort()
                    return route.continue_()
                context.route('**/*', _block_assets)
            except Exception:
                pass
            page = context.new_page()

            _sms_watchdog_event = None
            _sms_watchdog_thread = None

            def _cancel_sms_watchdog(reason: str = ""):
                nonlocal _sms_watchdog_event, _sms_watchdog_thread
                event = _sms_watchdog_event
                _sms_watchdog_event = None
                _sms_watchdog_thread = None
                if event:
                    event.set()
                if event and reason:
                    print(f"[BOT] sms_watchdog cancelled ({reason})", flush=True)
            cancel_watchdog = _cancel_sms_watchdog

            def _close_temp_browser_on_timeout():
                nonlocal page, context, browser
                print("[BOT] SMS_TIMEOUT_CLOSED (no code within 60s) → closing temp browser", flush=True)
                try:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = None
                    if context is not None:
                        try:
                            context.close()
                        except Exception:
                            pass
                        context = None
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
                        browser = None
                except Exception as exc:
                    print(f"[BOT] close temp browser failed: {exc}", flush=True)

            def _start_sms_watchdog(timeout: int = 60):
                nonlocal _sms_watchdog_event, _sms_watchdog_thread
                _cancel_sms_watchdog(reason="restart")
                stop_event = threading.Event()
                _sms_watchdog_event = stop_event

                def _runner():
                    if stop_event.wait(timeout):
                        return
                    _close_temp_browser_on_timeout()

                thread = threading.Thread(target=_runner, daemon=True)
                _sms_watchdog_thread = thread
                thread.start()
                print(f"[BOT] SMS_WAIT_START (t={timeout}s)", flush=True)

            # Guard для SMS-панели:
            #  • пока окно верификации не открыто — не вмешиваемся (первый шаг "zobraz číslo")
            #  • когда панель уже открыта и есть поле ввода — блокируем submit/клики,
            #    требуя корректный код: для #agentbutton достаточно любого непустого значения,
            #    для остальных разметок — 6–8 цифр.
            def _arm_sms_guard():
                if not SMS_GUARD_ENABLED:
                    return
                js = r"""
                (function(){
                  try{
                    if (window.__smsGuardArmedV2) return;
                    window.__smsGuardArmedV2 = true;
                    const DIGITS = /^\d{6,8}$/;
                    function verificationPanel(){
                      return document.querySelector('#overlaytel') ||
                             document.querySelector('.overlaytel') ||
                             document.querySelector('[data-test="verify-phone"], [data-testid="verify-phone"]');
                    }
                    function codeEl(){
                      const panel = verificationPanel();
                      if (!panel) return null;
                      const fields = Array.from(panel.querySelectorAll('input,textarea'));
                      const hit = fields.find(el=>{
                        if (!el || !el.offsetParent) return false;
                        const n=(el.name||'').toLowerCase();
                        const a=(el.autocomplete||'').toLowerCase();
                        const p=(el.placeholder||'').toLowerCase();
                        return (
                          a.includes('one-time') ||
                          /code|kod|kód|otp|token|sms|over|ověř/.test(n) ||
                          /code|kod|kód|sms|k[oó]d|код/.test(p) ||
                          n==='klic' || p.includes('klic') || p.includes('klíč')
                        );
                      });
                      return hit || null;
                    }
                    function codeOkDigits(){
                      const el = codeEl(); if(!el) return false;
                      const v=(el.value||'').trim();
                      return DIGITS.test(v);
                    }
                    function codeOkAny(){
                      const el = codeEl(); if(!el) return false;
                      const v=(el.value||'').trim();
                      return v.length > 0;
                    }
                    function hasAgentButton(){
                      return !!document.getElementById('agentbutton');
                    }
                    document.addEventListener('submit', (e)=>{
                      try{
                        if (!verificationPanel()) return;
                        if (!codeEl()) return;
                        const ok = hasAgentButton() ? codeOkAny() : codeOkDigits();
                        if (!ok){
                          e.preventDefault(); e.stopPropagation();
                        }
                      }catch(_){ }
                    }, true);
                    document.addEventListener('click', (e)=>{
                      try{
                        if (!verificationPanel()) return;
                        if (!codeEl()) return;
                        const btn = e.target && e.target.closest('#agentbutton');
                        const ok = btn ? codeOkAny() : (hasAgentButton() ? codeOkAny() : codeOkDigits());
                        if (!ok){
                          e.preventDefault(); e.stopPropagation();
                        }
                      }catch(_){ }
                    }, true);
                  }catch(_){ }
                })();
                """
                try:
                    page.add_init_script(js)
                except Exception:
                    pass
                try:
                    page.evaluate(js)
                except Exception:
                    pass

            _sms_request_fired = False
            _sms_request_status = None

            def _send_sms_once():
                """Trigger the SMS request exactly once, returning the status string."""
                nonlocal _sms_request_fired, _sms_request_status
                if _sms_request_fired:
                    return _sms_request_status or "already-sent"
                _sms_request_fired = True
                js = """
                () => {
                  function bySel(sel){ return document.querySelector(sel); }
                  const candidates = [
                    '#telbutton',
                    '#agentbutton',
                    'button#telbutton',
                    'button#agentbutton'
                  ];
                  for (const sel of candidates){
                    const el = bySel(sel);
                    if (!el) continue;
                    try { el.disabled = false; el.removeAttribute && el.removeAttribute('disabled'); } catch (_) {}
                    const oc = el.getAttribute && el.getAttribute('onclick');
                    if (oc){
                      try { eval(oc); return `eval:${sel}`; } catch (_) {}
                    }
                    try { el.click(); return `click:${sel}`; } catch (_) {}
                  }
                  const buttons = Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"]'));
                  const fallback = buttons.find(b => /odeslat/i.test((b.innerText || b.value || '')));
                  if (fallback){
                    try {
                      fallback.disabled = false;
                      const oc = fallback.getAttribute && fallback.getAttribute('onclick');
                      if (oc){
                        try { eval(oc); return 'eval:text=Odeslat'; } catch (_) {}
                      }
                      fallback.click();
                      return 'click:text=Odeslat';
                    } catch (_) {}
                  }
                  return 'no-button';
                }
                """
                try:
                    status = page.evaluate(js)
                except Exception:
                    status = 'failed-js'
                _sms_request_status = status
                return status

            def _wait_and_fill_sms(prev_code=None, timeout=60):
                selector = "input[autocomplete*='one-time' i],input[name*='code' i],input[type='tel'],input[type='text']"
                try:
                    page.wait_for_selector(selector, timeout=timeout * 1000)
                except Exception:
                    pass
                deadline = time.monotonic() + timeout
                code_val = None
                if get_code_fn:
                    print(f"[SMS WAIT] {phone}: waiting up to {timeout}s for code...", flush=True)
                while time.monotonic() < deadline and not code_val:
                    candidate = None
                    if get_code_fn:
                        try:
                            left = max(1, int(deadline - time.monotonic()))
                            chunk = min(30, left)
                            candidate = get_code_fn(timeout_sec=chunk)
                        except Exception:
                            candidate = None
                    if candidate:
                        candidate_str = str(candidate).strip()
                        if prev_code and candidate_str == str(prev_code).strip():
                            candidate = None
                        elif re.fullmatch(r"\d{6,8}", candidate_str):
                            code_val = candidate_str
                        else:
                            candidate = None
                    if not code_val:
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            time.sleep(min(1.0, remaining))
                if code_val and re.fullmatch(r"\d{6,8}", code_val):
                    try:
                        page.fill(selector, code_val)
                    except Exception:
                        ci_local = find_code_input(page)
                        if ci_local:
                            try:
                                ci_local.fill("")
                            except Exception:
                                pass
                            try:
                                ci_local.type(code_val, delay=35)
                            except Exception:
                                try:
                                    type_slow(ci_local, code_val)
                                except Exception:
                                    pass
                    try:
                        page.wait_for_function(
                            "(selector) => { const el = document.querySelector(selector); if (!el) return false; const v = (el.value || '').trim(); return /^\\d{6,8}$/.test(v); }",
                            selector,
                            timeout=10000,
                        )
                    except Exception:
                        pass
                if code_val:
                    _cancel_sms_watchdog(reason="code_received")
                return code_val

            _arm_sms_guard()

            # 1) open, accept cookies
            page.goto(base_url, timeout=45000, wait_until="load")
            accept_cookies(page)

            # 2) pick category and open random listing
            random_category_click(page, country)
            random_ad_click(page)
            accept_cookies(page)

            # 3) open phone overlay and request code
            click_show_phone_or_reply(page)
            time.sleep(5.0)

            tel_el = find_phone_input(page)
            if tel_el and phone:
                type_slow(tel_el, phone)

            # ОДИН раз отправляем запрос на SMS (идемпотентно, с дебаунсом внутри)
            try:
                status = _send_sms_once()
                print(f"[BAZOS] send-sms once: {status}", flush=True)
                _start_sms_watchdog(timeout=60)
                print("[LOG] sms wait started (60s from submit)", flush=True)
            except Exception:
                print("[BAZOS] send-sms once: exception", flush=True)

            # 4) get SMS code via callback — wait up to 60s (hard cap) and exit immediately if none
            prev_code = globals().get('_LAST_CODE_BY_PHONE', {}).get(phone)
            code = _wait_and_fill_sms(prev_code=prev_code, timeout=60)
            if code:
                globals().setdefault('_LAST_CODE_BY_PHONE', {})[phone] = code
            # If no code arrived within timeout, exit immediately with 'no_sms'
            if not code:
                _close_temp_browser_on_timeout()
                _cancel_sms_watchdog(reason="timeout_no_code")
                return False, "", "no_sms"

            ok = False
            if code:
                ci = find_code_input(page)
                if ci:
                    try:
                        current_val = (ci.input_value() or "").strip()
                    except Exception:
                        current_val = ""
                    if current_val != str(code):
                        try:
                            ci.fill("")
                            ci.press("Control+A")
                            ci.press("Backspace")
                        except Exception:
                            pass
                        type_slow(ci, str(code))
                    # Try to submit the code using a set of selectors first
                    # Повторные клики отключены: полагаемся на единичный запрос SMS и Enter по полю.
                    try:
                        ci.press("Enter")
                    except Exception:
                        pass
                    page.wait_for_timeout(300)
                    # After submit, wait up to 15s for success or error message
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        html_chk = (page.content() or "").lower()
                        if any(w in html_chk for w in ["ďakujem","dakujem","úspeš","úspěš","overen","ověřen","správa odoslaná","zpráva odeslána"]):
                            ok = True; reason = "success"; break
                        if any(w in html_chk for w in ["chybn","nespráv","neplat","error","chyba","nesprávny kód","kód není platný","neplatný kód"]):
                            ok = False; reason = "error"; break
                        time.sleep(1.0)
                    time.sleep(0.8)
            
            
            # DWELL: keep page alive up to 60s after submit; retry clicks; save cookies when success appears
            dwell_until = time.monotonic() + 5  # reduced from 60s
            saved_once = False
            while time.monotonic() < dwell_until:
                try:
                    page.wait_for_load_state('networkidle', timeout=1000)
                except Exception:
                    pass
                # success visible? (early save) — disabled to avoid double-save
                try:
                    _ = _is_success_phone_shown(page)  # noop
                except Exception:
                    pass
                # Повторные попытки автоклика отключены: ждём результат без доп. нажатий.
                try:
                    if page.locator("input[name='klic']").count() > 0:
                        try:
                            page.locator("input[name='klic']").first.press('Enter')
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(1.0)# 5) check result (patched)
            html_raw = (page.content() or "")
            html = html_raw.lower()
            # input code present?
            try:
                code_input_exists = page.locator("input[name='klic']").count() > 0
            except Exception:
                code_input_exists = False
            # visible phone anchor
            phone_txt = ""
            try:
                tel_el = page.locator("a.teldetail").first
                if tel_el:
                    phone_txt = tel_el.inner_text() or ""
            except Exception:
                pass
            phone_digits = "".join(ch for ch in phone_txt if ch.isdigit())
            ok = (len(phone_digits) >= 6) and (not code_input_exists)
            reason = "success" if ok else "error"

            cookie_file = ""
            folder = os.path.join(os.getcwd(), "BazosCookies", FOLDER_NAMES.get(country, country))
            if ok:
                # wait 5s AFTER success before reading cookies
                time.sleep(5.0)
                cookie_file = save_cookies_txt(context, folder, country)
            else:
                try:
                    failed_folder = folder  # FAILED disabled
                    cf = save_cookies_txt(context, failed_folder, country)
                    if cf:
                        cookie_file = cf
                except Exception:
                    pass

            # ensure we save before closing, keep page briefly on success
            try:
                if ok and not cookie_file:
                    folder = os.path.join(os.getcwd(), "BazosCookies", FOLDER_NAMES.get(country, country))
                    cookie_file = save_cookies_txt(context, folder, country)
            # removed extra sleep after saving to close faster
            except Exception:
                pass

            _cancel_sms_watchdog(reason="finalize")
            context.close(); browser.close()
            return ok, cookie_file, reason
    except Exception as e:
        try:
            cancel_watchdog(reason="exception")
        except Exception:
            pass
        print(f"[run_country_flow] error: {e}")
        return False, "", "proxy_error"


def _save_cookies_vertical(cookies: list, filepath: str):
    """
    Save cookies as vertical lines: name=value per line.
    Uses CRLF newlines for compatibility with Notepad.
    """
    try:
        lines = []
        for c in cookies or []:
            name = c.get("name", "")
            value = c.get("value", "")
            lines.append(f"{name}={value}")
        # if empty, don't create file
        if not lines:
            return False
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8", newline="\\r\\n") as f:
            f.write("\\r\\n".join(lines) + "\\r\\n")
        return True
    except Exception as e:
        try:
            # fall back to JSON pretty if something goes wrong
            with open(filepath, "w", encoding="utf-8", newline="\\r\\n") as f:
                import json
                f.write(_save_cookies_vertical(cookies, out_path))
            return True
        except Exception:
            return False



def _save_cookies_netscape(cookies: list, filepath: str):
    """
    Optional Netscape format writer (one cookie per line).
    """
    try:
        lines = [
            "# Netscape HTTP Cookie File",
            "# Generated by BazosAutoReg",
            ""
        ]
        for c in cookies or []:
            domain = c.get("domain", "")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            exp = int(c.get("expires") or 0) if c.get("expires") not in (None, "", -1) else 0
            name = c.get("name", "")
            value = c.get("value", "")
            lines.append("\\t".join([domain, include_subdomains, path, secure, str(exp), name, value]))
        if len(lines) <= 3:
            return False
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8", newline="\\r\\n") as f:
            f.write("\\r\\n".join(lines) + "\\r\\n")
        return True
    except Exception:
        return False



async def _soft_settle_after_confirm(page, timeout_ms: int = 8000, extra_ms: int = 1200):
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(extra_ms)
    except Exception:
        pass
