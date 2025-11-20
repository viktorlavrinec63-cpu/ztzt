import json
import threading
import queue
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class _BridgeState:
    def __init__(self):
        self.q = queue.Queue()
        self.waiters = {}
        self.lock = threading.Lock()

STATE = _BridgeState()

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/dequeue"):
            try:
                wait = 10
                if "wait=" in self.path:
                    try:
                        wait = int(self.path.split("wait=")[-1])
                    except:
                        pass
                try:
                    cmd = STATE.q.get(timeout=wait)
                    self._set_headers(200)
                    self.wfile.write(json.dumps(cmd).encode("utf-8"))
                except queue.Empty:
                    self._set_headers(204)
                    self.wfile.write(b"{}")
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length or 0)
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            data = {}
        if self.path == "/event":
            self._set_headers(200)
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
        elif self.path == "/cmd":
            STATE.q.put(data)
            self._set_headers(200)
            self.wfile.write(json.dumps({"enqueued": True}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b"{}")

class _BridgeServer(threading.Thread):
    def __init__(self, port=8765):
        super().__init__(daemon=True)
        self.port = int(port)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)

    def run(self):
        self.httpd.serve_forever()

    def start_server(self):
        super().start()

    def start(self):
        self.start_server()

    def request(self, action, params=None, timeout=15):
        cmd = {"action": action, "params": params or {}}
        STATE.q.put(cmd)
        return {"queued": True}
