
// background.js — Native Messaging; opens tab on 'navigate', forwards other actions.
let nmPort = null;

function log(...a){ try{ console.log(...a); }catch(_){} }

async function open2no(url) {
  const target = url || "https://2nd-no.com/auth/login";
  log("Navigating to", target);
  // Try to reuse existing tab
  let [tab] = await chrome.tabs.query({ url: "*://2nd-no.com/*" });
  if (tab) {
    try { await chrome.tabs.update(tab.id, { active: true, url: target }); } catch(e) { log("tabs.update failed:", e); }
    return tab.id;
  }
  // Or create a new one
  const created = await chrome.tabs.create({ url: target, active: true });
  return created.id;
}

async function forwardToContent(cmd) {
  let [tab] = await chrome.tabs.query({ url: "*://2nd-no.com/*" });
  if (!tab) tab = await chrome.tabs.create({ url: "https://2nd-no.com/auth/login", active: true });
  await new Promise(r => setTimeout(r, 800));
  return await new Promise((resolve) => {
    chrome.tabs.sendMessage(tab.id, cmd, (resp) => resolve(resp));
  });
}

async function handleHostMessage(msg){
  if (!msg) return;
  if (msg.action === "navigate") {
    const url = msg.params && msg.params.url;
    for (let i=0;i<3;i++){ try { await open2no(url); break; } catch(e){ await new Promise(r=>setTimeout(r,500)); } }
    try { nmPort && nmPort.postMessage({ event: "onNavigate", ok: true }); } catch(_) {}
    return;
  }
  await forwardToContent(msg);
}

function ensurePort() {
  if (nmPort) return nmPort;
  nmPort = chrome.runtime.connectNative("com.bazos.bridge");
  nmPort.onMessage.addListener(handleHostMessage);
  nmPort.onDisconnect.addListener(() => { log("Native host disconnected"); nmPort = null; });
  log("Native host connected");
  return nmPort;
}

// Start host as soon as SW starts
ensurePort();
