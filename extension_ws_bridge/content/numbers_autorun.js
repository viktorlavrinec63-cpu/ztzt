(() => {
  if (window.__2NO_NUMBERS_AUTORUN_STUB__) return;
  window.__2NO_NUMBERS_AUTORUN_STUB__ = true;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === 'start_number_registration') {
      if (typeof sendResponse === 'function') {
        try { sendResponse({ ok: true }); } catch (_) {}
      }
      return true;
    }
    return undefined;
  });

  const notifyReady = () => {
    try {
      if (/\/app\/numbers/.test(location.pathname)) {
        chrome.runtime.sendMessage({ type: 'page_ready_numbers' }, () => {});
      }
    } catch (_) {}
  };

  if (document.readyState === 'interactive' || document.readyState === 'complete') {
    notifyReady();
  } else {
    window.addEventListener('DOMContentLoaded', () => {
      notifyReady();
    }, { once: true });
  }
})();
