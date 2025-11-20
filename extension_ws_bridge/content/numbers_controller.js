// ultra-simple clicker for /app/numbers
(() => {
  if (window.__twoNoNumbersUltra) return;
  window.__twoNoNumbersUltra = true;

  let __currentRid = null;
  let __createBusy = false;
  let __smsBusy = false;

  chrome.runtime.onMessage.addListener((msg)=>{
    if (!msg || !msg.type) return;
    if (msg.type==='set_rid' || msg.type==='set_current_rid'){ __currentRid = msg.rid || __currentRid; return; }
    if (msg.type==='create_number' || msg.type==='start_number_registration'){
      const rid = msg.rid || __currentRid || null;
      if (rid) __currentRid = rid;
      if (__createBusy) return;
      __createBusy = true;
      runCreate(rid).catch(()=>{}).finally(()=>{ __createBusy = false; });
      return;
    }
    if (msg.type==='start_sms_wait'){
      const rid = msg.rid || __currentRid || null;
      if (rid) __currentRid = rid;
      if (__smsBusy) return;
      __smsBusy = true;
      waitSmsCode(rid).catch(()=>{}).finally(()=>{ __smsBusy = false; });
      return;
    }
  });

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const jitter = (base, spread=300) => base + Math.floor(Math.random()*spread);
  async function clickHuman(el){
    if (!el) return;
    try { el.scrollIntoView({ behavior:'smooth', block:'center' }); } catch(e){}
    await sleep(jitter(700,400));
    el.dispatchEvent(new MouseEvent('pointerdown', { bubbles:true }));
    await sleep(jitter(220,180));
    el.dispatchEvent(new MouseEvent('pointerup', { bubbles:true }));
    await sleep(jitter(220,180));
    el.click();
  }
  const log  = (...a) => { try { console.log('[2no-ext][numbers]', ...a); } catch(e) {} };
  const warn = (...a) => { try { console.warn('[2no-ext][numbers]', ...a); } catch(e) {} };
  const AUTO_SMS_AFTER_NUMBER = true;

  async function copyTextToClipboard(text){
    try {
      if (navigator.clipboard && navigator.clipboard.writeText){
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch(e){}
    try {
      const ta = document.createElement('textarea');
      ta.value = text || '';
      ta.setAttribute('readonly','');
      ta.style.position='fixed';
      ta.style.opacity='0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      return true;
    } catch(e){ return false; }
  }

  // ======== SMS helpers ========
  function messagesNavButton(){
    const sels = [
      'a[href*="/app/messages"]',
      'nav a[href*="/messages"]',
      'a:has(svg[aria-label*="message" i])',
      'a,button'
    ];
    for (const sel of sels){
      for (const el of document.querySelectorAll(sel)){
        const t = (el.textContent || '').toLowerCase();
        if (el.href?.includes('/app/messages') || t.includes('messages') || t.includes('сообщения') || t.includes('wiadomo')){
          return el;
        }
      }
    }
    return null;
  }

  async function ensureSmsTab(){
    if (location.pathname.includes('/app/messages')) return true;
    const btn = messagesNavButton();
    if (!btn) return false;
    await clickHuman(btn);
    const t0 = Date.now();
    while(Date.now()-t0 < 8000){
      await sleep(200);
      if (location.pathname.includes('/app/messages')) return true;
    }
    return location.pathname.includes('/app/messages');
  }

  function smsFirstRow(){
    const sels = [
      '[data-test="sms-row"]',
      '.MessageListItem',
      '[role="listitem"]',
      '.row, li'
    ];
    for (const sel of sels){
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function extractSmsCode(){
    const roots = [
      document.querySelector('[data-test="sms-panel"]'),
      document.querySelector('.MessageView'),
      document
    ].filter(Boolean);
    for (const root of roots){
      const txt = (root.textContent || '').trim();
      if (!txt) continue;
      const m = txt.match(/(?<!\d)(\d{6,8})(?!\d)/);
      if (m) return m[1];
    }
    return null;
  }

  async function waitSmsCode(rid, timeoutMs = 60000){
    if (rid) __currentRid = rid;
    const ok = await ensureSmsTab();
    if (!ok){
      try { chrome.runtime.sendMessage({ type:'external_error', rid: __currentRid, error:'open_messages_failed' }); } catch(e){}
      return false;
    }
    const row = smsFirstRow();
    if (row){
      try { row.click(); } catch(e){}
      await sleep(300);
    }
    const t0 = Date.now();
    let last = null;
    while(Date.now()-t0 < timeoutMs){
      const code = extractSmsCode();
      if (code && code !== last){
        last = code;
        try { chrome.runtime.sendMessage({ type:'external_code', code, rid: __currentRid }); } catch(e){}
        try { chrome.runtime.sendMessage({ type:'external_code', payload:{ code, rid: __currentRid } }); } catch(e){}
        try { await copyTextToClipboard(code); } catch(e){}
        log('external_code sent & copied', code, 'rid=', __currentRid);
        return true;
      }
      await sleep(700);
    }
    try { chrome.runtime.sendMessage({ type:'external_error', rid: __currentRid, error:'sms_timeout' }); } catch(e){}
    return false;
  }

  function visible(el){
    if(!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
  }

  function byXPath(xp){
    try {
      const res = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      return res.singleNodeValue || null;
    } catch(e){ return null; }
  }

  function findButton(){
    // 0) exact xpath (from working ext) -> click nearest button
    const xpDiv = '//*[@id="app"]/div[1]/div[2]/div[2]/div[2]/div/div/div[1]/div/div/div[2]/button/div';
    const xnode = byXPath(xpDiv);
    if (xnode) {
      const b = xnode.closest('button, [role="button"], a') || xnode;
      if (visible(b)) return b;
    }
    // 1) canonical selector
    let btn = document.querySelector('button.number-form-button');
    if (btn && visible(btn)) return btn;
    // 2) ripple wrapper
    const rw = document.querySelector('div.ripple-wrapper.primary');
    if (rw && visible(rw)) return rw;
    // 3) i18n text search
    const texts = ['add new number','добавить новый номер','додати новий номер','dodaj nowy numer','dodaj numer','add number'];
    for (const el of document.querySelectorAll('button, .button, [role="button"], a, .ripple-wrapper')){
      if (!visible(el)) continue;
      const t = (el.textContent || '').toLowerCase().trim();
      if (t && texts.some(s=>t.includes(s))) return el;
    }
    return null;
  }

  function clickTopCenter(target){
    const r = target.getBoundingClientRect();
    const x = Math.floor(r.left + r.width/2);
    const y = Math.floor(r.top + r.height/2);
    const topEl = document.elementFromPoint(x, y) || target;
    topEl.scrollIntoView({behavior:'smooth', block:'center'});
    const o = {bubbles:true, cancelable:true, clientX:x, clientY:y, composed:true};
    try {
      topEl.dispatchEvent(new PointerEvent('pointerdown', o));
      topEl.dispatchEvent(new MouseEvent('mousedown', o));
      topEl.dispatchEvent(new PointerEvent('pointerup', o));
      topEl.dispatchEvent(new MouseEvent('mouseup', o));
      topEl.click();
    } catch(e){}
  }

  function findVisible(sel){
    for (const el of document.querySelectorAll(sel)){
      if (visible(el)) return el;
    }
    return null;
  }

  async function waitForVisible(sel, timeout=20000){
    const t0 = Date.now();
    while(Date.now()-t0 < timeout){
      const el = findVisible(sel);
      if (el) return el;
      await new Promise(r=>setTimeout(r,200));
    }
    return null;
  }

  function i18nIncludes(text, arr){
    const t = (text||'').toLowerCase();
    return arr.some(p => t.includes(p));
  }

  function findLabelCheckbox(phrases){
    for (const lbl of document.querySelectorAll('label')){
      const t = (lbl.textContent || '').toLowerCase();
      if (i18nIncludes(t, phrases)){
        const inp = lbl.querySelector('input[type="checkbox"]') || lbl.parentElement?.querySelector('input[type="checkbox"]');
        return inp ? lbl : null;
      }
    }
    return null;
  }

  async function fillNameWithRandomDigits(n=5){
    const namePhrases = ['name','imię','nazwa','имя','назва'];
    let input = null;
    for (const lbl of document.querySelectorAll('label')){
      const t = (lbl.textContent||'').toLowerCase();
      if (i18nIncludes(t, namePhrases)){
        input = lbl.parentElement?.querySelector('input,textarea') || lbl.querySelector('input,textarea');
        if (input) break;
      }
    }
    if (!input) {
      const form = findVisible('form');
      input = form?.querySelector('input[type="text"], input[type="number"], textarea');
    }
    if (!input) return false;
    const digits = Math.random().toString().slice(2, 2+n);
    input.focus();
    input.value = digits;
    input.dispatchEvent(new Event('input', {bubbles:true}));
    return true;
  }

  async function tickCheckboxes(){
    const waivePhrases = [
      'waive the right to transfer the number','waive the right',
      'отказываюсь от права переноса','переноса номера',
      'відмовляюсь від права перенесення','перенесення номера',
      'zrzekam się prawa do przeniesienia','rezygnuję z prawa do przeniesienia','rezygnuje z prawa do przeniesienia'
    ];
    const marketingPhrases = [
      'agree to receive marketing content','marketing content',
      'согласен получать маркетинг','маркетинговые материалы',
      'zgadzam się na otrzymywanie treści marketingowych','materiałów marketingowych','treści marketingowe'
    ];

    const waive = findLabelCheckbox(waivePhrases);
    if (waive){ waive.click(); await sleep(150); }
    const marketing = findLabelCheckbox(marketingPhrases);
    if (marketing){ marketing.click(); await sleep(150); }
  }

  async function waitCloudflareOk(timeoutMs = 30000) {
    const start = Date.now();

    function hasSuccessWord() {
      try {
        const body = document.body;
        if (!body) return false;
        // innerText берётся из рендер-дерева, поэтому видит текст даже из shadow-DOM
        const text = (body.innerText || '').toLowerCase();
        return text.includes('успешно');
      } catch (e) {
        return false;
      }
    }

    // если надпись уже есть — выходим сразу
    if (hasSuccessWord()) {
      console.log('[WS-BRIDGE] Cloudflare: "Успешно" detected immediately');
      return true;
    }

    while (Date.now() - start < timeoutMs) {
      if (hasSuccessWord()) {
        console.log('[WS-BRIDGE] Cloudflare: "Успешно" detected');
        return true;
      }
      await sleep(500);  // проверяем два раза в секунду
    }

    console.warn('[WS-BRIDGE] Cloudflare: "Успешно" not detected within timeout, continue anyway');
    return false;
  }

  async function submitFinal(){
    const form = findVisible('form');
    if (!form) return false;
    let btn = form.querySelector('button[type="submit"]');
    if (!btn){
      const texts = ['add new number','добавить новый номер','dodaj nowy numer','dodaj numer','add number','confirm','создать','finish','continue','далее','продолжить'];
      for (const el of form.querySelectorAll('button, [role="button"], a')){
        const t = (el.textContent||'').toLowerCase();
        if (texts.some(s=>t.includes(s))) { btn = el; break; }
      }
    }
    if (!btn) return false;
    clickTopCenter(btn);
    return true;
  }

  function normalizeNumberText(t){
    if(!t) return '';
    t = String(t).replace(/\u00A0/g,' ').replace(/[()]/g,' ').replace(/\s+/g,' ').trim();
    const m = t.match(/\+\d[\d\s\-]{7,}/);
    return m ? m[0].replace(/[^\d+]/g,'') : '';
  }

  async function findAndReportFirstNumber(timeout=30000){
    const start = Date.now();
    while(Date.now()-start < timeout){
      const cells = document.querySelectorAll('table tr td:first-child, .table-list-element .title, [role="row"] [role="cell"]:first-child');
      for (const c of cells){
        const num = normalizeNumberText(c.textContent);
        if (!num || num.length <= 6) continue;
        try { await copyTextToClipboard(num); } catch(e){}
        try {
          chrome.runtime.sendMessage({ type:'external_number', number: num, rid: __currentRid });
          chrome.runtime.sendMessage({ type:'external_number', payload: { number: num, rid: __currentRid } });
        } catch(e){}
        log('external_number (table) sent & copied', num, 'rid=', __currentRid);
        if (AUTO_SMS_AFTER_NUMBER) {
          try { await sleep(300); await waitSmsCode(__currentRid, 60000); } catch(e){}
        }
        return true;
      }
      const rows = document.querySelectorAll('.table-list-element, tr, .row, [role="row"]');
      for (const row of rows){
        const txt = (row.textContent || '').trim();
        if (!txt) continue;
        const match = txt.match(/\+\d[\d\s]{5,}/);
        if (!match) continue;
        const num = normalizeNumberText(match[0]);
        if (!num || num.length <= 6) continue;
        try { await copyTextToClipboard(num); } catch(e){}
        try {
          chrome.runtime.sendMessage({ type:'external_number', number: num, rid: __currentRid });
          chrome.runtime.sendMessage({ type:'external_number', payload: { number: num, rid: __currentRid } });
        } catch(e){}
        log('external_number sent & copied', num, 'rid=', __currentRid);
        if (AUTO_SMS_AFTER_NUMBER) {
          try { await sleep(300); await waitSmsCode(__currentRid, 60000); } catch(e){}
        }
        return true;
      }
      await sleep(500);
    }
    warn('number not found (table scan timeout)');
    return false;
  }

  async function runCreate(rid){
    if (rid) __currentRid = rid;
    // Avoid duplicate concurrent runs
    if (window.__twoNoNumbersRunning) return;
    window.__twoNoNumbersRunning = true;
    try {
      // если "Add new number" недоступна (лимит), номер уже в таблице — сразу забираем
      if (await findAndReportFirstNumber(1000)) return;

      // 1) click "Add new number"
      let clicked = false;
      const t0 = Date.now();
      const timeout = 45000;

      const obs = new MutationObserver(() => {
        if (clicked) return;
        const b = findButton();
        if (b) { clickTopCenter(b); clicked = true; }
      });
      obs.observe(document.documentElement, {childList:true, subtree:true});

      while(!clicked && Date.now()-t0 < timeout){
        const b = findButton();
        if (b) { clickTopCenter(b); clicked = true; break; }
        await sleep(250);
      }
      obs.disconnect();
      if (!clicked) { window.__twoNoNumbersRunning = false; return; }

      // 2) form flow
      await sleep(5000);
      await waitForVisible('form');
      await fillNameWithRandomDigits(5);
      await tickCheckboxes();
      // надёжная пауза для Cloudflare: 18 секунд (можно поднять до 20000 при желании)
      await sleep(15000);
      await submitFinal();
      await findAndReportFirstNumber(30000);
    } finally {
      window.__twoNoNumbersRunning = false;
    }
  }

  // --- PAGE READY: /app/messages ---
  function emitPageReadyMessages(){
    try{ chrome.runtime.sendMessage({ type: 'page_ready_messages' }); }catch(e){}
  }
  function watchMessagesReady(){
    if (!/\/app\/messages/.test(location.pathname)) return;
    const checker = () => {
      const list = document.querySelector('.thread-list');
      if (list) { emitPageReadyMessages(); return true; }
      return false;
    };
    if (checker()) return;
    const mo = new MutationObserver(()=>{ if (checker()) mo.disconnect(); });
    mo.observe(document.documentElement, {childList:true,subtree:true});
    setTimeout(()=>{ try{ mo.disconnect(); }catch{} }, 30000);
  }
  document.addEventListener('DOMContentLoaded', watchMessagesReady);
  watchMessagesReady();

})();
