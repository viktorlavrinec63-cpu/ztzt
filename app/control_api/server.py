from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import json

_APP = None

def set_app_ref(app):
    global _APP
    _APP = app


class Handler(BaseHTTPRequestHandler):
    def _ok(self, code=200, data=None):
        body = json.dumps(data or {"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/status"):
            app = _APP
            if not app:
                return self._ok(500, {"ok": False, "error": "no app ref"})
            return self._ok(200, {
                "ok": True,
                "cycle_active": bool(getattr(app, "_cycle_active", False)),
            })
        return self._ok(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body.decode("utf-8") or "{}") if body else {}
        except Exception:
            data = {}

        if self.path == '/config':
            headful = data.get('headful')
            if _APP is not None and headful is not None:
                try:
                    _APP.after(0, lambda v=bool(headful): _APP.headful.set(v))
                except Exception:
                    pass
            return self._ok(200, {"ok": True, "applied": {"headful": bool(headful)}})

        app = _APP
        if not app:
            return self._ok(500, {"ok": False, "error": "no app ref"})
        if self.path.startswith("/start"):
            try:
                app.after(0, app.run)
                return self._ok(200, {"ok": True})
            except Exception as e:
                return self._ok(500, {"ok": False, "error": str(e)})
        return self._ok(404, {"ok": False, "error": "not found"})


class ControlServer:
    def __init__(self, app, host="127.0.0.1", port=8767):
        self.app = app
        self.host = host
        self.port = int(port)
        self.httpd = None
        self.thread = None

    def start(self):
        set_app_ref(self.app)
        self.httpd = HTTPServer((self.host, self.port), Handler)
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        try:
            self.app.append_log(f"[API] http://{self.host}:{self.port}")
        except Exception:
            pass
        return self

    def stop(self):
        try:
            if self.httpd:
                self.httpd.shutdown()
        except Exception:
            pass
        try:
            if self.thread:
                self.thread.join(timeout=1)
        except Exception:
            pass
        self.httpd = None
        self.thread = None
