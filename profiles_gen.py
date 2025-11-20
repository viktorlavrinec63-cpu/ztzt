
# profiles_gen.py
from __future__ import annotations
import random

# A small pool of plausible Chrome versions (desktop Windows 10/11)
_CHROME_VERS = ["121.0.6167.85","122.0.6261.94","123.0.6312.86","124.0.6367.91","125.0.6422.112","126.0.6478.55"]
_OS_TOKENS = ["Windows NT 10.0; Win64; x64","Windows NT 10.0; Win64; x64","Windows NT 10.0; Win64; x64","Windows NT 10.0; Win64; x64","Windows NT 11.0; Win64; x64"]

_LANGS = {
    "CZ": ("cs-CZ","Europe/Prague"),
    "SK": ("sk-SK","Europe/Bratislava"),
    "PL": ("pl-PL","Europe/Warsaw"),
    "DE": ("de-DE","Europe/Berlin"),
}

_VIEWPORTS = [
    {"width":1920,"height":1080,"deviceScaleFactor":1.0},
    {"width":1600,"height":900,"deviceScaleFactor":1.0},
    {"width":1536,"height":864,"deviceScaleFactor":1.0},
    {"width":1366,"height":768,"deviceScaleFactor":1.0},
    {"width":1280,"height":800,"deviceScaleFactor":1.0},
]

def _ua_for(lang: str) -> str:
    ver = random.choice(_CHROME_VERS)
    os_tok = random.choice(_OS_TOKENS)
    return f"Mozilla/5.0 ({os_tok}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36"

def accept_language_chain(locale: str) -> str:
    lang = locale.split("-")[0]
    return f"{locale},{lang};q=0.9,en;q=0.8"

def generate_profile(strategy: str, country_hint: str | None) -> dict:
    """
    strategy: 'country_tuned' | 'diverse_random'
    country_hint: 'CZ'|'SK'|'PL'|'DE' or None
    Returns dict with locale, timezoneId, userAgent, viewport, colorScheme, isMobile, hasTouch, acceptLanguage.
    """
    p = {}
    if strategy == "country_tuned" and country_hint in _LANGS:
        loc, tz = _LANGS[country_hint]
    else:
        # diverse_random: pick a random from supported languages
        loc, tz = random.choice(list(_LANGS.values()))
    p["locale"] = loc
    p["timezoneId"] = tz
    p["userAgent"] = _ua_for(loc)
    p["viewport"] = random.choice(_VIEWPORTS)
    p["colorScheme"] = random.choice(["light","dark"])
    p["isMobile"] = False
    p["hasTouch"] = False
    p["acceptLanguage"] = accept_language_chain(loc)
    # geolocation left for net_geo auto-match phase
    return p
