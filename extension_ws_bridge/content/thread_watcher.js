(function(){
  const TICK_MS   = 120;
  const DEDUPE_MS = 45_000;

  const ROW_BTN     = 'button.button.plain.thread-element-wrapper, button.thread-element-wrapper, .thread-list button.thread-element';
  const PREVIEW     = '.thread-element-content .thread-last-message, p.thread-last-message';
  const DIALOG_TEXT = '.chat-window .message .text, .chat-window [class*="message"] [class*="text"], .chat-window .content-row p';

  window.__currentRid = window.__currentRid || null;
  window.__currentPhone = window.__currentPhone || null;

  let ARMED = false;
  let FROZEN = false;
  let SEND_LOCK = false;
  let lastCode = null;
  let lastTs = 0;
  let ignoreCode = null;

  const now = () => Date.now();
  const wait = (ms) => new Promise(r=>setTimeout(r,ms));

  function extractCode(text){
    const m = (text||'').match(/\b(\d{4,8})\b/);
    return m ? m[1] : null;
  }

  function readDialog(){
    const nodes = document.querySelectorAll(DIALOG_TEXT);
    if (!nodes.length) return null;
    const last = nodes[nodes.length-1];
    return extractCode((last.innerText||last.textContent||'').trim());
  }

  function readPreview(){
    const row = topRow();
    if (!row) return null;
    const el = row.querySelector(PREVIEW) || row;
    const text = (el.innerText || el.textContent || '').trim();
    return extractCode(text);
  }

  function robustClick(el){
    if (!el) return;
    try { el.scrollIntoView({block:'nearest'}); } catch(e){}
    const r = el.getBoundingClientRect();
    const pts = [
      [r.left + r.width/2, r.top + r.height/2],
      [r.left + r.width*0.7, r.top + r.height/2],
      [r.left + r.width*0.3, r.top + r.height/2],
    ];
    for (const [cx,cy] of pts) {
      const t = document.elementFromPoint(cx, cy) || el;
      let btn = (t.closest && t.closest('button.button.plain.thread-element-wrapper'))
             || (t.closest && t.closest('button'))
             || el.closest?.('button')
             || el;
      if (!(btn instanceof HTMLElement)) btn = el;
      if (btn.matches && btn.matches('div.ripple-wrapper.plain')) {
        const up = btn.closest('button');
        if (up) btn = up;
      }
      ['pointerdown','mousedown','mouseup','click'].forEach(type=>{
        btn.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window,clientX:cx,clientY:cy}));
      });
    }
  }

  function topRow(){
    return document.querySelector(ROW_BTN);
  }

  async function openTopThreadAndWait(){
    const row = topRow();
    if (!row) return false;
    if (row.classList?.contains('active')) return true;
    const t0 = Date.now();
    while (Date.now() - t0 < 1500) {
      robustClick(row);
      await wait(100);
      if (row.classList?.contains('active') || document.querySelector(DIALOG_TEXT)) return true;
    }
    const inner = row.querySelector('.thread-element-content') || row;
    robustClick(inner);
    const t1 = Date.now();
    while (Date.now() - t1 < 800) {
      await wait(80);
      if (row.classList?.contains('active') || document.querySelector(DIALOG_TEXT)) return true;
    }
    return false;
  }

  function sendCode(code){
    if (!code) return;
    if (SEND_LOCK) return;
    if (ignoreCode && code === ignoreCode) return;
    const ts = now();
    if (code === lastCode && (ts - lastTs) < DEDUPE_MS) return;
    try {
      SEND_LOCK = true;
      chrome.runtime.sendMessage({ type:'external_code', data:{ code, rid:window.__currentRid, phone:window.__currentPhone } });
      lastCode = code;
      lastTs = ts;
      ARMED = false;
      FROZEN = true;
      setTimeout(()=>{ FROZEN = false; SEND_LOCK = false; }, 25_000);
    } catch (e) {
      SEND_LOCK = false;
      console.warn('[thread_watcher] sendCode fail', e);
    }
  }

  async function tick(){
    if (!ARMED || FROZEN) return;

    const inDialog = readDialog();
    if (inDialog){
      if (ignoreCode && inDialog === ignoreCode) return;
      if (inDialog!==lastCode || (now()-lastTs)>DEDUPE_MS) sendCode(inDialog);
      return;
    }

    await openTopThreadAndWait();
    await wait(200);
    const afterClick = readDialog();
    if (afterClick){
      if (ignoreCode && afterClick === ignoreCode) return;
      if (afterClick!==lastCode || (now()-lastTs)>DEDUPE_MS) sendCode(afterClick);
      return;
    }

    const prev = readPreview();
    if (prev) {
      if (ignoreCode && prev === ignoreCode) return;
      if (prev!==lastCode || (now()-lastTs)>DEDUPE_MS) sendCode(prev);
    }
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse)=>{
    if (!msg || !msg.type) return;
    if (msg.type==='arm_sms'){
      ARMED = true; FROZEN=false; SEND_LOCK=false;
      ignoreCode = lastCode || null;
      sendResponse && sendResponse({armed:true});
      return true;
    }
    if (msg.type==='set_current_rid' || msg.type==='set_rid'){
      window.__currentRid = msg.rid || null;
      window.__currentPhone = msg.phone || null;
      sendResponse && sendResponse({ok:true});
      return true;
    }
    if (msg.type==='set_last_code'){
      ignoreCode = (msg.code||'').trim() || null;
      sendResponse && sendResponse({ok:true});
      return true;
    }
    if (msg.type==='force_scan'){
      tick();
      sendResponse && sendResponse({ok:true});
      return true;
    }
    return true;
  });

  setInterval(tick, TICK_MS);
  new MutationObserver(()=> tick()).observe(document.body,{childList:true,subtree:true,characterData:true});
})();
