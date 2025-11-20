/* content_sms.js — injected on 2nd-no SMS pages */
(() => {
  const CFG_URL = chrome.runtime.getURL("selectors.json");
  const state = {
    cfg: null,
    lastByThread: new Map(), // threadId -> { code, ts }
  };

  function log(...args){ console.log("[WSEXT][content]", ...args); }
  const sleep = (ms)=>new Promise(r=>setTimeout(r,ms));

  async function loadCfg(){
    if (state.cfg) return state.cfg;
    const resp = await fetch(CFG_URL);
    state.cfg = await resp.json();
    return state.cfg;
  }

  function qsAny(root, selectors){
    for (const sel of selectors){
      try {
        const el = root.querySelector(sel);
        if (el) return el;
      } catch(e){ /* ignore invalid selector */ }
    }
    return null;
  }

  function qsaAny(root, selectors){
    for (const sel of selectors){
      try {
        const els = root.querySelectorAll(sel);
        if (els && els.length) return Array.from(els);
      } catch(e){}
    }
    return [];
  }

  function waitFor(predicate, {timeout=15000, interval=200}={}){
    const start = Date.now();
    return new Promise((resolve, reject)=>{
      const t = setInterval(()=>{
        try{
          const v = predicate();
          if (v){ clearInterval(t); resolve(v); }
          else if (Date.now()-start > timeout){
            clearInterval(t); reject(new Error("waitFor timeout"));
          }
        }catch(e){
          clearInterval(t); reject(e);
        }
      }, interval);
    });
  }

  function extractCode(text, codeRe){
    const m = text && text.match(codeRe);
    return m ? m[1] : null;
  }

  function findByText(root, texts){
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()){
      const el = walker.currentNode;
      const t = (el.innerText || el.textContent || "").trim().toLowerCase();
      for (const tx of texts){
        if (t.includes(tx.toLowerCase())) return el;
      }
    }
    return null;
  }

  function clickSafe(el){
    if (!el) return false;
    el.dispatchEvent(new MouseEvent("click", {bubbles:true, cancelable:true}));
    return true;
  }

  async function openThreadFromPopup(cfg){
    let anchor = qsAny(document, cfg.popupItem);
    if (anchor) { clickSafe(anchor); return true; }
    const fallback = findByText(document.body, ["new message", "новое сообщение", "sms"]);
    if (fallback){ clickSafe(fallback); return true; }
    return false;
  }

  function currentThreadId(){
    try {
      const m = location.pathname.match(/messages\/([^\/]+)/);
      return m ? m[1] : location.href;
    } catch(e){ return location.href; }
  }

  async function clickUnreadOrFirstThread(cfg){
    const container = await waitFor(()=> qsAny(document, cfg.threadListContainer), { timeout: 20000 });
    // Prefer unread (blue dot / unread class), else first item
    const items = qsaAny(container, cfg.threadListItem);
    if (!items.length) throw new Error("No threads in list");
    // try find with unread marker
    const unread = items.find(it => {
      try {
        const hasBadge = it.querySelector(cfg.threadUnreadBadge[0]) || cfg.threadUnreadBadge.slice(1).some(s=> it.querySelector(s));
        return !!hasBadge;
      }catch(e){ return false; }
    });
    const target = unread || items[0];
    clickSafe(target);
    return true;
  }

  async function readLatestCode(cfg, newOnly){
    const codeRe = new RegExp(cfg.codeRegex, "i");
    const container = await waitFor(()=> qsAny(document, cfg.messageContainer), { timeout: 20000 });
    // brief settle
    await sleep(150);
    const row = qsAny(container, cfg.threadCodeLine) || container.lastElementChild;
    if (!row) throw new Error("No message row found");
    const txt = (row.innerText || row.textContent || "").trim();
    const code = extractCode(txt, codeRe);
    if (!code) throw new Error("No code in last message");
    const tid = currentThreadId();
    const prev = state.lastByThread.get(tid);
    const now = Date.now();
    if (newOnly && prev && prev.code === code) {
      throw new Error("Same code as previous and new_only=true");
    }
    state.lastByThread.set(tid, { code, ts: now });
    return { code, tid };
  }

  async function deleteThreadInPlace(cfg){
    const cand = qsAny(document, cfg.kebabInThread) || findByText(document.body, ["more", "ещё", "ещё…"]);
    if (!cand){ log("kebab not found"); return false; }
    clickSafe(cand);
    await sleep(200);
    const del = findByText(document.body, ["delete thread", "удалить диалог"]) || qsAny(document, cfg.menuDelete);
    if (!del){ log("delete menu not found"); return false; }
    clickSafe(del);
    await sleep(200);
    const confirm = findByText(document.body, ["delete", "удалить", "confirm"]) || qsAny(document, cfg.confirmDelete);
    if (confirm){ clickSafe(confirm); return true; }
    return false;
  }

  // If site renders dynamically, observe and auto-click when new item appears
  function armNewSmsObserver(cfg, rid){
    try{
      const root = qsAny(document, cfg.threadListContainer) || document.body;
      const mo = new MutationObserver((mutations)=>{
        for (const m of mutations){
          for (const n of Array.from(m.addedNodes || [])){
            if (!(n instanceof HTMLElement)) continue;
            // new thread item?
            if (n.matches && cfg.threadListItem.some(sel => { try { return n.matches(sel); } catch(e){ return false; } })) {
              log("new thread node appeared, clicking");
              clickSafe(n);
            } else {
              const cand = qsAny(n, cfg.threadListItem);
              if (cand){ log("new thread child appeared, clicking"); clickSafe(cand); }
            }
          }
        }
      });
      mo.observe(root, { childList:true, subtree:true });
      log("new SMS observer armed", !!root);
      return mo;
    }catch(e){
      log("observer failed", e && e.message);
      return null;
    }
  }

  // Message bus with SW
  chrome.runtime.onMessage.addListener(async (msg, _sender, sendResponse) => {
    if (!msg || !msg.type) return;
    try{
      await loadCfg();
      if (msg.type === "start_sms_watch"){
        const { rid, new_only } = msg;
        log("start_sms_watch", rid, { new_only });
        const mo = armNewSmsObserver(state.cfg, rid);
        // Try popup first; if not found, click unread/first in list
        const opened = await openThreadFromPopup(state.cfg);
        if (!opened){
          await clickUnreadOrFirstThread(state.cfg);
        }
        // read code
        const { code, tid } = await readLatestCode(state.cfg, !!new_only);
        chrome.runtime.sendMessage({ type: "external_code", rid, code, threadId: tid });
        // delete thread best-effort
        const ok = await deleteThreadInPlace(state.cfg);
        chrome.runtime.sendMessage({ type: "thread_deleted", rid, ok, threadId: tid });
        if (mo) mo.disconnect();
        sendResponse({ ok: true });
        return true;
      }
    } catch(e){
      log("error:", e && e.message);
      chrome.runtime.sendMessage({ type: "external_error", reason: e && e.message });
      sendResponse({ ok:false, error: String(e && e.message) });
    }
    return true;
  });
})();
