
# net_geo.py
from __future__ import annotations
import requests

def get_ip_via_proxy(proxy: str, timeout: int = 15) -> str:
    """Detect outward IP by querying ipify through the given proxy."""
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=timeout)
    r.raise_for_status()
    return r.json().get("ip","")

def geolocate_ip(ip: str, timeout: int = 15) -> dict:
    """
    Use ipwho.is (no key) to geolocate IP.
    Returns dict with keys: country_code, city, latitude, longitude, timezone.
    """
    if not ip:
        return {}
    r = requests.get(f"https://ipwho.is/{ip}", timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not j.get("success", False):
        return {}
    return {
        "country_code": j.get("country_code"),
        "city": j.get("city"),
        "latitude": j.get("latitude"),
        "longitude": j.get("longitude"),
        "timezone": (j.get("timezone") or {}).get("id") if isinstance(j.get("timezone"), dict) else j.get("timezone")
    }

def lang_for_country(country_code: str) -> str:
    cc = (country_code or "").upper()
    mapping = {
        "CZ": "cs-CZ",
        "SK": "sk-SK",
        "PL": "pl-PL",
        "DE": "de-DE",
        "AT": "de-AT",
        "HU": "hu-HU",
        "US": "en-US",
        "GB": "en-GB",
        "NL": "nl-NL",
        "FR": "fr-FR",
        "ES": "es-ES",
        "IT": "it-IT"
    }
    return mapping.get(cc, "en-US")

def accept_language_chain(locale: str) -> str:
    # Build a reasonable Accept-Language chain from locale
    if not locale:
        return "en-US,en;q=0.9"
    lang = locale.split("-")[0]
    return f"{locale},{lang};q=0.9,en;q=0.8"
