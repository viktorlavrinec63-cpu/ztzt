(function(){
  const cfgDefault = {
    preModalMs: 500,
    beforeConfirmDeleteMs: 1200,
    afterConfirmMs: 800,
    timeoutMs: 15000
  };

  const sleep = (ms)=> new Promise(r=>setTimeout(r, ms));
  const now = ()=> Date.now();

  async function waitForSelector(sel, {timeout=8000, mustBeVisible=true}={}) {
    const t0 = now();
    while (now() - t0 < timeout) {
      const el = document.querySelector(sel);
      if (el) {
        if (!mustBeVisible) return el;
        const rect = el.getBoundingClientRect();
        const visible = rect.width > 0 && rect.height > 0;
        if (visible) return el;
      }
      await sleep(100);
    }
    throw new Error(`waitForSelector timeout: ${sel}`);
  }

  function jitter(ms, spread=0.25){
    const d = ms * spread;
    return ms + Math.floor((Math.random()*2-1)*d);
  }

  async function clickSafe(el){
    el.scrollIntoView({block:'center'});
    await sleep(50);
    el.click();
  }

  async function doDeleteAccount(userCfg={}){
    const cfg = {...cfgDefault, ...userCfg};

    if (!location.pathname.startsWith('/app/settings')) {
      const deadline = now() + cfg.timeoutMs;
      while (now() < deadline) {
        if (location.pathname.startsWith('/app/settings')) break;
        await sleep(150);
      }
      if (!location.pathname.startsWith('/app/settings')) {
        return {ok: false, error: 'not_on_settings_page'};
      }
    }

    const pageDeleteBtn = await waitForSelector(
      'div.page-section.delete-account button.button.delete, div.page-section .button.delete',
      {timeout: 8000}
    );
    await clickSafe(pageDeleteBtn);
    await sleep(jitter(cfg.preModalMs));

    const modal = await waitForSelector('div.modal-base:not([style*="display: none"])', {timeout: 8000, mustBeVisible:true});
    const confirmBtn = await waitForSelector('div.modal-base button.button.delete', {timeout: 8000, mustBeVisible:true});

    await sleep(jitter(cfg.beforeConfirmDeleteMs));
    await clickSafe(confirmBtn);

    await sleep(jitter(cfg.afterConfirmMs));

    let ok = false;
    try {
      const gone = !document.querySelector('div.modal-base') ||
                   document.querySelector('div.modal-base[aria-hidden="true"]');
      ok = !!gone;
    } catch(e){ }

    return {ok};
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === 'CS_DELETE_ACCOUNT') {
      const userCfg = (window.__BazosCfg && window.__BazosCfg.uiDelays) ? window.__BazosCfg.uiDelays : {};
      doDeleteAccount(userCfg)
        .then(r => sendResponse(r))
        .catch(err => sendResponse({ok:false, error: String(err && err.message || err)}));
      return true;
    }
  });

  try { chrome.runtime.sendMessage({type:'page_ready_settings'}); } catch(_){ }
})();
