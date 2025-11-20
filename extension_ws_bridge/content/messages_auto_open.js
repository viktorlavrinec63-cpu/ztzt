// messages_auto_open.js — ручной запуск ожидания SMS по команде из бекграунда
(function(){
  if (window.__msgAutoOpenLoaded) return; window.__msgAutoOpenLoaded = true;
  function sleep(ms){ return new Promise(r=>setTimeout(r, ms)); }
  function jitter(base, spread=300){ return base + Math.floor(Math.random()*spread); }
  async function clickHuman(el){
    try { el.scrollIntoView({ behavior:'smooth', block:'center' }); } catch(e){}
    await sleep(jitter(800,400));
    el.dispatchEvent(new MouseEvent('pointerdown', { bubbles:true }));
    await sleep(jitter(220,180));
    el.dispatchEvent(new MouseEvent('pointerup', { bubbles:true }));
    await sleep(jitter(220,180));
    el.click();
  }

  const log = (...a)=>{ try{ console.log('[2no-msg]', ...a);}catch(e){} };
  let currentRid = null;
  let busy = false;

  async function humanNavigateToMessagesAndOpenThread() {
    const selectors = [
      'a[href*="/app/messages"]',
      'nav a, nav button',
      'a[role="button"]',
      'a,button'
    ];
    let target = null;
    for (const sel of selectors) {
      const list = Array.from(document.querySelectorAll(sel));
      target = list.find(el => {
        const t = (el.innerText||'').toLowerCase();
        const a = (el.getAttribute('aria-label')||'').toLowerCase();
        const h = (el.getAttribute('href')||'').toLowerCase();
        return /message|сообщен/.test(t) || /message/.test(a) || /\/messages/.test(h);
      });
      if (target) break;
    }
    if (!target) throw new Error('Messages control not found');

    await clickHuman(target);

    const listSel = ['[data-testid="threads-list"]','section ul','div[role="list"]','div[aria-label*="messages"] ul'];
    let listRoot = null;
    for (let i=0;i<12 && !listRoot;i++){
      await sleep(jitter(500,250));
      for (const s of listSel) {
        const cand = document.querySelector(s);
        if (cand && cand.querySelector('li,[role="listitem"],a,button')) { listRoot = cand; break; }
      }
    }
    if (!listRoot) throw new Error('Messages list not ready');

    const thread = listRoot.querySelector('[data-unread="true"], li, [role="listitem"], a, button');
    if (!thread) throw new Error('No threads');
    await clickHuman(thread);

    await sleep(jitter(800,300));
  }

  function extractCode(){
    const rightPane = document.querySelector('.chat-window, .chat, .messages, [class*="chat-window"]');
    const txt = (rightPane && rightPane.textContent) || (document.body ? document.body.textContent : '') || '';
    const m = txt.match(/(?<!\d)(\d{4,8})(?!\d)/g);
    return m ? m[m.length-1] : '';
  }

  async function copy(text){
    try{
      if (navigator.clipboard && navigator.clipboard.writeText){
        await navigator.clipboard.writeText(text);
        return true;
      }
    }catch(e){}
    const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta);
    ta.select(); try{ document.execCommand('copy'); }catch(e){}
    document.body.removeChild(ta); return true;
  }

  async function waitForCode(rid, timeoutMs=60000){
    const start = Date.now();
    let lastCode = null;
    while(Date.now() - start < timeoutMs){
      const code = extractCode();
      if (code && code !== lastCode){
        lastCode = code;
        try{ chrome.runtime.sendMessage({type:'external_code', payload:{code, rid}, rid}); }catch(e){}
        try{ await copy(code); }catch(e){}
        log('sent external_code:', code, 'rid:', rid);
        return true;
      }
      await sleep(600);
    }
    return false;
  }

  function handleStartSmsWait(rid, navPromise){
    if (busy) return;
    busy = true;
    (async()=>{
      try {
        await navPromise;
      } catch (e) {
        console.warn('[SMS NAV FAIL]', e);
      }
      const ok = await waitForCode(rid);
      if (!ok){
        try{ chrome.runtime.sendMessage({ type:'external_error', payload:{ rid, error:'sms_code_timeout' } }); }catch(e){}
      }
    })().finally(()=>{ busy = false; });
  }

  chrome.runtime.onMessage.addListener((msg)=>{
    if (!msg || !msg.type) return;
    if (msg.type === 'set_rid' || msg.type === 'set_current_rid'){ currentRid = msg.rid || currentRid; }
    if (msg.type === 'start_sms_wait'){
      const rid = msg.rid || currentRid || null;
      if (!rid) return;
      currentRid = rid;
      const navPromise = (async()=>{ try{ await humanNavigateToMessagesAndOpenThread(); }catch(e){ console.warn('[SMS NAV FAIL]', e); throw e; } })();
      handleStartSmsWait(rid, navPromise);
    }
  });
})();
