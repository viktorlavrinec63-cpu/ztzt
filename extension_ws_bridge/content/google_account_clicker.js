(function(){
  function clickAccountTile(preferredEmail){
    const tiles = Array.from(document.querySelectorAll('[data-identifier], div[role="button"], div[tabindex="0"]'));
    if (preferredEmail) {
      const lower = preferredEmail.trim().toLowerCase();
      const exact = tiles.find(el => (el.getAttribute('data-identifier')||'').trim().toLowerCase() === lower);
      if (exact) { exact.click(); return true; }
      const contains = tiles.find(el => (el.innerText||el.textContent||'').toLowerCase().includes(lower));
      if (contains) { contains.click(); return true; }
    }
    const withEmail = tiles.find(el => /@/.test((el.getAttribute('data-identifier')||'') + (el.innerText||'')));
    if (withEmail) { withEmail.click(); return true; }
    if (tiles[0]) { tiles[0].click(); return true; }
    return false;
  }

  function clickContinueAllow(){
    const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
    const labels = ['continue', 'allow', 'разрешить', 'продолжить', 'continue to', 'yes'];
    const hit = btns.find(b => {
      const t = (b.innerText||b.textContent||'').trim().toLowerCase();
      return labels.some(l => t.includes(l));
    });
    if (hit) { hit.click(); return true; }
    return false;
  }

  function clickNext(){
    const btn = Array.from(document.querySelectorAll('button, div[role="button"]'))
      .find(b => /next|далее/i.test((b.innerText||b.textContent||'')));
    if (btn) { btn.click(); return true; }
    return false;
  }

  function tick(preferredEmail){
    if (!/accounts\.google\.com/.test(location.hostname)) return true;
    if (clickAccountTile(preferredEmail)) return false;
    if (clickContinueAllow()) return false;
    if (clickNext()) return false;
    return false;
  }

  let preferredEmail = window.__preferredGoogleEmail || null;

  let tries = 0, maxTries = Math.ceil(25_000 / 250);
  const timer = setInterval(() => {
    tries++;
    const done = tick(preferredEmail);
    if (done || tries >= maxTries) clearInterval(timer);
  }, 250);

  const mo = new MutationObserver(() => tick(preferredEmail));
  mo.observe(document.documentElement, {childList:true, subtree:true});

  window.addEventListener('beforeunload', () => { try{ mo.disconnect(); }catch(_){} });
})();
