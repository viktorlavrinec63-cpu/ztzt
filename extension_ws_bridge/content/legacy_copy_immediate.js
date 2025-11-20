// === LEGACY instant copy for 2nd-no numbers ===
(async () => {
  console.log('[LEGACY] injected legacy_copy_immediate.js');
  function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

  async function copyToClipboard(text){
    try { await navigator.clipboard.writeText(text); }
    catch(e){ console.warn('Clipboard error', e); }
  }

  async function sendToBackground(type, value){
    try {
      chrome.runtime.sendMessage({ type, value });
      console.log('[LEGACY] sent', type, value);
    } catch(e){ console.warn('Legacy send fail', e); }
  }

  async function watchNumbers(){
    while(true){
      const el = document.querySelector('table tbody tr td:first-child');
      if (el){
        const phone = el.innerText.trim();
        if (/^\+?\d{5,}/.test(phone)){
          await copyToClipboard(phone);
          await sendToBackground('external_number', phone);
          console.log('[LEGACY] Number found and sent:', phone);
          return;
        }
      }
      await sleep(1500);
    }
  }

  async function watchSms(){
    while(true){
      const msg = document.querySelector('.MessageListItem');
      if (msg){
        const code = (msg.innerText.match(/\d{4,8}/)||[])[0];
        if (code){
          await copyToClipboard(code);
          await sendToBackground('external_code', code);
          console.log('[LEGACY] SMS code found and sent:', code);
          return;
        }
      }
      await sleep(1500);
    }
  }

  if (location.href.includes('/app/numbers')){
    console.log('[LEGACY] start watchNumbers');
    watchNumbers();
  }
  if (location.href.includes('/app/messages')){
    console.log('[LEGACY] start watchSms');
    watchSms();
  }
})();
