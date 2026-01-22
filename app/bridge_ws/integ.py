import asyncio
import json
import os
import subprocess
import threading
import re
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Dict, Optional


def log(msg: str) -> None:
    print(f"[BRIDGE {datetime.now().strftime('%H:%M:%S')}] {msg}")


try:
    import websockets
except Exception:  # pragma: no cover - propagated to caller
    raise


def _make_rid() -> str:
    return f"rid-{uuid.uuid4().hex}"


def _normalize_pl(raw: Any) -> str:
    """Normalize phone number coming from 2nd-no payloads."""
    if raw is None:
        return ""
    text = str(raw)
    if not text.strip():
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return ""
    if digits.startswith("0048"):
        digits = digits[2:]
    if digits.startswith("48"):
        normalized = digits
    elif len(digits) == 9:
        normalized = "48" + digits
    elif digits.startswith("0") and len(digits) >= 9:
        normalized = "48" + digits.lstrip("0")
    else:
        normalized = digits
    return "+" + normalized.lstrip("+")


class BridgeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self.server: Any = None
        self.clients: set[Any] = set()
        self.queue: Optional[asyncio.Queue] = None
        self.events: Optional[asyncio.Queue] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self.on_external_code: Optional[Callable[[str], None]] = None
        self.on_external_number: Optional[Callable[[str], None]] = None
        self._latest_number: Optional[str] = None
        self._latest_code: Optional[str] = None
        self._last_code: Optional[str] = None
        self._last_code_ts: float = 0.0
        self._dedupe_window_ms: int = 30_000
        self._latest_number_path = Path("logs/latest_external_number.txt")
        self._latest_code_path = Path("logs/latest_external_code.txt")
        for path in (self._latest_number_path, self._latest_code_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._extension_ready = threading.Event()
        self._last_ping_ts: float = time.time()
        self._alive_timeout: float = 45.0
        self.append_log: Optional[Callable[[str], None]] = None

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        return self._ready.wait(timeout)

    def _log_gui(self, message: str) -> None:
        cb = getattr(self, "append_log", None)
        if callable(cb):
            try:
                cb(message)
                return
            except Exception:
                pass
        try:
            log(message)
        except Exception:
            pass

    def ws_send(self, payload: Dict[str, Any]) -> None:
        if not self.loop:
            raise RuntimeError("bridge loop not running")
        if self.queue is None:
            raise RuntimeError("bridge queue не инициализирована")

        async def _dispatch() -> None:
            assert self.queue is not None
            await self.queue.put(payload)

        fut = asyncio.run_coroutine_threadsafe(_dispatch(), self.loop)
        fut.result()

    def start_login_watch(self) -> None:
        try:
            self.ws_send({"type": "start_login_watch"})
            self._log_gui("[2ND] login-watch started (15s reload until /auth/login)")
        except Exception as e:
            self._log_gui(f"[2ND] login-watch start failed: {e}")

    def stop_login_watch(self) -> None:
        try:
            self.ws_send({"type": "stop_login_watch"})
            self._log_gui("[2ND] login-watch stopped")
        except Exception as e:
            self._log_gui(f"[2ND] login-watch stop failed: {e}")

    def request_close_browser_window(self) -> None:
        try:
            self.ws_send({"type": "close_active_tab_and_window"})
            self._log_gui("[2ND] requested extension to close window")
        except Exception as e:
            self._log_gui(f"[2ND] close window request failed: {e}")

    async def _send_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        assert self.queue is not None
        while True:
            cmd = await self.queue.get()
            try:
                if isinstance(cmd, dict) and cmd.get("type") == "start_number_registration":
                    log(f"[-> EXT] start_number_registration rid={cmd.get('rid')}")
                else:
                    log(f"[-> EXT] {cmd.get('type') or cmd}")
                await ws.send(json.dumps(cmd))
            except Exception as exc:
                log(f"send failed: {exc}")
                # return command to queue so next client can retry
                try:
                    await self.queue.put(cmd)
                except Exception:
                    pass
                raise

    async def _recv_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        assert self.events is not None
        while True:
            msg = await ws.recv()
            try:
                obj = json.loads(msg)
            except Exception:
                continue
            if isinstance(obj, dict):
                ev = (obj.get("event") or obj.get("type") or "").lower()
                if ev == "ping":
                    self._last_ping_ts = time.time()
                    try:
                        await ws.send(json.dumps({"type": "pong"}))
                    except Exception:
                        pass
                    continue
                if ev == "external_number":
                    payload = obj.get("data") or obj.get("payload") or {}
                    rid = obj.get("rid") or payload.get("rid")
                    raw_number = (
                        payload.get("number")
                        or payload.get("phone")
                        or obj.get("number")
                        or obj.get("value")
                        or obj.get("phone")
                    )
                    number = _normalize_pl(raw_number or "")
                    if number:
                        self._latest_number = number
                        try:
                            self._latest_number_path.write_text(number, encoding="utf-8")
                        except Exception:
                            pass
                        data = {
                            "event": "external_number",
                            "number": number,
                            "value": number,
                            "rid": rid,
                            "raw": obj,
                        }
                        await self.events.put(data)
                        fut = None
                        if rid:
                            fut = self._pending.pop(rid, None)
                        if fut is None and self._pending:
                            # fallback: take any pending future (legacy bridge may omit rid)
                            try:
                                rid2, fut2 = next(iter(self._pending.items()))
                            except Exception:
                                rid2, fut2 = None, None
                            if fut2:
                                self._pending.pop(rid2, None)
                                rid = rid or rid2
                                fut = fut2
                        if fut and not fut.done():
                            fut.set_result({"number": number, "value": number, "rid": rid, "raw": obj})
                        if callable(self.on_external_number) and number:
                            try:
                                self.on_external_number(str(number))
                            except Exception as exc:
                                log(f"on_external_number error: {exc}")
                elif ev == "external_code":
                    payload = obj.get("data") or obj.get("payload") or {}
                    rid = obj.get("rid") or payload.get("rid")
                    raw_code = (
                        payload.get("code")
                        or payload.get("value")
                        or payload.get("sms")
                        or payload.get("text")
                        or obj.get("code")
                        or obj.get("value")
                    )
                    if raw_code is not None:
                        code = str(raw_code)
                        self._latest_code = code
                        log(f"external_code received: rid={rid}")
                        data = {"event": "external_code", "code": code, "value": code, "rid": rid, "raw": obj}
                        await self.events.put(data)
                        fut = None
                        if rid:
                            fut = self._pending.pop(rid, None)
                        if fut is None and self._pending:
                            try:
                                rid2, fut2 = next(iter(self._pending.items()))
                            except Exception:
                                rid2, fut2 = None, None
                            if fut2:
                                self._pending.pop(rid2, None)
                                fut = fut2
                        if fut and not fut.done():
                            try:
                                fut.set_result({"code": code, "value": code, "rid": rid, "raw": obj})
                            except Exception:
                                pass
                        now_ms = time.time() * 1000
                        if code and self._last_code == code and (now_ms - self._last_code_ts) < self._dedupe_window_ms:
                            log("external_code dedup: skip repeat within window")
                        else:
                            self._last_code = code
                            self._last_code_ts = now_ms
                            try:
                                self._latest_code_path.write_text(code, encoding="utf-8")
                            except Exception:
                                pass
                            if callable(self.on_external_code) and code:
                                try:
                                    self.on_external_code(str(code))
                                except Exception as exc:
                                    log(f"on_external_code error: {exc}")
                elif ev == "result":
                    # Унифицированная обработка result от SW (в т.ч. open_delete_account)
                    rid = obj.get("rid")
                    of = obj.get("of")
                    ok = bool(obj.get("ok", True))
                    data = {"event": "result", "of": of, "ok": ok, "rid": rid, "raw": obj}
                    await self.events.put(data)
                    fut = None
                    if rid:
                        fut = self._pending.pop(rid, None)
                    if fut is None and self._pending:
                        # fallback, если SW не прислал rid — завершим "любой" ожидающий
                        try:
                            rid2, fut2 = next(iter(self._pending.items()))
                        except Exception:
                            rid2, fut2 = None, None
                        if fut2:
                            self._pending.pop(rid2, None)
                            rid = rid or rid2
                            fut = fut2
                    if fut and not fut.done():
                        try:
                            fut.set_result(obj)
                        except Exception:
                            pass
                    continue
                elif ev == "delete_done":
                    rid = obj.get("rid")
                    ok = bool(obj.get("ok", True))
                    data = {"event": "delete_done", "rid": rid, "ok": ok, "raw": obj}
                    await self.events.put(data)
                    fut = None
                    if rid:
                        fut = self._pending.pop(rid, None)
                    if fut and not fut.done():
                        try:
                            fut.set_result(data)
                        except Exception:
                            pass
                elif ev == "login_reached":
                    self._log_gui("[EXT] login page (or app) reached")
                    try:
                        if self.queue is not None:
                            await self.queue.put({"type": "stop_login_watch"})
                    except Exception as exc:
                        self._log_gui(f"[2ND] login-watch stop send failed: {exc}")
                    await self.events.put({"event": "login_reached", "raw": obj})
                elif ev == "login_watch_limit":
                    self._log_gui("[EXT] login-watch reached limit (3 min). Stopping reloads.")
                    await self.events.put({"event": "login_watch_limit", "raw": obj})
                elif ev == "page_ready_numbers":
                    try:
                        if self.queue is not None:
                            await self.queue.put({"type": "stop_login_watch"})
                    except Exception as exc:
                        self._log_gui(f"[2ND] login-watch stop send failed: {exc}")
                    await self.events.put({"event": "page_ready_numbers", "raw": obj})
                else:
                    await self.events.put(obj)
            else:
                await self.events.put(obj)

    async def _alive_monitor(self, ws: websockets.WebSocketClientProtocol) -> None:
        try:
            while True:
                await asyncio.sleep(5)
                if time.time() - self._last_ping_ts > self._alive_timeout:
                    log("no ping from extension, closing connection")
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            pass

    async def handler(self, ws: websockets.WebSocketServerProtocol) -> None:
        self.clients.add(ws)
        log("extension connected")
        self._extension_ready.set()
        self._last_ping_ts = time.time()
        send_task = asyncio.create_task(self._send_loop(ws))
        recv_task = asyncio.create_task(self._recv_loop(ws))
        alive_task = asyncio.create_task(self._alive_monitor(ws))
        try:
            await asyncio.wait({send_task, recv_task, alive_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (send_task, recv_task, alive_task):
                task.cancel()
            self.clients.discard(ws)
            log("extension disconnected")
            if not self.clients:
                self._extension_ready.clear()

    async def run(self) -> None:
        self.server = await websockets.serve(self.handler, self.host, self.port)
        log(f"listening on ws://{self.host}:{self.port}")
        await self.server.wait_closed()

    def start(self) -> None:
        def _runner() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self.queue = asyncio.Queue()
            self.events = asyncio.Queue()
            self._ready.set()
            try:
                loop.run_until_complete(self.run())
            finally:
                self._ready.clear()
                self._loop = None

        threading.Thread(target=_runner, daemon=True).start()

    async def send_delete_account(self, rid: Optional[str] = None) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        payload: Dict[str, Any] = {"type": "delete_account_and_close"}
        if rid:
            payload["rid"] = rid
        log(f"[QUEUE] enqueue cmd: {payload.get('type')} rid={payload.get('rid')}")
        await self.queue.put(payload)

    async def send_open_delete_account(self, rid: Optional[str] = None) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        payload: Dict[str, Any] = {"type": "open_delete_account"}
        if rid:
            payload["rid"] = rid
        log(f"[QUEUE] enqueue cmd: {payload.get('type')} rid={payload.get('rid')}")
        await self.queue.put(payload)

    async def send_reset_cycle(self) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        payload: Dict[str, Any] = {"type": "reset_cycle"}
        log(f"[QUEUE] enqueue cmd: {payload.get('type')} rid={payload.get('rid')}")
        await self.queue.put(payload)

    async def send_open_2no_login(self) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        payload: Dict[str, Any] = {"type": "open_2ndno_and_login_resilient"}
        log(f"[QUEUE] enqueue cmd: {payload.get('type')} rid={payload.get('rid')}")
        await self.queue.put(payload)

    async def send_set_last_code(self, code: str) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        payload = {
            "type": "content_message",
            "name": "set_last_code",
            "payload": {"code": code},
        }
        log(f"[QUEUE] enqueue cmd: {payload.get('type')} rid={payload.get('rid')}")
        await self.queue.put(payload)

    async def send(self, data: dict) -> None:
        if self.queue is None:
            raise RuntimeError("bridge queue is not ready")
        try:
            log(f"[QUEUE] enqueue cmd: {data.get('type')} rid={data.get('rid')}")
        except Exception:
            pass
        await self.queue.put(data)


def find_portable_chrome(base_dir: Path) -> Optional[Path]:
    cand = [
        base_dir / "GoogleChromePortable" / "GoogleChromePortable.exe",
        base_dir.parent / "GoogleChromePortable" / "GoogleChromePortable.exe",
    ]
    for c in cand:
        if c.exists():
            return c
    for p in base_dir.rglob("GoogleChromePortable.exe"):
        try:
            if len(p.relative_to(base_dir).parts) <= 3:
                return p
        except Exception:
            pass
    return None


def start_bridge_and_open(base_dir: str | Path, ext_rel: str = "extension_ws_bridge",
                          profile_rel: str = "app/chrome_profile", ws_port: int = 8765,
                          url: str = "https://2nd-no.com/", proxy_server: str | None = None) -> BridgeServer:
    base = Path(base_dir).resolve()
    chrome = find_portable_chrome(base)
    if not chrome:
        raise RuntimeError("Не найден GoogleChromePortable.exe рядом с программой")
    ext_path = (base / ext_rel).resolve()
    profile = (base / profile_rel).resolve()
    profile.mkdir(parents=True, exist_ok=True)

    server = BridgeServer(port=ws_port)
    server.start()
    server.wait_ready(5)

    args = [
        str(chrome),
        f"--user-data-dir={profile}",
        f"--load-extension={ext_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions-file-access-check",
    ]

    proxy = (proxy_server or os.environ.get("CHROME_PROXY_SERVER", "") or "").strip()
    if proxy:
        if "@" in proxy:
            log(f"[CHROME] proxy rejected (auth not allowed): {proxy}")
        else:
            if "://" not in proxy:
                proxy = "http://" + proxy
            args.append(f"--proxy-server={proxy}")
            args.append("--proxy-bypass-list=<-loopback>")
            log(f"[CHROME] proxy enabled: {proxy}")
    else:
        log("[CHROME] proxy disabled")

    subprocess.Popen(args)

    async def boot() -> None:
        await asyncio.sleep(0.8)
        await server.send({"type": "open_tab", "url": url})
        for _ in range(3):
            await asyncio.sleep(1)
            await server.send({"type": "ping"})

    asyncio.run(boot())

    return server


def subscribe_external_numbers(server: BridgeServer, callback: Callable[[str, Optional[dict]], None]) -> None:
    if not server or not server.loop:
        return

    def _runner() -> None:
        while True:
            if server.loop is None:
                break
            if server.events is None:
                time.sleep(0.05)
                continue
            fut = asyncio.run_coroutine_threadsafe(server.events.get(), server.loop)
            try:
                data = fut.result()
            except Exception:
                break
            if isinstance(data, dict):
                ev = data.get("event")
                if ev == "external_number":
                    try:
                        callback(data.get("number"), data)
                    except Exception:
                        pass
                elif ev == "page_ready_numbers":
                    try:
                        callback(None, data)
                    except Exception:
                        pass

    threading.Thread(target=_runner, daemon=True).start()


def queue_command(server: BridgeServer, cmd: dict) -> None:
    if not server or not server.loop:
        raise RuntimeError("bridge server не запущен")
    if server.queue is None:
        raise RuntimeError("bridge queue не инициализирована")
    try:
        log(f"[QUEUE] enqueue cmd: {cmd.get('type')} rid={cmd.get('rid')}")
    except Exception:
        pass
    fut = asyncio.run_coroutine_threadsafe(server.queue.put(cmd), server.loop)
    fut.result()


# backward compatibility alias
queue = queue_command


def request_number(server: BridgeServer, timeout_sec: float = 45.0) -> Optional[dict]:
    if not server or not server.loop:
        return None
    rid = f"rid-{uuid.uuid4().hex}"

    async def _do_request() -> Optional[dict]:
        assert server.queue is not None
        fut = server.loop.create_future()  # type: ignore[union-attr]
        server._pending[rid] = fut
        try:
            log(f"[RPC] queue start_number_registration rid={rid}")
        except Exception:
            pass
        await server.queue.put({"type": "start_number_registration", "rid": rid})
        try:
            result = await asyncio.wait_for(fut, timeout=timeout_sec)
            return result
        except asyncio.TimeoutError:
            server._pending.pop(rid, None)
            return None

    fut = asyncio.run_coroutine_threadsafe(_do_request(), server.loop)
    try:
        return fut.result(timeout=timeout_sec + 5)
    except Exception:
        return None


def request_sms_code(server: BridgeServer, timeout_sec: float = 60.0) -> Optional[dict]:
    if not server or not server.loop:
        return None
    rid = f"rid-{uuid.uuid4().hex}"

    async def _do_request() -> Optional[dict]:
        assert server.queue is not None
        fut = server.loop.create_future()  # type: ignore[union-attr]
        server._pending[rid] = fut
        try:
            log(f"[RPC] queue start_sms_wait rid={rid}")
        except Exception:
            pass
        await server.queue.put({"type": "start_sms_wait", "rid": rid})
        try:
            result = await asyncio.wait_for(fut, timeout=timeout_sec)
            return result
        except asyncio.TimeoutError:
            server._pending.pop(rid, None)
            return None

    fut = asyncio.run_coroutine_threadsafe(_do_request(), server.loop)
    try:
        return fut.result(timeout=timeout_sec + 5)
    except Exception:
        return None


def request_delete_account(server: BridgeServer, timeout_sec: float = 90.0) -> dict:
    if not server or not server.loop:
        return {"ok": False, "error": "bridge_not_ready"}

    rid = _make_rid()

    async def _do_request() -> dict:
        assert server.queue is not None
        fut = server.loop.create_future()  # type: ignore[union-attr]
        server._pending[rid] = fut
        await server.send_open_delete_account(rid)
        try:
            result = await asyncio.wait_for(fut, timeout=timeout_sec)
        except asyncio.TimeoutError:
            server._pending.pop(rid, None)
            return {"ok": False, "error": "timeout", "rid": rid}
        if isinstance(result, dict):
            return result
        return {"ok": bool(result), "rid": rid}

    fut = asyncio.run_coroutine_threadsafe(_do_request(), server.loop)
    try:
        return fut.result(timeout=timeout_sec + 5)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "rid": rid}


def reset_cycle(server: BridgeServer) -> None:
    if not server or not server.loop:
        return

    async def _dispatch() -> None:
        await server.send_reset_cycle()

    asyncio.run_coroutine_threadsafe(_dispatch(), server.loop)


def open_2no_and_login(server: BridgeServer) -> None:
    if not server or not server.loop:
        return

    async def _dispatch() -> None:
        await server.send_open_2no_login()

    asyncio.run_coroutine_threadsafe(_dispatch(), server.loop)


def set_last_code_for_next_sms(server: BridgeServer, code: str) -> None:
    if not server or not server.loop or not code:
        return

    async def _dispatch() -> None:
        await server.send_set_last_code(code)

    asyncio.run_coroutine_threadsafe(_dispatch(), server.loop)


def wait_ready(server: BridgeServer, timeout_sec: float = 10.0) -> bool:
    if not server:
        return False
    try:
        return server._extension_ready.wait(timeout=timeout_sec)
    except Exception:
        return False
