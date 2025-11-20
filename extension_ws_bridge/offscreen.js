const WS_URLS = ["ws://127.0.0.1:8765", "ws://localhost:8765"];
const PING_INTERVAL_MS = 10_000;
const DEAD_AFTER_MS = 30_000;
const MAX_BACKOFF_MS = 10_000;

let ws = null;
let urlIndex = 0;
let lastPongTs = 0;
let pingTimer = null;
let backoff = 500;

function log(...a) {
  // console.log("[WS-BRIDGE][offscreen]", ...a);
}

function postToSW(payload) {
  try {
    chrome.runtime.sendMessage({ __from: "offscreen", __to: "sw", payload });
  } catch (e) {
    log("postToSW error", e);
  }
}

function scheduleReconnect() {
  const delay = Math.min(backoff, MAX_BACKOFF_MS);
  backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
  setTimeout(connect, delay);
}

function connect() {
  const url = WS_URLS[urlIndex % WS_URLS.length];
  urlIndex += 1;
  log("connecting", url);
  try {
    ws = new WebSocket(url);
  } catch (err) {
    log("WebSocket ctor failed", err);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    log("open");
    lastPongTs = Date.now();
    backoff = 500;
    postToSW({ type: "ws_status", status: "open", url });
    try { ws.send(JSON.stringify({ type: "hello", from: "extension" })); } catch (e) { log("hello send failed", e); }
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      try { ws.send(JSON.stringify({ type: "ping" })); } catch (e) { log("ping send fail", e); }
      if (Date.now() - lastPongTs > DEAD_AFTER_MS) {
        log("no pong, closing");
        try { ws.close(); } catch (err) { log("close fail", err); }
      }
    }, PING_INTERVAL_MS);
  };

  ws.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (_) {
      return;
    }
    if (msg?.type === "pong") {
      lastPongTs = Date.now();
      return;
    }
    if (msg?.type === "ping") {
      try { ws?.send(JSON.stringify({ type: "pong" })); } catch (err) { log("pong reply fail", err); }
      return;
    }
    postToSW(msg);
  };

  ws.onclose = (ev) => {
    log("close", ev?.code, ev?.reason);
    postToSW({ type: "ws_status", status: "closed", reason: ev?.reason ?? null });
    clearInterval(pingTimer);
    pingTimer = null;
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    log("error", err);
    postToSW({ type: "ws_status", status: "error", error: String(err && err.message || err) });
    try { ws.close(); } catch (_) {}
  };
}

chrome.runtime.onMessage.addListener((msg) => {
  if (!(msg && msg.__to === "offscreen")) return;
  const payload = msg.payload;
  if (!payload) return;
  if (payload.type === "ping") {
    // keepalive from service worker
    return;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify(payload));
    } catch (e) {
      log("send payload fail", e);
    }
  }
});

connect();
