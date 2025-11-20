
// background.js - debugger.attach implementation for setValue/navigate via native host
let nmPort = null;

function log(...a){ try{ console.log.apply(console, a); }catch(e){} }

function ensurePort() {
  if (nmPort) return nmPort;
  try {
    nmPort = chrome.runtime.connectNative("com.bazos.bridge");
  } catch (e) {
    console.error("connectNative failed", e);
    nmPort = null;
    return null;
  }
  nmPort.onMessage.addListener(async (msg) => {
    try {
      await handleHostMessage(msg);
    } catch(e) {
      console.error("handleHostMessage error", e);
    }
  });
  nmPort.onDisconnect.addListener(() => { log("Native host disconnected"); nmPort = null; });
  log("Native host connected");
  return nmPort;
}

async function ensureTab(url) {
  const target = url || "https://2nd-no.com/auth/login";
  let tabs = await chrome.tabs.query({ url: "*://2nd-no.com/*" });
  if (tabs && tabs.length) return tabs[0];
  return await chrome.tabs.create({ url: target, active: true });
}

function attachAndEval(tabId, expression) {
  return new Promise((resolve, reject) => {
    try {
      chrome.debugger.attach({ tabId: tabId }, "1.3", () => {
        if (chrome.runtime.lastError) {
          return reject(chrome.runtime.lastError.message);
        }
        chrome.debugger.sendCommand({ tabId: tabId }, "Runtime.evaluate", {
          expression: expression,
          awaitPromise: true,
          returnByValue: true
        }, (res) => {
          // detach after command
          try { chrome.debugger.detach({ tabId: tabId }, () => {}); } catch(e) {}
          if (chrome.runtime.lastError) {
            return reject(chrome.runtime.lastError.message);
          }
          resolve(res);
        });
      });
    } catch (e) {
      reject(e);
    }
  });
}

function buildSetValueExpression(selector, value) {
  const sel = JSON.stringify(selector);
  const val = JSON.stringify(value);
  return `(()=>{ try{ const el = document.querySelector(${sel}); if(!el) return {ok:false, error:'not_found'}; el.focus(); el.value = ${val}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); return {ok:true}; }catch(e){ return {ok:false, error: String(e)}; } })()`;
}

async function handleHostMessage(msg) {
  if (!msg || !msg.action) return;
  if (msg.action === "navigate") {
    const url = msg.params && msg.params.url;
    const tab = await ensureTab(url);
    try { await chrome.tabs.update(tab.id, { url: msg.params && msg.params.url || tab.url }); } catch(e) {}
    await new Promise(r => setTimeout(r, 1200));
    try { nmPort && nmPort.postMessage({ event: "onNavigate", ok: true }); } catch(e){}
    return;
  }
  if (msg.action === "setValue") {
    const selector = (msg.params && msg.params.selector) || "input[placeholder='Email']";
    const value = (msg.params && msg.params.value) || "";
    const tab = await ensureTab();
    const expr = buildSetValueExpression(selector, value);
    try {
      const res = await attachAndEval(tab.id, expr);
      try { nmPort && nmPort.postMessage(Object.assign({ event: "onSetValue" }, res)); } catch(e){};
    } catch (e) {
      try { nmPort && nmPort.postMessage({ event: "onError", error: String(e) }); } catch(e){};
    }
    return;
  }
  const tab = await ensureTab();
  try {
    await new Promise(r => setTimeout(r, 800));
    chrome.tabs.sendMessage(tab.id, msg, (resp) => {
      try { nmPort && nmPort.postMessage(Object.assign({ event: "forwarded" }, resp)); } catch(e){};
    });
  } catch(e) {}
}

ensurePort();
