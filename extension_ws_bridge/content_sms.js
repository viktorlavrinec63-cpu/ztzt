/* content_sms.js — auto-open dialog on new SMS → copy code → delete thread */
(() => {
  const CFG_URL = chrome.runtime.getURL("selectors.json");
  const state = { cfg: null, lastByThread: new Map() };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const log = (...args) => console.log("[WS-BRIDGE][sms]", ...args);
  const PREVIEW_LAST_CODE_KEY = "ws_last_sent_code";
  const PREVIEW_LAST_CODE_TS_KEY = "ws_last_sent_code_at";

  async function loadCfg() {
    if (state.cfg) {
      return state.cfg;
    }
    const res = await fetch(CFG_URL, { cache: "no-cache" });
    state.cfg = await res.json();
    return state.cfg;
  }

  function qsAny(root, selectors) {
    for (const sel of selectors) {
      try {
        const el = root.querySelector(sel);
        if (el) {
          return el;
        }
      } catch (_) {
        /* ignore selector errors */
      }
    }
    return null;
  }

  function qsaAny(root, selectors) {
    for (const sel of selectors) {
      try {
        const list = root.querySelectorAll(sel);
        if (list && list.length) {
          return [...list];
        }
      } catch (_) {
        /* ignore selector errors */
      }
    }
    return [];
  }

  function waitFor(fn, { timeout = 15000, interval = 200 } = {}) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const timer = setInterval(() => {
        try {
          const value = fn();
          if (value) {
            clearInterval(timer);
            resolve(value);
          } else if (Date.now() - start > timeout) {
            clearInterval(timer);
            reject(new Error("waitFor timeout"));
          }
        } catch (err) {
          clearInterval(timer);
          reject(err);
        }
      }, interval);
    });
  }

  function extractCode(text, regex) {
    if (!text) {
      return null;
    }
    const match = text.match(regex);
    return match ? match[1] : null;
  }

  function findByText(root, strings) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    const cmp = strings.map((s) => String(s || "").trim().toLowerCase()).filter(Boolean);
    while (walker.nextNode()) {
      const el = walker.currentNode;
      const text = (el.innerText || el.textContent || "").trim().toLowerCase();
      if (!text) {
        continue;
      }
      if (cmp.some((needle) => text.includes(needle))) {
        return el;
      }
    }
    return null;
  }

  function clickSafe(el) {
    if (!el) {
      return false;
    }
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    return true;
  }

  const codeFromText = (text) => {
    if (!text) {
      return null;
    }
    const match = text.match(/(?:kod|code)\D*(\d{6,7})/i);
    return match ? match[1] : null;
  };

  const findBazosThreadItem = () => {
    const rows = Array.from(
      document.querySelectorAll('[class*="thread-element"]')
    );
    return rows.find((row) => /bazos/i.test(row.innerText || "")) || null;
  };

  const getLastMessageNode = (rowEl) => {
    if (!rowEl) {
      return null;
    }
    return (
      rowEl.querySelector('[class*="thread-last-message"]') ||
      rowEl.querySelector('[class*="content-row"][class*="number-info"]') ||
      rowEl
    );
  };

  async function waitCodeInPreview({ timeoutMs = 60000 } = {}) {
    let row = findBazosThreadItem();
    if (!row) {
      row = await new Promise((resolve, reject) => {
        const start = Date.now();
        const timer = setInterval(() => {
          const found = findBazosThreadItem();
          if (found) {
            clearInterval(timer);
            resolve(found);
          } else if (Date.now() - start > timeoutMs) {
            clearInterval(timer);
            reject(new Error("preview thread not found"));
          }
        }, 250);
      });
    }

    const msgNode = getLastMessageNode(row);
    if (!msgNode) {
      throw new Error("preview message node not found");
    }

    const start = Date.now();
    let lastValue = (msgNode.innerText || "").trim();
    let code = codeFromText(lastValue);
    if (code) {
      return code;
    }

    let currentValue = lastValue;
    const observer = new MutationObserver(() => {
      const text = (msgNode.innerText || "").trim();
      if (text !== currentValue) {
        currentValue = text;
      }
    });
    observer.observe(msgNode, { subtree: true, characterData: true, childList: true });

    try {
      while (Date.now() - start <= timeoutMs) {
        await sleep(250);
        code = codeFromText(currentValue);
        if (code) {
          return code;
        }
      }
      throw new Error("preview code wait timeout");
    } finally {
      observer.disconnect();
    }
  }

  async function readCodeFromPreview({ rid, newOnly, timeoutMs = 60000 }) {
    try {
      const code = await waitCodeInPreview({ timeoutMs });
      if (!code) {
        return null;
      }
      const prev = sessionStorage.getItem(PREVIEW_LAST_CODE_KEY) || "";
      if (newOnly && code === prev) {
        log("preview code matches last sent, skipping", code);
        return null;
      }
      sessionStorage.setItem(PREVIEW_LAST_CODE_KEY, code);
      sessionStorage.setItem(PREVIEW_LAST_CODE_TS_KEY, String(Date.now()));
      chrome.runtime.sendMessage({ type: "external_code", code, rid });
      log("code from preview", code, "rid=", rid);
      return code;
    } catch (err) {
      log("preview read failed", err?.message || err);
      return null;
    }
  }

  async function openThreadFromPopup(cfg) {
    const anchor = qsAny(document, cfg.popupItem);
    if (anchor) {
      clickSafe(anchor);
      return true;
    }
    const hint = findByText(document.body, ["new message", "новое сообщение", "sms"]);
    if (hint) {
      clickSafe(hint);
      return true;
    }
    return false;
  }

  function currentThreadId() {
    try {
      const match = location.pathname.match(/messages\/([^/]+)/);
      if (match) {
        return match[1];
      }
    } catch (_) {
      /* ignore */
    }
    return location.href;
  }

  async function clickUnreadOrFirstThread(cfg) {
    const container = await waitFor(() => qsAny(document, cfg.threadListContainer), { timeout: 20000 });
    const items = qsaAny(container, cfg.threadListItem);
    if (!items.length) {
      throw new Error("no-threads");
    }
    const unread = items.find((node) => {
      try {
        if (cfg.threadUnreadBadge.some((sel) => node.querySelector(sel))) {
          return true;
        }
      } catch (_) {
        /* ignore */
      }
      return false;
    });
    clickSafe(unread || items[0]);
    return true;
  }

  async function readLatestCode(cfg, newOnly) {
    const codeRegex = new RegExp(cfg.codeRegex, "i");
    const container = await waitFor(() => qsAny(document, cfg.messageContainer), { timeout: 20000 });
    await sleep(150);
    const row = qsAny(container, cfg.threadCodeLine) || container.lastElementChild;
    if (!row) {
      throw new Error("no-message-row");
    }
    const text = (row.innerText || row.textContent || "").trim();
    const code = extractCode(text, codeRegex);
    if (!code) {
      throw new Error("code-not-found");
    }
    const threadId = currentThreadId();
    const prev = state.lastByThread.get(threadId);
    if (newOnly && prev && prev.code === code) {
      throw new Error("code-not-new");
    }
    state.lastByThread.set(threadId, { code, ts: Date.now() });
    return { code, threadId };
  }

  function realClick(node) {
    if (!node) {
      return;
    }
    const rect = node.getBoundingClientRect();
    const opts = {
      bubbles: true,
      cancelable: true,
      clientX: rect.left + Math.min(4, Math.max(0, rect.width / 2)),
      clientY: rect.top + Math.min(4, Math.max(0, rect.height / 2)),
      view: window,
    };
    node.dispatchEvent(new MouseEvent("mousedown", opts));
    node.dispatchEvent(new MouseEvent("mouseup", opts));
    node.dispatchEvent(new MouseEvent("click", opts));
  }

  async function deleteThreadInPlace(cfg) {
    const kebab =
      qsAny(document, cfg.kebabInThread) || findByText(document.body, ["more", "ещё", "еще", "more…"]);
    if (!kebab) {
      log("deleteThread: kebab not found");
      return false;
    }
    realClick(kebab);
    await sleep(200);

    const deleteBtn =
      findByText(document.body, ["delete thread", "удалить диалог"]) || qsAny(document, cfg.menuDelete);
    if (!deleteBtn) {
      log("deleteThread: menu delete not found");
      return false;
    }
    realClick(deleteBtn);
    await sleep(200);

    const confirm =
      findByText(document.body, ["delete", "удалить", "confirm", "yes", "ok"]) || qsAny(document, cfg.confirmDelete);
    if (confirm) {
      realClick(confirm);
    }
    await sleep(120);
    return true;
  }

  function armNewSmsObserver(cfg) {
    try {
      const root = qsAny(document, cfg.threadListContainer) || document.body;
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes || []) {
            if (!(node instanceof HTMLElement)) {
              continue;
            }
            if (cfg.threadListItem.some((sel) => {
              try {
                return node.matches(sel);
              } catch (_) {
                return false;
              }
            })) {
              log("new thread node → click");
              clickSafe(node);
              continue;
            }
            const nested = qsAny(node, cfg.threadListItem);
            if (nested) {
              log("new thread descendant → click");
              clickSafe(nested);
            }
          }
        }
      });
      observer.observe(root, { childList: true, subtree: true });
      return observer;
    } catch (err) {
      log("observer error", err);
      return null;
    }
  }

  chrome.runtime.onMessage.addListener(async (msg, _sender, sendResponse) => {
    if (!msg || msg.type !== "start_sms_watch") {
      return;
    }
    const rid = msg.rid || null;
    const newOnly = Boolean(msg.new_only);
    const timeoutMs = typeof msg.timeout_ms === "number" ? msg.timeout_ms : 60000;

    try {
      const previewCode = await readCodeFromPreview({ rid, newOnly, timeoutMs });
      if (previewCode) {
        sendResponse?.({ ok: true, code: previewCode, via: "preview" });
        return true;
      }
    } catch (previewErr) {
      log("preview branch error", previewErr?.message || previewErr);
    }

    try {
      const cfg = await loadCfg();
      const observer = armNewSmsObserver(cfg);
      const opened = await openThreadFromPopup(cfg);
      if (!opened) {
        await clickUnreadOrFirstThread(cfg);
      }
      const { code, threadId } = await readLatestCode(cfg, newOnly);
      chrome.runtime.sendMessage({ type: "external_code", rid, code, threadId });
      const deleted = await deleteThreadInPlace(cfg);
      chrome.runtime.sendMessage({ type: "thread_deleted", rid, ok: deleted, threadId });
      if (observer) {
        observer.disconnect();
      }
      sendResponse?.({ ok: true, code, threadId, via: "dialog" });
    } catch (err) {
      log("start_sms_watch error", err?.message || err);
      chrome.runtime.sendMessage({ type: "external_error", rid, error: String(err?.message || err) });
      sendResponse?.({ ok: false, error: String(err?.message || err) });
    }
    return true;
  });

  window.__ws_read_code_from_list__ = async function(opts = {}) {
    const rid = opts?.rid ?? null;
    const newOnly = opts?.newOnly ?? true;
    const timeoutMs = typeof opts?.timeoutMs === "number" ? opts.timeoutMs : 60000;
    const code = await readCodeFromPreview({ rid, newOnly, timeoutMs });
    return { ok: Boolean(code), code, rid };
  };
})();
