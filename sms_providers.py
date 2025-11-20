# sms_providers.py (Variant B - with stubs + OnlineSim working)
from __future__ import annotations
from pathlib import Path
import time, requests
import subprocess
from requests.exceptions import SSLError, ProxyError, ConnectTimeout, ReadTimeout, ConnectionError

class OnlineSimProxyError(Exception): pass
from typing import Tuple, Optional, Dict, Any

DEFAULT_COUNTRY_MAP = {"CZ": 420, "SK": 421, "PL": 48, "DE": 49}

class SmsProviderBase:
    def request_number(self, country: str) -> Tuple[str, str]:
        """Return (activation_id, phone_number)."""
        raise NotImplementedError

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        """Wait for SMS code text; return just the numeric code when possible."""
        raise NotImplementedError

    def request_new_code(self, activation_id: str, country: str) -> None:
        """Ask the provider to resend/renew the SMS code (optional)."""
        pass

    def finalize(self, activation_id: str, success: bool = True, banned: bool = False) -> None:
        """Mark activation as complete; optionally report ban state."""
        pass


# --------------------------- STUB PROVIDERS ---------------------------
class ManualSmsProvider(SmsProviderBase):
    """Manual/Debug provider: asks the user to input phone and code in console."""
    def request_number(self, country: str) -> Tuple[str, str]:
        phone = input(f"[manual] Введите номер телефона для {country}: ").strip()
        return ("manual-activation", phone)

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        code = input("[manual] Введите код из СМС: ").strip()
        return code

    def request_new_code(self, activation_id: str, country: str) -> None:
        print("[manual] Запрос нового кода — (WS no-op)")

    def finalize(self, activation_id: str, success: bool = True, banned: bool = False) -> None:
        print(f"[manual] finalize: success={success}, banned={banned}")


class GenericSmsProvider(SmsProviderBase):
    """Generic placeholder in case of wrong provider name in config."""
    def request_number(self, country: str) -> Tuple[str, str]:
        raise RuntimeError("GenericSmsProvider: провайдер не настроен")

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        raise RuntimeError("GenericSmsProvider: провайдер не настроен")


class ProviderA(SmsProviderBase):
    """Skeleton for another provider; implement by analogy with OnlineSimProvider."""
    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")

    def request_number(self, country: str) -> Tuple[str, str]:
        raise NotImplementedError("ProviderA не реализован")

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        raise NotImplementedError("ProviderA не реализован")


class ProviderB(ProviderA):
    """Same stub for an alternative provider."""
    pass


# --------------------------- OnlineSim Provider ---------------------------
class OnlineSimProvider(SmsProviderBase):
    """
    Minimal OnlineSim integration using the classic HTTP API:
      - /api/getNum.php            -> request number -> tzid
      - /api/getState.php          -> poll for number + sms
      - /api/setOperationRevise.php -> request new code
      - /api/setOperationOk.php     -> finalize (optionally with ban=1)
    """
    def __init__(self, api_key: str, base_url: str, service: str,
                 country_map: Dict[str, int] | None = None,
                 poll_interval_sec: int = 5):
        self.api_key = api_key
        self.base_url = (base_url or "https://onlinesim.io").rstrip("/")
        self.service = service
        cm = dict(DEFAULT_COUNTRY_MAP)
        if country_map:
            cm.update({k.upper(): v for k, v in country_map.items()})
        self.country_map = cm
        self.poll = max(2, int(poll_interval_sec))
        self._s = requests.Session()
        self._proxies = None  # requests proxies dict per cycle
        self._s.trust_env = False

    def set_http_proxy_from_parsed(self, proxy_info: Dict[str,str] | None):
        """Bind OnlineSim HTTP calls to the same proxy as the current pair.
        Expects a dict from proxy_utils.parse_proxy_line: {server, username?, password?}.
        """
        if not proxy_info or not proxy_info.get("server"):
            self._proxies = None
            return
        srv = str(proxy_info.get("server"))
        # normalize socks5h -> socks5 for requests
        if srv.startswith("socks5h://"):
            srv = "socks5://" + srv[len("socks5h://"):]
        if srv.startswith("socks4a://"):
            srv = "socks4://" + srv[len("socks4a://"):]
        # inject credentials in URL if present
        user = proxy_info.get("username") or ""
        pwd = proxy_info.get("password") or ""
        if user:
            # split scheme://host:port
            try:
                scheme, rest = srv.split("://", 1)
            except ValueError:
                scheme, rest = "http", srv
            auth = f"{user}:{pwd}@" if pwd else f"{user}@"
            srv_auth = f"{scheme}://{auth}{rest}"
        else:
            srv_auth = srv
        # Use the same endpoint for http and https
        self._proxies = {"http": srv_auth, "https": srv_auth}

    def _get_proxies(self):
        return self._proxies

    # --- HTTP helper
    def _get(self, path: str, **params) -> Dict[str, Any] | list:
        p = {"apikey": self.api_key, **params}
        url = self.base_url + path
        try:
            r = self._s.get(url, params=p, timeout=30, proxies=self._get_proxies())
            r.raise_for_status()
        except (SSLError, ProxyError, ConnectTimeout, ReadTimeout, ConnectionError) as e:
            raise OnlineSimProxyError(str(e))
        try:
            return r.json()
        except Exception:
            import json as _json
            return _json.loads(r.text)

    # --- API
    def request_number(self, country: str) -> Tuple[str, str]:
        cu = (country or "CZ").upper()
        code = self.country_map.get(cu, self.country_map["CZ"])
        # 1) request tzid
        data = self._get("/api/getNum.php", country=code, service=self.service, lang="en")
        tzid = None
        if isinstance(data, dict):
            tzid = data.get("tzid") or data.get("Tzid") or data.get("tz_id")
        if not tzid:
            raise RuntimeError(f"OnlineSim getNum failed: {data}")

        # 2) try to fetch the phone number
        t0 = time.time()
        while time.time() - t0 < 60:
            st = self._get("/api/getState.php", tzid=tzid, lang="en")
            item = st[0] if isinstance(st, list) and st else st
            number = (item.get("number") if isinstance(item, dict) else None) or \
                     (item.get("tel") if isinstance(item, dict) else None)
            if number:
                return (str(tzid), str(number))
            time.sleep(self.poll)

        raise TimeoutError(f"Timeout getting phone number (tzid={tzid})")

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        tzid = activation_id
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout_sec:
            st = self._get("/api/getState.php", tzid=tzid, lang="en")
            item = st[0] if isinstance(st, list) and st else st
            code_text = None
            if isinstance(item, dict):
                for k in ("sms", "msg", "message", "code", "text"):
                    if item.get(k):
                        code_text = str(item[k])
                        break
            last = item
            if code_text:
                # Extract 4–8 digit code if present
                import re
                m = re.search(r"(\\d{4,8})", code_text)
                return m.group(1) if m else code_text
            time.sleep(self.poll)

        raise TimeoutError(f"Timeout waiting for SMS (tzid={tzid}); last={last}")

    def request_new_code(self, activation_id: str, country: str) -> None:
        self._get("/api/setOperationRevise.php", tzid=activation_id, lang="en")

    def finalize(self, activation_id: str, success: bool = True, banned: bool = False) -> None:
        params = {"tzid": activation_id, "lang": "en"}
        if banned:
            params["ban"] = 1
        # API завершается Ok независимо от success — логика success используется в приложении
        self._get("/api/setOperationOk.php", **params)


class SmsHubProvider(SmsProviderBase):
    def __init__(self, api_key: str, service: str = "cb",
                 base_url: str = "https://smshub.org/stubs/handler_api.php",
                 country_map: Dict[str, int] | None = None,
                 operator: str = "any",
                 poll_interval_sec: int = 5,
                 max_price: int | None = None,
                 random_issue: bool = False):
        self.api_key = api_key
        self.base_url = base_url
        self.service = service or "cb"
        cm = {"CZ": 63, "SK": 141, "PL": 15, "DE": 43}
        if country_map:
            cm.update({k.upper(): int(v) for k, v in country_map.items()})
        self.country_map = cm
        self.operator = operator or "any"
        self.poll = max(2, int(poll_interval_sec))
        self._s = requests.Session()
        self._s.trust_env = False
        self._proxies = None
        self.max_price = (int(max_price) if (max_price is not None and str(max_price).isdigit()) else None)
        self.random_issue = bool(random_issue)

    def set_http_proxy_from_parsed(self, proxy_info: Dict[str, str] | None):
        if not proxy_info or not proxy_info.get("server"):
            self._proxies = None
            return
        srv = str(proxy_info.get("server"))
        if srv.startswith("socks5h://"):
            srv = "socks5://" + srv[len("socks5h://"):]
        if srv.startswith("socks4a://"):
            srv = "socks4://" + srv[len("socks4a://"):]
        user = proxy_info.get("username") or ""
        pwd = proxy_info.get("password") or ""
        if user:
            try:
                scheme, rest = srv.split("://", 1)
            except ValueError:
                scheme, rest = "http", srv
            auth = f"{user}:{pwd}@" if pwd else f"{user}@"
            srv_auth = f"{scheme}://{auth}{rest}"
        else:
            srv_auth = srv
        self._proxies = {"http": srv_auth, "https": srv_auth}

    def _get_proxies(self):
        return self._proxies

    def _call(self, **params) -> str:
        p = {"api_key": self.api_key, **params}
        try:
            r = self._s.get(self.base_url, params=p, timeout=30, proxies=self._get_proxies())
            r.raise_for_status()
        except (SSLError, ProxyError, ConnectTimeout, ReadTimeout, ConnectionError) as e:
            raise OnlineSimProxyError(str(e))
        return r.text.strip()

    def request_number(self, country: str) -> Tuple[str, str]:
        cc = self.country_map.get(country.upper())
        if cc is None:
            raise ValueError(f"Unsupported country for SMSHub: {country}")
        params = {"action":"getNumber","service":self.service,"country":cc,"operator":self.operator}
        if self.max_price is not None and self.max_price > 0:
            params["maxPrice"] = self.max_price
        if self.random_issue:
            params["random"] = 1
        txt = self._call(**params)
        if not txt.startswith("ACCESS_NUMBER:"):
            raise RuntimeError(f"SMSHub getNumber failed: {txt}")
        _, act_id, number = txt.split(":", 2)
        return act_id, number

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        import time, re
        deadline = time.time() + max(1, int(timeout_sec))
        last = ""
        while time.time() < deadline:
            txt = self._call(action="getStatus", id=activation_id)
            last = txt
            if txt.startswith("STATUS_OK:"):
                code = txt.split(":", 1)[1]
                m = re.search(r"(\\d{4,8})", code)
                return m.group(1) if m else code
            if txt.startswith("STATUS_WAIT_RETRY"):
                pass
            elif txt.startswith("STATUS_CANCEL"):
                raise RuntimeError("activation cancelled")
            time.sleep(self.poll)
        raise TimeoutError(f"Timeout waiting for SMS (id={activation_id}); last={last}")

    def request_new_code(self, activation_id: str, country: str) -> None:
        self._call(action="setStatus", status=3, id=activation_id)

    def finalize(self, activation_id: str, success: bool = True, banned: bool = False) -> None:
        status = 6 if success else 8
        self._call(action="setStatus", status=status, id=activation_id)

# -------- SecondNo via Portable Chrome + Extension (HTTP bridge) --------
import threading, http.server, socketserver, urllib.parse, time, uuid
from queue import Queue, Empty

class _BridgeState:
    def __init__(self):
        self.cmd_queue = Queue()
        self.waiters = {}  # requestId -> (event, result)

BRIDGE_HTML_OK = b'{"ok":true}'

class _BridgeHandler(http.server.BaseHTTPRequestHandler):
    state: "_BridgeState" = None  # type: ignore

    def _send_json(self, obj):
        import json as _json
        data = _json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/dequeue":
            wait = 20
            try:
                qs = urllib.parse.parse_qs(parsed.query or "")
                wait = int(qs.get("wait", [20])[0])
            except Exception:
                pass
            try:
                cmd = self.state.cmd_queue.get(timeout=max(1, wait))
                self._send_json(cmd)
            except Empty:
                self._send_json({"ok": False, "empty": True})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            obj = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            obj = {}
        if self.path == "/enqueue":
            self.state.cmd_queue.put(obj)
            self._send_json({"ok": True})
        elif self.path == "/event":
            rid = obj.get("requestId")
            if rid and rid in self.state.waiters:
                ev, slot = self.state.waiters[rid]
                slot["result"] = obj
                ev.set()
            self._send_json({"ok": True})
        else:
            self.send_response(404); self.end_headers()

class _BridgeServer:
    def __init__(self, port: int):
        self.port = int(port)
        self.state = _BridgeState()
        self.thread = None
        self.httpd = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        handler = _BridgeHandler
        handler.state = self.state
        class _Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True
        self.httpd = _Threaded(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        try:
            if self.httpd: self.httpd.shutdown()
        except Exception:
            pass

    def request(self, action: str, params: dict, timeout: int = 60) -> dict:
        rid = str(uuid.uuid4())
        ev = threading.Event()
        slot = {}
        self.state.waiters[rid] = (ev, slot)
        self.state.cmd_queue.put({"action": action, "params": params or {}, "requestId": rid})
        ok = ev.wait(timeout=max(1, timeout))
        self.state.waiters.pop(rid, None)
        if not ok:
            raise RuntimeError(f"bridge timeout for {action}")
        return slot.get("result") or {}

class SecondNoProvider(SmsProviderBase):

    def fill_email(self, value, selector="input[placeholder='Email']"):
        try:
            self._bridge.request("setValue", {"selector": selector, "value": value}, timeout=15)
        except Exception as e:
            print("[SecondNoProvider] setValue failed:", e)

    def __init__(self, chrome_portable_dir: str="GoogleChromePortable",
                 ext_dir: str="chrome_ext/secondno_bridge",
                 port: int = 8765, start_timeout: int = 10):
        self.chrome_dir = Path(chrome_portable_dir)
        self.ext_dir = Path(ext_dir)
        self.port = int(port)
        self.start_timeout = int(start_timeout)
        self._bridge = _BridgeServer(self.port)
        self._bridge.start()
        self.proc = None

    def _start_chrome(self):
        if self.proc and self.proc.poll() is None:
            return
        chrome_bin = None
        for name in ("chrome.exe","GoogleChromePortable.exe","ChromePortable.exe"):
            p = self.chrome_dir / name
            if p.exists():
                chrome_bin = str(p); break
        if not chrome_bin:
            raise RuntimeError("ChromePortable not found in " + str(self.chrome_dir))
        profile = self.chrome_dir / "profile_secondno"
        profile.mkdir(exist_ok=True)
        cmd = [
            chrome_bin,
            f"--user-data-dir={str(profile)}",
            f"--load-extension={str(self.ext_dir)}",
            "--no-first-run","--no-default-browser-check",
            "--disable-popup-blocking"
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Give extension time to start polling
        time.sleep(self.start_timeout)

    def request_number(self, country: str) -> Tuple[str, str]:
        self._start_chrome()
        # Ensure navigation to site
        self._bridge.request("navigate", {}, timeout=20)
        time.sleep(1.0)
        self.fill_email('1234')
        resp = self._bridge.request("requestNumber", {"country": country}, timeout=60)
        if resp.get("event") != "onNumber":
            raise RuntimeError(f"SecondNo requestNumber failed: {resp}")
        return resp.get("activation_id") or "secondno-"+str(int(time.time())), resp.get("number")

    def wait_for_sms(self, activation_id: str, timeout_sec: int = 180) -> str:
        resp = self._bridge.request("getSms", {"activation_id": activation_id}, timeout=max(10, timeout_sec))
        if resp.get("event") != "onSms":
            raise RuntimeError(f"SecondNo getSms failed: {resp}")
        return resp.get("code")

    def request_new_code(self, activation_id: str, country: str) -> None:
        # optional implementation
        pass

    def finalize(self, activation_id: str, success: bool = True, banned: bool = False) -> None:
        try:
            self._bridge.request("finalize", {"activation_id": activation_id, "success": success, "banned": banned}, timeout=10)
        except Exception:
            pass
    

class WsExternalProvider:
    """No-op provider for WS mode (we control Chrome via extension; no internal bridge)."""
    def __init__(self): pass
    def start(self): pass
    def stop(self): pass
    def get_number(self, *a, **kw): return None
    def get_code(self, *a, **kw): return None

