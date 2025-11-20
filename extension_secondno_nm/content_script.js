
// content_script.js — supports setValue and notifies background when page is ready
(function () {
  function nativeSet(el, val) {
    const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    if (d && d.set) d.set.call(el, val); else el.value = val;
  }
  function findInput(selector) {
    const list = [
      selector,
      "input[placeholder='Email']",
      "input[type='email']",
      "input[name='email']",
      ".input-field input",
      "input[type='text']",
    ].filter(Boolean);
  for (const sel of list) { try { const el = document.querySelector(sel); if (el) return el; } catch(e) {} }
    return null;
  }
  async function setValueWithRetry(selector, value, timeoutMs=5000) {
    const t0 = Date.now();
    let el = null;
    while (Date.now() - t0 < timeoutMs) {
      el = findInput(selector);
      if (el) break;
      await new Promise(r => setTimeout(r, 200));
    }
    if (!el) return { event:"onError", ok:false, error:"element_not_found: "+selector };
    el.focus();
    nativeSet(el, String(value ?? ""));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { event:"onSetValue", ok:true, selector, value };
  }

  chrome.runtime.onMessage.addListener((cmd, _s, send) => {
    if (!cmd || !cmd.action) return;
    if (cmd.action === "setValue") {
      const selector = cmd.params?.selector || "input[placeholder='Email']";
      const value = cmd.params?.value ?? "";
      setValueWithRetry(selector, value).then(send);
      return true;
    }
  });

  // notify background that this page is ready
  chrome.runtime.sendMessage({ event: "pageReady" });
})();
