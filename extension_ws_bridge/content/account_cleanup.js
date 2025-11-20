// account_cleanup.js — запускается только по явной команде background → {type:'RUN_DELETE_ACCOUNT'}
let __cleanupRunning = false;
let __cleanupCompleted = false;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || (msg.type !== "run_account_cleanup" && msg.type !== "RUN_DELETE_ACCOUNT")) {
    return;
  }
  if (__cleanupRunning) {
    try { sendResponse?.({ ok: false, error: "already_running" }); } catch (_) {}
    return;
  }
  __cleanupRunning = true;
  Promise.resolve(runAccountCleanup())
    .catch((err) => {
      console.error("[CLEANUP] failed", err);
      try {
        if (!__cleanupCompleted) {
          __cleanupCompleted = true;
          chrome.runtime.sendMessage({ type: "account_cleanup_done", ok: false, error: String(err) });
        }
      } catch (_) {}
    })
    .finally(() => {
      __cleanupRunning = false;
    });
  try { sendResponse?.({ ok: true }); } catch (_) {}
});

async function runAccountCleanup() {
  const host = location.hostname;
  const path = location.pathname || "";

  // Не выполняем в окне авторизации Google
  if (host.endsWith("accounts.google.com")) {
    if (!__cleanupCompleted) {
      __cleanupCompleted = true;
      chrome.runtime.sendMessage({ type: "account_cleanup_done", ok: false, error: "oauth_context" });
    }
    return;
  }

  // Ожидаем рабочее приложение /app/*
  if (!(host.endsWith("2nd-no.com") && path.startsWith("/app/"))) {
    if (!__cleanupCompleted) {
      __cleanupCompleted = true;
      chrome.runtime.sendMessage({ type: "account_cleanup_done", ok: false, error: "not_on_app_page" });
    }
    return;
  }

  await deleteAccountUiFlow();

  try {
    window.addEventListener(
      "beforeunload",
      () => {
        if (__cleanupCompleted) return;
        __cleanupCompleted = true;
        try { chrome.runtime.sendMessage({ type: "account_cleanup_done", ok: true }); } catch (_) {}
      },
      { once: true }
    );
  } catch (_) {}

  let ok = false;
  for (let i = 0; i < 40; i++) {
    await sleep(250);
    const bodyText = (document.body && document.body.textContent) || "";
    if (/authorization required/i.test(bodyText)) {
      ok = true;
      break;
    }
    if (location.pathname.startsWith("/auth/")) {
      ok = true;
      break;
    }
  }
  if (!__cleanupCompleted) {
    __cleanupCompleted = true;
    chrome.runtime.sendMessage({ type: "account_cleanup_done", ok });
  }
}

// Удаление аккаунта c надёжной паузой перед финальным кликом
async function deleteAccountUiFlow() {
  // 1) Открыть Settings (если не там)
  await clickOnce([
    'a[href="/app/settings"]',
    '.sidebar a[href="/app/settings"]',
    '.sidebar a[role="link"][href*="settings"]',
    () => findClickableByText(["Settings", "Настройки"])
  ], 8000, "Settings button not found");
  await sleep(300);

  // 2) Нажать красную кнопку "Delete account"
  await clickOnce(
    [
      '.delete-account button',
      'button.delete-account',
      '.content-row .btn.delete-account',
      () => findClickableByText(["Delete account", "Удалить аккаунт", "Remove account"])
    ],
    8000,
    "Delete account button not found"
  );

  // 3) Дождаться модалки
  let modal = await waitFor(() => {
    const modalCandidate = document.querySelector('.modal-base .modal, .modal-base .fixed, .modal-base [role="dialog"], [role="dialog"]');
    return modalCandidate && isVisible(modalCandidate) ? modalCandidate : null;
  }, 8000);
  if (!modal) throw new Error("Delete modal not found");

  // 4) Найти именно кнопку Delete внутри модалки
  let confirmButton = await waitFor(() => findModalDeleteButton(modal), 8000);
  if (!confirmButton) throw new Error("Modal Delete button not found");

  // 5) Пауза 3 секунды, чтобы закончились анимации/разрешилась кнопка
  await sleep(3000);

  // 6) Дождаться, что кнопка не disabled и кликабельна
  if (!modal.isConnected) {
    const refreshedModal = await waitFor(() => {
      const candidate = document.querySelector('.modal-base .modal, .modal-base .fixed, .modal-base [role="dialog"], [role="dialog"]');
      return candidate && isVisible(candidate) ? candidate : null;
    }, 4000);
    if (refreshedModal) {
      modal = refreshedModal;
      confirmButton = await waitFor(() => findModalDeleteButton(modal), 5000) || confirmButton;
    }
  }
  if (!confirmButton.isConnected) {
    const refreshed = findModalDeleteButton(modal);
    if (refreshed) {
      confirmButton = refreshed;
    }
  }
  await waitForEnabled(confirmButton, 5000);

  // 7) Прокрутить в видимую область и кликнуть по самой кнопке
  try { confirmButton.scrollIntoView({ block: "center", inline: "center" }); } catch (_) {}
  await sleep(100);
  safeClick(confirmButton);
  await sleep(150);
}

function findClickableByText(labels) {
  const lowered = labels.map((l) => (l || "").toLowerCase());
  const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], [role="link"], .btn'));
  return candidates.find((el) => {
    if (!isVisible(el)) return false;
    const text = (el.innerText || el.textContent || "").trim().toLowerCase();
    if (!text) return false;
    return lowered.some((label) => text.includes(label));
  }) || null;
}

function findModalDeleteButton(modal) {
  if (!modal) return null;
  const directSelectors = [
    'button.button.delete',
    'button.delete',
    'button[data-variant="delete"]',
    '.btn.delete',
    'button[data-color="red"]'
  ];
  for (const sel of directSelectors) {
    const el = modal.querySelector(sel);
    if (el && isVisible(el)) {
      return el;
    }
  }
  const textMatches = ["delete", "confirm", "удалить", "да, удалить"];
  const candidates = Array.from(modal.querySelectorAll('button, [role="button"], a'));
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const text = (el.innerText || el.textContent || "").trim().toLowerCase();
    if (!text) continue;
    if (textMatches.some((label) => text.includes(label))) {
      return el;
    }
  }
  return null;
}

function isVisible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0") {
    return false;
  }
  const rect = el.getBoundingClientRect();
  if (!rect || rect.width === 0 || rect.height === 0) {
    return false;
  }
  if (!el.offsetParent && style.position !== "fixed") {
    return false;
  }
  return true;
}

async function clickOnce(selectorOrResolver, timeoutMs = 8000, errorMessage = "Selector not found") {
  const el = await waitFor(selectorOrResolver, timeoutMs, { visible: true });
  if (!el) {
    throw new Error(errorMessage);
  }
  try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (_) {}
  await sleep(50);
  safeClick(el);
  await sleep(150);
  return el;
}

async function waitForEnabled(el, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!el || !el.isConnected) {
      throw new Error("target detached before enabling");
    }
    const disabled = el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true";
    const style = window.getComputedStyle(el);
    const blocked =
      disabled ||
      style.pointerEvents === "none" ||
      style.visibility === "hidden" ||
      style.display === "none" ||
      Number(style.opacity || "1") === 0;
    if (!blocked) {
      return;
    }
    await sleep(100);
  }
  console.warn("[EXT] Delete button not clearly enabled, attempting click anyway");
}

function safeClick(el) {
  if (!el) return;
  try {
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  } catch (e) {
    try {
      el.click();
    } catch (_) {}
  }
}

function resolveSelector(selectorOrResolver) {
  if (typeof selectorOrResolver === "function") {
    try {
      return selectorOrResolver() || null;
    } catch (_) {
      return null;
    }
  }
  if (Array.isArray(selectorOrResolver)) {
    for (const candidate of selectorOrResolver) {
      const found = resolveSelector(candidate);
      if (found) {
        return found;
      }
    }
    return null;
  }
  if (typeof selectorOrResolver === "string" && selectorOrResolver) {
    try {
      const el = document.querySelector(selectorOrResolver);
      return el || null;
    } catch (_) {
      return null;
    }
  }
  return null;
}

async function waitFor(selectorOrResolver, timeoutMs = 5000, options = {}) {
  const { visible = false } = options || {};
  const start = Date.now();
  return new Promise((resolve) => {
    const timer = setInterval(() => {
      const el = resolveSelector(selectorOrResolver);
      if (el && (!visible || isVisible(el))) {
        clearInterval(timer);
        resolve(el);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        clearInterval(timer);
        resolve(null);
      }
    }, 100);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
