/* Click 'Login with Google' on 2nd-no.com */
(async () => {

window.__DISABLE_AUTORUN__ = true;

function _autoClick(el){
  try{
    const r = el.getBoundingClientRect();
    const x = r.left + Math.min(5, r.width/2);
    const y = r.top + Math.min(5, r.height/2);
    const o = {bubbles:true, cancelable:true, clientX:x, clientY:y, composed:true};
    el.dispatchEvent(new PointerEvent('pointerdown', o));
    el.dispatchEvent(new MouseEvent('mousedown', o));
    el.dispatchEvent(new PointerEvent('pointerup', o));
    el.dispatchEvent(new MouseEvent('mouseup', o));
  }catch(e){}
  el.click();
}

async function clickGoogleGsiIframe(){
  const ifr = Array.from(document.querySelectorAll('iframe')).find(f => {
    const s = f.getAttribute('src') || '';
    return /accounts\.google\.com\/gsi\/button/i.test(s);
  });
  if(!ifr) return false;
  ifr.scrollIntoView({behavior:'smooth', block:'center'});
  await new Promise(r=>setTimeout(r,120));
  _autoClick(ifr);
  return true;
}

  let list = [];
const { autoClick } = await chrome.storage.local.get(['autoClick']);
  if (autoClick === false) return;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function visible(el){ return el && el.offsetParent !== null; }

  function findCandidates(){
    const list = [];
    document.querySelectorAll('button, a, div[role="button"], .btn, .button').forEach(el => {
      const t = (el.innerText || '').trim().toLowerCase();
      if (t && (t.includes('login with google') || t.includes('sign in with google') || t.includes('войти через google') || t.includes('вход через google'))) {
        if (visible(el)) list.push(el);
      }
    });
    // common google button classes
    document.querySelectorAll('[data-provider="google"], .gsi-material-button, .google').forEach(el => { if (visible(el)) list.push(el); });
    // fallback: look for the section that contains the text and click nearest button
    if (!list.length) {
      const label = Array.from(document.querySelectorAll('div,button,a')).find(el => (el.innerText||'').toLowerCase().includes('login with google'));
      if (label) {
        let btn = label.closest('button, a, div[role="button"]') || label;
        if (visible(btn)) list.push(btn);
      }
    }
    // de-dup
    return Array.from(new Set(list));
  }

  async function run(){
    for (let i=0;i<840;i++){
      const cands = findCandidates();
      if (cands.length){
        await sleep(500 + Math.random()*700);
        const el = cands[0];
        el.scrollIntoView({behavior:'smooth', block:'center'});
        await sleep(200 + Math.random()*300);
        el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
        await sleep(150 + Math.random()*200);
        el.click();
        console.log('[2no-ext] Clicked Google login');
        return;
      }
      await sleep(250);
    }
  }
  run();
})();
