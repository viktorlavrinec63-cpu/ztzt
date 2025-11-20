const OFFSCREEN_URL = chrome.runtime.getURL("offscreen.html");
const OFFSCREEN_REASON = "IFRAME_SCRIPTING";
const KEEPALIVE_ALARM = "bridge-keepalive";

const cleanupWatchers = new Map();

// === LOGIN WATCH (фикс) ===
let _loginWatchTimer = null;
let _loginWatchActive = false;
let _watchTabId = null;
let _watchWindowId = null;
let _reloads = 0;
const _MAX_RELOADS = Number.MAX_SAFE_INTEGER;

const _is2ndHost = (h) => {
  if (!h) return false;
  h = h.toLowerCase();
  return h.endsWith("2nd-no.com") || h.endsWith("2no.pl");
};

function _isLoggedInTargetPath(p) {
  if (!p) return false;
  return p.startsWith("/auth/login");
}

function _getActiveTab(cb) {
  chrome.tabs.query({ active: true, lastFocusedWindow: true }, tabs => {
    cb((tabs && tabs[0]) || null);
  });
}

function startLoginWatch() {
  if (_loginWatchActive) return;
  _loginWatchActive = true;
  _reloads = 0;

  // Запоминаем текущую активную вкладку/окно для привязки
  _getActiveTab(tab => {
    _watchTabId = tab ? tab.id : null;
    _watchWindowId = tab ? tab.windowId : null;
  });

  const tick = () => {
    if (!_loginWatchActive) return;

    // Предохранитель по количеству перезагрузок
    if (_reloads >= _MAX_RELOADS) {
      _loginWatchActive = false;
      _loginWatchTimer && clearTimeout(_loginWatchTimer);
      _loginWatchTimer = null;
      // Можно сообщить в GUI, что достигнут лимит
      if (typeof sendWsMessage === "function") sendWsMessage({ type: "login_watch_limit" });
      if (chrome?.runtime?.sendMessage) chrome.runtime.sendMessage({ type: "login_watch_limit" });
      return;
    }

    _getActiveTab(tab => {
      // Если вкладка/окно сменились — останавливаемся
      if (!tab || ( _watchTabId && tab.id !== _watchTabId ) || ( _watchWindowId && tab.windowId !== _watchWindowId )) {
        stopLoginWatch();
        return;
      }

      let u = null;
      try { u = new URL(tab.url || ""); } catch (_) {}

      if (u && _is2ndHost(u.hostname)) {
        if (_isLoggedInTargetPath(u.pathname)) {
          // Мы уже на целевой странице — стоп
          stopLoginWatch();
          if (typeof sendWsMessage === "function") sendWsMessage({ type: "login_reached" });
          if (chrome?.runtime?.sendMessage) chrome.runtime.sendMessage({ type: "login_reached" });
          return;
        } else {
          // Ещё не на логине/приложении — перезагрузка
          _reloads += 1;
          chrome.tabs.reload(tab.id, { bypassCache: true }, () => {});
        }
      } else {
        // Ушли с домена — стоп
        stopLoginWatch();
        return;
      }

      _loginWatchTimer = setTimeout(tick, 15000);
    });
  };

  _loginWatchTimer = setTimeout(tick, 15000);
}

function stopLoginWatch() {
  _loginWatchActive = false;
  _watchTabId = null;
  _watchWindowId = null;
  _reloads = 0;
  if (_loginWatchTimer) {
    clearTimeout(_loginWatchTimer);
    _loginWatchTimer = null;
  }
}

function closeActiveTabAndWindow() {
  _getActiveTab(tab => {
    if (!tab) return;
    const wid = tab.windowId;
    chrome.windows.remove(wid, () => {
      if (typeof sendWsMessage === "function") sendWsMessage({ type: "browser_closed" });
      if (chrome?.runtime?.sendMessage) chrome.runtime.sendMessage({ type: "browser_closed" });
    });
  });
}

function detachCleanupWatcher(tabId, { keepEntry = false } = {}){
  if (typeof tabId !== 'number') return null;
  const entry = cleanupWatchers.get(tabId) || null;
  if (!entry) return null;
  if (entry.listener) {
    try { chrome.tabs.onUpdated.removeListener(entry.listener); } catch (_) {}
    entry.listener = null;
  }
  if (!keepEntry) {
    cleanupWatchers.delete(tabId);
  }
  return entry;
}

function markCleanupWatcherCompleted(tabId){
  const entry = cleanupWatchers.get(tabId) || null;
  if (entry) entry.completed = true;
  return entry;
}

let targetTabId = null;
let lastNumbersTabId = null;
let CURRENT_CYCLE_TAB_ID = null;
let LAST_2NO_OPEN_AT = 0;
let CURRENT_OPEN_PROMISE = null;
const STRICT_GATE = true;
const ENABLE_LEGACY_COPY = false; // legacy auto-copy/injects remain disabled unless explicitly re-enabled
let activeRid = null;
let activeRidUntil = 0;
let lastStartNumberAt = 0;
const START_NUMBER_DEBOUNCE_MS = 60_000;
let cycleGuard = { numberRequested: false, numbersReadyHandled: false, messagesReady: false };
let numberSentThisCycle = false;
const lastCodeByRid = new Map();
let bridgeStatus = "unknown";

function log(...a){ console.log("[WS-BRIDGE]", ...a); }

async function hasOffscreenDocument(){
  try {
    const hasDoc = await chrome.offscreen?.hasDocument?.();
    return Boolean(hasDoc);
  } catch (e) {
    log("hasOffscreenDocument error", e);
    return false;
  }
}

async function ensureOffscreen(){
  if (!chrome.offscreen || !chrome.offscreen.createDocument) return;
  if (await hasOffscreenDocument()) return;
  try {
    await chrome.offscreen.createDocument({
      url: OFFSCREEN_URL,
      reasons: [OFFSCREEN_REASON],
      justification: "Persistent WebSocket bridge to local Python app."
    });
  } catch (e) {
    log("ensureOffscreen failed", e);
  }
}

function sendToOffscreen(message){
  ensureOffscreen().then(() => {
    try {
      chrome.runtime.sendMessage(message, () => {
        const err = chrome.runtime.lastError;
        if (err && err.message && !/Receiving end does not exist/i.test(err.message)) {
          log("sendToOffscreen lastError", err.message);
        }
      });
    } catch (e) {
      log("sendToOffscreen threw", e);
    }
  }).catch((err) => {
    log("ensureOffscreen rejection", err);
  });
}

function send(payload){
  sendToOffscreen({ __from: "sw", __to: "offscreen", payload });
}

function wsDebug(msg, extra = {}){
  send({ type: 'ws_debug', msg, ...extra });
}

chrome.runtime.onStartup.addListener(ensureOffscreen);
chrome.runtime.onInstalled.addListener(ensureOffscreen);

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.__from === "offscreen" && msg.__to === "sw") {
    const payload = msg.payload;
    if (!payload) return;
    if (payload.type === "ws_status") {
      bridgeStatus = payload.status || "unknown";
      log("ws status", bridgeStatus);
      return;
    }
    Promise.resolve(handle(payload)).catch((err) => {
      log("handle error", err);
    });
    return;
  }
  if (msg && msg.__to === "offscreen" && msg.__from !== "sw") {
    let payload = msg.payload;
    if (payload === undefined) {
      const { __to: _to, __from: _from, ...rest } = msg;
      payload = rest;
    }
    if (payload) {
      send(payload);
    }
    return;
  }
});

try {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
} catch (e) {
  log("alarms.create failed", e);
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm || alarm.name !== KEEPALIVE_ALARM) return;
  send({ type: "ping" });
});

function sendToActiveTab(message) {
  try {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs && tabs[0]) {
        try {
          chrome.tabs.sendMessage(tabs[0].id, message, () => {});
        } catch (err) {
          if (err && err.message && !/Receiving end does not exist/i.test(err.message)) {
            log('sendToActiveTab sendMessage error', err.message);
          }
        }
      }
    });
  } catch (e) {
    console.warn('sendToActiveTab fail', e);
  }
}

async function openOrFocus(url){
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs){
    if (!tab || typeof tab.id !== 'number') continue;
    const currentUrl = tab.url || '';
    if (currentUrl.startsWith(url)){
      if (typeof tab.windowId === 'number'){
        try { await chrome.windows.update(tab.windowId, { focused: true }); } catch (_) {}
      }
      try { await chrome.tabs.update(tab.id, { active: true }); } catch (_) {}
      return tab;
    }
  }
  const created = await chrome.tabs.create({ url, active: true });
  if (created && typeof created.windowId === 'number'){
    try { await chrome.windows.update(created.windowId, { focused: true }); } catch (_) {}
  }
  return created;
}

async function ensureMessagesTab(){
  // Больше НЕ создаём вкладки и НЕ меняем URL.
  // Находим уже открытую вкладку 2nd-no и возвращаем её id.
  const preferNumbers = /\/app\/numbers/i;
  const is2no = (u) => typeof u === 'string' && /https?:\/\/(www\.)?2nd-no\.com\//i.test(u);

  const tabs = await chrome.tabs.query({});
  let best = null;
  for (const t of tabs) {
    if (!t || typeof t.id !== 'number' || !t.url) continue;
    if (!is2no(t.url)) continue;
    if (!best) best = t;
    if (preferNumbers.test(t.url)) { best = t; break; }
  }
  if (!best) throw new Error('messages_tab_unavailable');
  try { await chrome.tabs.update(best.id, { active: true }); } catch (_) {}
  return best.id;
}

async function startSmsWaitFlow(cmd){
  const rid = cmd?.rid || null;
  const messagesTabId = await ensureMessagesTab();
  if (typeof messagesTabId !== 'number') {
    throw new Error('messages_tab_unavailable');
  }
  wsDebug('sw → cs: start_sms_wait', { rid, tabId: messagesTabId });

  const targets = new Set();
  targets.add(messagesTabId);
  try {
    const allTabs = await chrome.tabs.query({});
    for (const tab of allTabs){
      if (!tab || typeof tab.id !== 'number') continue;
      if (!tab.url) continue;
      if (/\/\/[^\/]*2nd-no\.com\//i.test(tab.url)) {
        targets.add(tab.id);
      }
    }
  } catch (err) {
    log('startSmsWaitFlow tabs query error', err?.message || err);
  }

  const sendArm = (tabId) => new Promise((resolveArm) => {
    const startTs = Date.now();
    (function loop(){
      if (Date.now() - startTs > 8000) return resolveArm(false);
      try { chrome.tabs.sendMessage(tabId, { type: 'set_current_rid', rid }, () => {}); } catch (_) {}
      chrome.tabs.sendMessage(tabId, { type: 'arm_sms', rid }, (resp) => {
        const err = chrome.runtime.lastError;
        if (!err && resp && resp.armed === true) {
          return resolveArm(true);
        }
        setTimeout(loop, 250);
      });
    })();
  });

  for (const tabId of targets){
    try { chrome.tabs.sendMessage(tabId, { type: 'set_current_rid', rid }, () => {}); } catch (_) {}
    try {
      chrome.tabs.sendMessage(tabId, { type: 'start_sms_wait', rid }, () => {});
    } catch (_) {}
  }

  for (const tabId of targets){
    await sendArm(tabId);
  }

  sendToActiveTab({ type: 'arm_sms', rid });
  return { ok: true, rid };
}

async function clickDeleteInSettings(tabId){
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: async () => {
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const findByText = (root, text) => {
          const needle = String(text || '').trim().toLowerCase();
          if (!needle) return null;
          const nodes = root.querySelectorAll('button, .button, div[role="button"], span');
          for (const node of nodes){
            const txt = (node.innerText || node.textContent || '').trim().toLowerCase();
            if (txt === needle) return node;
          }
          return null;
        };

        const findDeleteButton = async () => {
          const selectors = [
            'button.button.delete',
            'button.delete-account',
            '.delete-account-wrapper button',
            'button[data-test="delete-account"]'
          ];
          const deadline = Date.now() + 15000;
          while (Date.now() < deadline){
            for (const sel of selectors){
              const el = document.querySelector(sel);
              if (el) return el;
            }
            const byText = findByText(document, 'delete account');
            if (byText) return byText;
            await wait(200);
          }
          return null;
        };

        const button = await findDeleteButton();
        if (!button) return false;
        try { button.click(); } catch (e) { console.warn('delete button click failed', e); }
        await wait(300);

        const findConfirm = async () => {
          const selectors = [
            '.modal .button.delete',
            '.delete-number-modal .button.delete',
            '.modal button[data-test="confirm-delete"]',
          ];
          const deadline = Date.now() + 8000;
          while (Date.now() < deadline){
            for (const sel of selectors){
              const el = document.querySelector(sel);
              if (el) return el;
            }
            const byText = findByText(document, 'delete');
            if (byText) return byText;
            await wait(150);
          }
          return null;
        };

        const confirmBtn = await findConfirm();
        if (!confirmBtn) return false;
        try { confirmBtn.click(); } catch (e) { console.warn('confirm delete click failed', e); }
        return true;
      },
    });
    return !!result;
  } catch (err) {
    console.warn('clickDeleteInSettings error', err);
    return false;
  }
}

const DEFAULT_2NO_URL = "https://2nd-no.com/";

async function waitTabComplete(tabId, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastSeen = null;
  while (Date.now() < deadline) {
    try {
      const tab = await chrome.tabs.get(tabId);
      lastSeen = tab || lastSeen;
      if (!tab) break;
      if (tab.status === "complete") {
        return tab;
      }
    } catch (err) {
      return null;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return lastSeen;
}

async function closeAll2noTabs() {
  try {
    const tabs = await chrome.tabs.query({ url: ["https://2nd-no.com/*"] });
    if (!Array.isArray(tabs) || tabs.length === 0) {
      return;
    }
    const ids = [];
    for (const tab of tabs) {
      const tid = tab?.id;
      if (typeof tid !== "number") continue;
      ids.push(tid);
      detachCleanupWatcher(tid);
    }
    if (!ids.length) {
      return;
    }
    try {
      await chrome.tabs.remove(ids);
    } catch (err) {
      log("closeAll2noTabs remove failed", err);
    }
    if (ids.includes(targetTabId)) targetTabId = null;
    if (ids.includes(lastNumbersTabId)) lastNumbersTabId = null;
    if (ids.includes(CURRENT_CYCLE_TAB_ID)) CURRENT_CYCLE_TAB_ID = null;
  } catch (err) {
    log("closeAll2noTabs query failed", err);
  }
}

async function open2noSingle(url = DEFAULT_2NO_URL, makeActive = true) {
  const now = Date.now();
  if (CURRENT_OPEN_PROMISE && (now - LAST_2NO_OPEN_AT) < 2000) {
    try {
      return await CURRENT_OPEN_PROMISE;
    } catch (err) {
      log("open2noSingle reuse failed", err);
    }
  }

  LAST_2NO_OPEN_AT = now;
  CURRENT_OPEN_PROMISE = (async () => {
    await closeAll2noTabs();
    const tab = await new Promise((resolve, reject) => {
      try {
        chrome.tabs.create({ url, active: makeActive }, (created) => {
          const err = chrome.runtime.lastError;
          if (err) {
            reject(new Error(err.message || "tabs.create_failed"));
            return;
          }
          resolve(created || null);
        });
      } catch (e) {
        reject(e);
      }
    });

    const tabId = tab?.id ?? null;
    if (typeof tabId === "number") {
      CURRENT_CYCLE_TAB_ID = tabId;
      targetTabId = tabId;
      lastNumbersTabId = tabId;
      try {
        await waitTabComplete(tabId);
      } catch (err) {
        log("waitTabComplete after open failed", err);
      }
    }
    return tabId;
  })();

  try {
    return await CURRENT_OPEN_PROMISE;
  } finally {
    CURRENT_OPEN_PROMISE = null;
  }
}

async function open2noInNewTab(url = DEFAULT_2NO_URL, makeActive = true) {
  return await open2noSingle(url, makeActive);
}

function is2NoAuthUrl(url) {
  if (typeof url !== "string" || !url) return false;
  try {
    const u = new URL(url);
    return u.hostname.endsWith("2nd-no.com") && u.pathname.startsWith("/auth/");
  } catch (_) {
    return false;
  }
}

function is2NoUrl(url) {
  if (typeof url !== "string" || !url) return false;
  try {
    const u = new URL(url);
    return u.hostname.endsWith("2nd-no.com");
  } catch (_) {
    return false;
  }
}

async function ensureCleanupTab() {
  let tab = null;
  if (typeof CURRENT_CYCLE_TAB_ID === "number") {
    tab = await getTabSafe(CURRENT_CYCLE_TAB_ID);
  }
  if (!tab) {
    tab = await resolveNumbersTab();
  }
  if (!tab || typeof tab.id !== "number" || !is2NoUrl(tab.url)) {
    const createdTabId = await open2noSingle(DEFAULT_2NO_URL, true);
    if (typeof createdTabId !== "number") {
      return null;
    }
    const fresh = await getTabSafe(createdTabId);
    if (fresh) {
      return fresh;
    }
    return { id: createdTabId, url: DEFAULT_2NO_URL };
  }

  const tabId = tab.id;
  CURRENT_CYCLE_TAB_ID = tabId;
  lastNumbersTabId = tabId;
  try {
    if (is2NoAuthUrl(tab.url || "")) {
      await chrome.tabs.update(tabId, { url: DEFAULT_2NO_URL, active: true });
    } else {
      await chrome.tabs.update(tabId, { active: true });
    }
  } catch (_) {}

  const updated = await waitTabComplete(tabId);
  if (updated && typeof updated.id === "number") {
    tab = updated;
  }
  return tab;
}

async function deleteAccountFlow(cmd) {
  console.log("[CLEANUP] start deleteAccountFlow (single-tab)");
  const tab = await ensureCleanupTab();
  if (!tab || typeof tab.id !== "number") {
    throw new Error("cleanup_tab_not_ready");
  }
  const tabId = tab.id;

  detachCleanupWatcher(tabId);

  const onUpd = async (changedId, changeInfo, t) => {
    try {
      if (changedId !== tabId) return;
      if (changeInfo.status === "complete" && /\/401\b/.test((t && t.url) || "")) {
        console.warn("[CLEANUP] 401 detected by SW watcher");
        markCleanupWatcherCompleted(tabId);
        const entry = detachCleanupWatcher(tabId, { keepEntry: true });
        if (entry) {
          cleanupWatchers.set(tabId, entry);
          setTimeout(() => {
            const stored = cleanupWatchers.get(tabId);
            if (stored === entry) {
              cleanupWatchers.delete(tabId);
            }
          }, 60_000);
        }
        try { chrome.runtime.sendMessage({ type: "cleanup_done_broadcast", ok: true }); } catch (_) {}
        try { chrome.tabs.remove(tabId); } catch (_) {}
        if (CURRENT_CYCLE_TAB_ID === tabId) {
          CURRENT_CYCLE_TAB_ID = null;
        }
      }
    } catch (e) {}
  };
  try {
    chrome.tabs.onUpdated.addListener(onUpd);
    cleanupWatchers.set(tabId, { listener: onUpd, completed: false });
  } catch (_) {}

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content/account_cleanup.js"],
    });
    await chrome.tabs.sendMessage(tabId, { type: "RUN_DELETE_ACCOUNT" });
  } catch (e) {
    console.error("[CLEANUP] inject failed", e);
    detachCleanupWatcher(tabId);
    throw e;
  }
}

async function find2ndNoTab(){
  try {
    const tabs = await chrome.tabs.query({});
    const is2no = (url) => typeof url === "string" && /https?:\/\/(www\.)?2nd-no\.com\//i.test(url);
    const preferNumbers = /\/app\/numbers/i;
    for (const tab of tabs){
      if (is2no(tab.url) && preferNumbers.test(tab.url || "")) return tab;
    }
    for (const tab of tabs){
      if (is2no(tab.url)) return tab;
    }
  } catch (e) {
    log("find2ndNoTab error", e);
  }
  return null;
}

async function getTabSafe(tabId){
  if (typeof tabId !== 'number') return null;
  try {
    return await chrome.tabs.get(tabId);
  } catch (_) {
    return null;
  }
}

async function resolveNumbersTab(){
  if (lastNumbersTabId !== null) {
    const existing = await getTabSafe(lastNumbersTabId);
    if (existing) return existing;
    lastNumbersTabId = null;
  }
  const tab = await find2ndNoTab();
  if (tab) {
    lastNumbersTabId = tab.id;
  }
  return tab;
}

async function exec(tabId, func, args=[]){
  const res = await chrome.scripting.executeScript({ target:{tabId}, func, args });
  return (res && res[0]) ? res[0].result : null;
}

async function runInTab(tabId, fnName){
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (name) => {
        try {
          const fn = window?.[name];
          if (typeof fn === 'function') {
            return Promise.resolve(fn()).catch((err) => ({ ok: false, error: String(err) }));
          }
          return { ok: false, reason: 'no-fn' };
        } catch (err) {
          return { ok: false, error: String(err) };
        }
      },
      args: [fnName],
    });
    return result;
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

function open2ndNoAndLoginResilient(preferredTabId = null){
  const BASE_URL = 'https://2nd-no.com/';
  const CHECK_EVERY_MS = 500;
  const RELOAD_AFTER_MS = 15000;

  const startWatchdog = (tabId) => {
    if (typeof tabId !== 'number') return;
    let lastReloadAt = Date.now();
    const timer = setInterval(() => {
      chrome.tabs.get(tabId, (tab) => {
        if (!tab) return;
        const url = tab.url || '';
        const isLogin = /https?:\/\/2nd-no\.com\/auth\/login/i.test(url);
        if (isLogin) {
          clearInterval(timer);
          // как только увидели /auth/login — никаких дальнейших авто-перезагрузок
          try { clickGoogleLogin?.(tabId); } catch(e) {}
          return;
        }
        const now = Date.now();
        if (now - lastReloadAt >= RELOAD_AFTER_MS) {
          lastReloadAt = now;
          try { chrome.tabs.reload(tabId, { bypassCache: true }, () => {}); } catch (_) {}
        }
      });
    }, CHECK_EVERY_MS);
  };

  const openBaseAndWatch = () => {
    chrome.tabs.create({ url: BASE_URL, active: true }, (tab) => startWatchdog(tab?.id));
  };

  if (Number.isInteger(preferredTabId)) {
    chrome.tabs.update(preferredTabId, { url: BASE_URL, active: true }, (tab) => {
      startWatchdog((tab && tab.id) ?? preferredTabId);
    });
  } else {
    openBaseAndWatch();
  }
}

function watchGoogleOAuthWindow(preferredEmail){
  const listener = (tabId, changeInfo, tab) => {
    try {
      if (!changeInfo?.status && !changeInfo?.url) return;
      const url = changeInfo?.url || tab?.url || '';
      if (!url) return;
      if (!/https?:\/\/accounts\.google\.com\//i.test(url)) return;

      if (typeof tab?.windowId === 'number') {
        chrome.windows.update(tab.windowId, { focused: true }, () => {});
      }
      if (typeof tabId === 'number') {
        chrome.tabs.update(tabId, { active: true }, () => {});
      }

      try {
        if (preferredEmail) {
          chrome.scripting.executeScript({
            target: { tabId },
            func: (email) => { window.__preferredGoogleEmail = email; },
            args: [preferredEmail],
          }, () => {});
        }
        chrome.scripting.executeScript({
          target: { tabId },
          files: ['content/google_account_clicker.js'],
        }, () => {});
      } catch (injectErr) {
        console.warn('watchGoogleOAuthWindow inject error', injectErr);
      }
    } catch (err) {
      console.warn('watchGoogleOAuthWindow listener error', err);
    }
  };

  chrome.tabs.onUpdated.addListener(listener);
  setTimeout(() => {
    try { chrome.tabs.onUpdated.removeListener(listener); } catch (_) {}
  }, 30_000);
}

function clickGoogleLogin(tabId){
  if (typeof tabId !== 'number') return;
  chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      function tryClick(){
        const labels = ['continue with google', 'sign in with google', 'google'];
        const nodes = Array.from(document.querySelectorAll('button, a, div'));
        const btn = nodes.find((el) => {
          const text = (el.innerText || el.textContent || '').toLowerCase();
          return labels.some((label) => text.includes(label));
        });
        if (btn) {
          btn.click();
          return true;
        }
        return false;
      }
      let attempts = 0;
      const tick = setInterval(() => {
        attempts += 1;
        if (tryClick() || attempts > 20) {
          clearInterval(tick);
        }
      }, 250);
    }
  });
  watchGoogleOAuthWindow(null);
}

// глубинный поиск по тексту (shadow DOM + same-origin iframes)
function deepQueryAll(root, selector){
  const out = [];
  function walk(n){
    try{ n.querySelectorAll(selector).forEach(el=>out.push(el)); }catch(_){}
    const nodes = n.querySelectorAll("*");
    for(const el of nodes){ const sr = el.shadowRoot; if(sr) walk(sr); }
    for(const ifr of n.querySelectorAll("iframe")){
      try{ const doc = ifr.contentDocument; if(doc) walk(doc); }catch(_){}
    }
  }
  walk(root);
  return out;
}

async function handle(cmd){
  const type = cmd?.type || cmd?.event;
  if (!type) return;

  switch(type){

    case "start_login_watch": {
      startLoginWatch();
      if (cmd?.type) {
        send({ type: "result", of: "start_login_watch", ok: true });
      }
      break;
    }

    case "stop_login_watch": {
      stopLoginWatch();
      if (cmd?.type) {
        send({ type: "result", of: "stop_login_watch", ok: true });
      }
      break;
    }

    case "close_active_tab_and_window": {
      closeActiveTabAndWindow();
      if (cmd?.type) {
        send({ type: "result", of: "close_active_tab_and_window", ok: true });
      }
      break;
    }

    case "reset_cycle": {
      cycleGuard.numberRequested = false;
      cycleGuard.numbersReadyHandled = false;
      cycleGuard.messagesReady = false;
      lastStartNumberAt = 0;
      numberSentThisCycle = false;
      CURRENT_CYCLE_TAB_ID = null;
      if (cmd?.type) {
        send({ type: "result", of: "reset_cycle", ok: true });
      }
      break;
    }

    case "page_ready_numbers": {
      cycleGuard.numbersReadyHandled = true;
      if (cmd?.type) {
        send({ type: "result", of: "page_ready_numbers", ok: true });
      }
      break;
    }

    case "open_tab": {
      const url = typeof cmd.url === "string" && cmd.url ? cmd.url : DEFAULT_2NO_URL;
      try {
        const tabId = await open2noInNewTab(url, true);
        if (typeof tabId !== "number") throw new Error("tab_create_failed");
        send({ type: "result", of: "open_tab", ok: true, tabId });
      } catch (e) {
        send({ type: "result", of: "open_tab", ok: false, error: String(e) });
      }
      break;
    }

    case "goto": {
      try{
        const tabId = cmd.tabId ?? targetTabId; if(!tabId) throw new Error("no_target_tab");
        await chrome.tabs.update(tabId, {url: cmd.url});
        send({type:"result", of:"goto", ok:true, tabId, url: cmd.url});
      }catch(e){ send({type:"result", of:"goto", ok:false, error:String(e)}); }
      break;
    }

    case "waitAndClickText": {
      try{
        const tabId = cmd.tabId ?? targetTabId; if(!tabId) throw new Error("no_target_tab");
        const texts = cmd.texts || cmd.text || [];
        const timeout = cmd.timeout ?? 20000;
        const ok = await exec(tabId, (texts, timeout) => new Promise(resolve=>{
          function norm(s){ return (s||"").toLowerCase().trim(); }
          const arr = Array.isArray(texts)?texts:[texts];
          const deadline = Date.now()+timeout;
          function deepQueryAll(root, selector){
            const out=[]; function walk(n){
              try{ n.querySelectorAll(selector).forEach(el=>out.push(el)); }catch(_){}
              const nodes = n.querySelectorAll("*");
              for(const el of nodes){ const sr = el.shadowRoot; if(sr) walk(sr); }
              for(const ifr of n.querySelectorAll("iframe")){
                try{ const doc = ifr.contentDocument; if(doc) walk(doc); }catch(_){}
              }
            } walk(root); return out;
          }
          function tick(){
            const nodes = deepQueryAll(document, "button, a, div[role='button']");
            for(const el of nodes){
              const t = norm(el.innerText||el.textContent);
              for(const x of arr){
                if(t.includes(norm(x))){
                  try{ el.scrollIntoView({block:"center"}); el.click(); el.dispatchEvent(new MouseEvent("click",{bubbles:true})); }catch(_){}
                  return resolve(true);
                }
              }
            }
            if(Date.now()>deadline) return resolve(false);
            setTimeout(tick, 300);
          }
          tick();
        }), [texts, timeout]);
        send({type:"result", of:"waitAndClickText", ok: !!ok, tabId});
      }catch(e){ send({type:"result", of:"waitAndClickText", ok:false, error:String(e)}); }
      break;
    }

    case "runActions": { // можно слать из софта
      try{
        const tabId = cmd.tabId ?? targetTabId; if(!tabId) throw new Error("no_target_tab");
        const steps = Array.isArray(cmd.steps)?cmd.steps:[];
        for(const step of steps){
          if(step.type==="goto"){
            await chrome.tabs.update(tabId, {url: step.url});
            await new Promise(r=>setTimeout(r, step.delay||800));
          }else if(step.type==="waitAndClickText"){
            await handle({type:"waitAndClickText", tabId, texts: step.texts, timeout: step.timeout||20000});
          }
        }
        send({type:"result", of:"runActions", ok:true, tabId});
      }catch(e){ send({type:"result", of:"runActions", ok:false, error:String(e)}); }
      break;
    }

    case "setOption": { // включить/выключить авто-создание
      try{
        const {key, value} = cmd; await chrome.storage.local.set({[key]: value});
        send({type:"result", of:"setOption", ok:true, key, value});
      }catch(e){ send({type:"result", of:"setOption", ok:false, error:String(e)}); }
      break;
    }

    case "getOptions": {
      try{
        const keys = cmd.keys || null; const data = await chrome.storage.local.get(keys);
        send({type:"result", of:"getOptions", ok:true, data});
      }catch(e){ send({type:"result", of:"getOptions", ok:false, error:String(e)}); }
      break;
    }

    case "start_number_registration": {
      try {
        const rid = cmd.rid || null;
        const nowTs = Date.now();
        if (cycleGuard.numberRequested || (nowTs - lastStartNumberAt) < START_NUMBER_DEBOUNCE_MS) {
          log("skip duplicate start_number_registration (guard)", { rid, delta: nowTs - lastStartNumberAt, cycleGuard });
          send({ type: "result", of: "start_number_registration", ok: false, error: "debounced" });
          break;
        }
        let tab = null;
        if (typeof CURRENT_CYCLE_TAB_ID === "number") {
          tab = await getTabSafe(CURRENT_CYCLE_TAB_ID);
        }
        if (!tab) {
          const createdTabId = await open2noInNewTab(DEFAULT_2NO_URL, true);
          if (typeof createdTabId === "number") {
            tab = await getTabSafe(createdTabId);
          }
        }
        if (!tab) {
          tab = await resolveNumbersTab();
        }
        if (!tab) {
          send({ type: "result", of: "start_number_registration", ok: false, error: "numbers_tab_not_found" });
          break;
        }
        CURRENT_CYCLE_TAB_ID = tab.id;
        lastStartNumberAt = nowTs;
        lastNumbersTabId = tab.id;
        targetTabId = tab.id;
        cycleGuard.numberRequested = true;
        log("cmd:start_number_registration", { rid, tabId: tab.id, url: tab.url });
        activeRid = rid || null;
        activeRidUntil = Date.now() + 30000;
        wsDebug('sw → cs: create_number', { rid, tabId: tab.id });
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ["content/numbers_controller.js"],
          });
          log("numbers_controller injected");
        } catch (injectErr) {
          log("numbers_controller inject skipped", injectErr?.message || injectErr);
        }
        await new Promise((resolve) => {
          chrome.tabs.sendMessage(tab.id, { type: 'set_rid', rid }, () => {});
          chrome.tabs.sendMessage(tab.id, { type: 'start_number_registration', rid }, () => {
            const err = chrome.runtime.lastError;
            if (err) {
              log("start_number_registration sendMessage error", err.message);
            } else {
              log("start_number_registration dispatched", { tabId: tab.id, rid });
            }
            resolve();
          });
        });
        send({ type: "result", of: "start_number_registration", ok: true, rid });
      } catch (e) {
        send({ type: "result", of: "start_number_registration", ok: false, error: String(e) });
      }
      break;
    }

    case "start_sms_wait": {
      try {
        const result = await startSmsWaitFlow(cmd);
        send({ type: "result", of: "start_sms_wait", ok: true, rid: result.rid || null });
      } catch (e) {
        send({ type: "result", of: "start_sms_wait", ok: false, error: String(e) });
      }
      break;
    }

    case "open_2ndno_and_login_resilient": {
      try {
        const url = typeof cmd.url === "string" && cmd.url ? cmd.url : DEFAULT_2NO_URL;
        const tabId = await open2noInNewTab(url, true);
        open2ndNoAndLoginResilient(tabId ?? undefined);
        send({ type: "result", of: "open_2ndno_and_login_resilient", ok: true, tabId: tabId ?? null });
      } catch (e) {
        send({ type: "result", of: "open_2ndno_and_login_resilient", ok: false, error: String(e) });
      }
      break;
    }

    case "delete_account_and_close": {
      try {
        await deleteAccountFlow(cmd);
        send({ type: "result", of: "delete_account_and_close", ok: true, rid: cmd?.rid || null });
      } catch (e) {
        const errMsg = String(e);
        send({ type: "result", of: "delete_account_and_close", ok: false, error: errMsg, rid: cmd?.rid || null });
      }
      break;
    }

    case "open_delete_account": {
      const rid = cmd?.rid || null;
      (async () => {
        try {
          await deleteAccountFlow(cmd);
        } catch (e) {
          console.warn("[CLEANUP] open_delete_account flow error", e);
        }
      })();
      send({ type: "result", of: "open_delete_account", ok: true, rid });
      break;
    }

    case "account_cleanup": {
      try {
        await deleteAccountFlow(cmd);
        send({ type: "result", of: "account_cleanup", ok: true, rid: cmd?.rid || null });
      } catch (e) {
        const errMsg = String(e);
        send({ type: "result", of: "account_cleanup", ok: false, error: errMsg, rid: cmd?.rid || null });
      }
      break;
    }

    case "content_message": {
      try {
        const name = cmd.name;
        if (!name) {
          throw new Error('missing_name');
        }
        const payload = cmd.payload || {};
        const message = { type: name, ...payload };
        sendToActiveTab(message);
        try {
          const tabs = await chrome.tabs.query({});
          await Promise.all((tabs || []).map((tab) => new Promise((resolve) => {
            if (!tab || typeof tab.id !== 'number' || !tab.url) {
              resolve();
              return;
            }
            if (!/\/\/[^\/]*2nd-no\.com\//i.test(tab.url)) {
              resolve();
              return;
            }
            chrome.tabs.sendMessage(tab.id, message, () => resolve());
          })));
        } catch (broadcastErr) {
          log('content_message broadcast error', broadcastErr?.message || broadcastErr);
        }
        send({ type: "result", of: "content_message", ok: true, name });
      } catch (e) {
        send({ type: "result", of: "content_message", ok: false, error: String(e) });
      }
      break;
    }
  }
  return {ok:true};
}

// Трекинг вкладки + триггер после логина
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab?.url && /:\/\/(www\.)?2nd-no\.com\//.test(tab.url)) {
    targetTabId = tabId;
    send({type:"event", event:"pageReady", tabId, url: tab.url});
    if (/\/app\/numbers/.test(tab.url)) {
      lastNumbersTabId = tabId;
      CURRENT_CYCLE_TAB_ID = tabId;
      send({ type: "event", event: "page_ready_numbers", tabId, url: tab.url });
      // Никаких автодействий тут не запускаем: STRICT_GATE остаётся включённым.
    }
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === CURRENT_CYCLE_TAB_ID) {
    CURRENT_CYCLE_TAB_ID = null;
  }
  if (tabId === lastNumbersTabId) {
    lastNumbersTabId = null;
  }
  if (tabId === targetTabId) {
    targetTabId = null;
  }
});

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.event === "pageReady") {
    if (sender?.tab?.id) targetTabId = sender.tab.id;
    send({type:"event", event:"pageReady", tabId: sender?.tab?.id ?? null, url: msg.url || sender?.url || null});
    if (/\/app\/numbers/.test(msg.url||"")) {
      lastNumbersTabId = sender?.tab?.id ?? null;
      CURRENT_CYCLE_TAB_ID = sender?.tab?.id ?? CURRENT_CYCLE_TAB_ID;
      const payload = { id: `ev-${Date.now()}`, event: 'page_ready_numbers', data: { ts: Date.now() } };
      send(payload);
    }
  } else if (msg && msg.type === 'page_ready_numbers') {
    if (sender?.tab?.id) lastNumbersTabId = sender.tab.id;
    if (sender?.tab?.id) CURRENT_CYCLE_TAB_ID = sender.tab.id;
    const payload = { id: `ev-${Date.now()}`, event: 'page_ready_numbers', data: { ts: Date.now() } };
    send(payload);
  } else if (msg && msg.type === 'page_ready_messages') {
    cycleGuard.messagesReady = true;
    const payload = { id: `ev-${Date.now()}`, event: 'page_ready_messages', data: { ts: Date.now() } };
    send(payload);
  }
});

ensureOffscreen();



// --- ws-bridge external_number forwarder (enhanced) ---
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  try {
    if (!msg || !msg.type) return;

    const fromTabUrl = sender?.tab?.url || '';
    const fromTabId = sender?.tab?.id ?? null;
    if (fromTabId && /\/app\/numbers/i.test(fromTabUrl)) {
      lastNumbersTabId = fromTabId;
    }

    const type = msg.type;
    if (type === 'cs_ack') {
      wsDebug('cs_ack', { rid: msg.rid ?? null, stage: msg.stage ?? null });
      return;
    }

    const payloadIn = msg.payload || msg.data || {};
    let rid = (msg.rid ?? payloadIn.rid) ?? null;

    if (!rid && activeRid && Date.now() < activeRidUntil) {
      rid = activeRid;
    }

    if (type === 'external_number') {
      const number = (msg.number ?? msg.phone ?? payloadIn.number ?? payloadIn.phone) ?? null;
      if (numberSentThisCycle) {
        if (typeof sendResponse === 'function') {
          try { sendResponse({ ok: true, deduped: true }); } catch (_) {}
        }
        return true;
      }
      numberSentThisCycle = true;
      const payload = { type: 'external_number', rid, number, value: number };
      console.log('[WS-BRIDGE] external_number -> WS', number, rid);
      send(payload);
      if (rid && activeRid === rid) {
        activeRid = null;
        activeRidUntil = 0;
      }
      if (typeof sendResponse === 'function') {
        try { sendResponse({ ok: true }); } catch (_) {}
      }
      return true;
    }

    if (type === 'external_code') {
      const code = (msg.code ?? payloadIn.code) ?? null;
      const phone = msg.phone ?? payloadIn.phone ?? null;
      if (!code) {
        if (typeof sendResponse === 'function') {
          try { sendResponse({ ok: false, error: 'no_code' }); } catch (_) {}
        }
        return true;
      }
      if (rid) {
        const last = lastCodeByRid.get(rid);
        if (last && last === code) {
          if (typeof sendResponse === 'function') {
            try { sendResponse({ ok: true, deduped: true }); } catch (_) {}
          }
          return true;
        }
        lastCodeByRid.set(rid, code);
        setTimeout(() => {
          if (lastCodeByRid.get(rid) === code) {
            lastCodeByRid.delete(rid);
          }
        }, 90_000);
      }
      const data = (() => {
        const base = msg.data && typeof msg.data === 'object' ? { ...msg.data } : {};
        if (code && !base.code) base.code = code;
        if (rid && !base.rid) base.rid = rid;
        if (phone && !base.phone) base.phone = phone;
        return base;
      })();
      const obj = { event: 'external_code', data };
      send(obj);
      console.log('[WS-BRIDGE] external_code forwarded', { code, rid: rid || null });
      const payload = { type: 'external_code', rid, code, value: code };
      send(payload);
      if (rid && activeRid === rid) {
        activeRid = null;
        activeRidUntil = 0;
      }
      if (typeof sendResponse === 'function') {
        try { sendResponse({ ok: true, ackReceived: true }); } catch (_) {}
      }
      return true;
    }

    if (type === 'external_error') {
      const err = msg.error ?? payloadIn.error ?? 'unknown_error';
      send({ type: 'external_error', rid, error: err });
      if (typeof sendResponse === 'function') {
        try { sendResponse({ ok: true }); } catch (_) {}
      }
      return true;
    }
  } catch (e) {
    console.warn('runtime message handler error', e);
  }
});

// --- when start_number_registration goes out, tell content to unfreeze ---
function __broadcastUnfreeze(tabId){
  try{ chrome.tabs.sendMessage(tabId, {type:'start_number_registration'}); }catch(e){}
}
/* unfreeze-on-start */


// --- when external_number arrives from content, freeze further copies until next command ---
try{
  chrome.runtime.onMessage.addListener((msg, sender) => {
    if (msg && msg.type==='external_number'){
      const tabId = sender && sender.tab && sender.tab.id;
      try{ if (tabId) chrome.tabs.sendMessage(tabId, {type:'freeze_copy'}); }catch(e){}
      console.log('[WS-BRIDGE] freeze_copy sent to tab', tabId);
    }
  });
}catch(e){}
/* freeze-on-number */

// === Close only after cleanup done ===
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === 'account_cleanup_done') {
    const tabId = sender?.tab?.id;
    const ok = !!msg.ok;
    const watcherEntry = typeof tabId === 'number' ? cleanupWatchers.get(tabId) || null : null;
    const watcherCompleted = watcherEntry?.completed === true;
    if (typeof tabId === 'number') {
      detachCleanupWatcher(tabId);
    }
    if (watcherCompleted && ok) {
      return;
    }
    setTimeout(() => {
      try { if (ok && tabId) chrome.tabs.remove(tabId); } catch (e) {}
      try { chrome.runtime.sendMessage({ type: 'cleanup_done_broadcast', ok }); } catch (e) {}
    }, 1200);
  }
});

