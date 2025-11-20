
# proxy_utils.py
from __future__ import annotations
from urllib.parse import urlsplit, unquote
from typing import Optional, Dict

SUPPORTED_SCHEMES = {"http", "https", "socks5", "socks4"}

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
