
# proxy_utils.py
from __future__ import annotations
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, unquote
from typing import Any, Dict, Optional

SUPPORTED_SCHEMES = {"http", "https", "socks5", "socks4"}

BASE_DIR = Path(__file__).resolve().parent
ROTATION_STATE_FILE = BASE_DIR / "proxy_rotation_state.json"

COUNTRY_PROXY_FILES = {
    "CZ": BASE_DIR / "proxies_cz.txt",
    "SK": BASE_DIR / "proxies_sk.txt",
    # future: "PL", "DE", etc.
}

def parse_proxy_line(line: str) -> Dict[str, str]:
    """
    Accepts formats:
      - scheme://username:password@host:port
      - scheme://host:port (no auth)
      - socks5h://... (converted to socks5)
    Returns dict: {"server": "scheme://host:port", "username": "...", "password": "...", "raw": original}
    """
    raw = (line or "").strip()
    if not raw:
        return {}
    # normalize separators
    raw = raw.replace("\\t", "").strip()
    # Ensure scheme
    if "://" not in raw:
        # assume http
        raw = "http://" + raw

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme == "socks5h":
        scheme = "socks5"
    if scheme not in SUPPORTED_SCHEMES:
        # fallback to http
        scheme = "http"
    host = parts.hostname or ""
    port = parts.port or 0
    server = f"{scheme}://{host}:{port}"

    username = unquote(parts.username) if parts.username else None
    password = unquote(parts.password) if parts.password else None

    return {"server": server, "username": username, "password": password, "raw": line.strip()}

def derive_country_from_proxy(proxy: Dict[str, str]) -> Optional[str]:
    """
    Tries to read country code from username/host tokens like:
      region-cz, country=cz, cc_cz, _cz_
    Returns "CZ"/"SK"/"PL"/"DE" or None.
    """
    import re
    text = " ".join([proxy.get("raw",""), proxy.get("server","")]).lower()
    # common patterns
    candidates = []
    for pat in (r"region[-_=]([a-z]{2})", r"country[-_=]([a-z]{2})", r"\\b([a-z]{2})\\b"):
        m = re.search(pat, text)
        if m:
            candidates.append(m.group(1).upper())
    for cc in candidates:
        if cc in {"CZ","SK","PL","DE"}:
            return cc
    return None


def load_proxies_for_country(country: str):
    country = country.upper()
    path = COUNTRY_PROXY_FILES.get(country)
    if not path:
        raise RuntimeError(f"Нет файла с прокси для страны {country}")
    if not path.exists():
        raise RuntimeError(f"Файл с прокси для {country} не найден: {path}")
    with path.open("r", encoding="utf-8") as f:
        proxies = [ln.strip() for ln in f if ln.strip()]
    if not proxies:
        raise RuntimeError(f"Файл {path} пустой — нет прокси для {country}")
    return proxies


def load_rotation_state() -> Dict[str, Any]:
    if not ROTATION_STATE_FILE.exists():
        return {}
    try:
        with ROTATION_STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rotation_state(state: Dict[str, Any]) -> None:
    with ROTATION_STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_next_proxy_for_country(country: str) -> str:
    """
    Возвращает СЛЕДУЮЩУЮ строку прокси для указанной страны (CZ/SK) по циклу.
    Состояние (последний индекс) хранится в proxy_rotation_state.json,
    чтобы между перезапусками программы прокси не начинался с первого.
    """
    country = country.upper()
    proxies = load_proxies_for_country(country)

    state = load_rotation_state()
    country_state = state.get(country, {})
    last_index = country_state.get("last_index", -1)

    next_index = (last_index + 1) % len(proxies)

    country_state["last_index"] = next_index
    state[country] = country_state
    save_rotation_state(state)

    return proxies[next_index]
