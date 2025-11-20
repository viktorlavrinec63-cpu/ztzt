
Playwright integration patch for BazosAutoReg project
====================================================

This archive contains a ready-to-use Playwright integration and a large, fresh
set of User-Agent strings and randomized profiles. It does NOT overwrite your original
project files. Instead, it includes a folder `bazos_playwright_patch/` you can
copy into your project and integrate.

Files added (inside bazos_playwright_patch/):
- user_agents.txt           -- ~100+ modern User-Agent strings
- ua_manager.py             -- helpers to pick UA/viewports/locales and generate profiles
- browser_setup.py          -- Playwright helper to launch a context with stealth scripts
- stealth.js                -- JS stealth patches (navigator, canvas, webgl)
- profiles.json             -- 200 pre-generated profiles (UA, viewport, locale, timezone)
- README_INTEGRATE.txt      -- this file (instructions)
- QUICK_PATCH.txt           -- quick one-file patch suggestions for bazos_bot.py and main.py

Quick integration steps (recommended):
1) Install dependencies on the machine where bot runs:
   - Python 3.9+
   - pip install -U playwright
   - python -m playwright install chromium
   - pip install -U playwright-stealth (optional) or other helpers

   Example commands:
     pip install -U playwright
     python -m playwright install --with-deps

2) Copy `bazos_playwright_patch/` into your project root (same level as bazos_bot.py).
   For example, if your project is `BazosAutoReg_Windo2232ws/`, copy the folder inside it.

3) Replace or modify calls that create browser/sessions in your project to use the new helper.
   Easiest approach: in your `bazos_bot.py` or `main.py` find where it launches browser/session
   and replace with something like:

   from bazos_playwright_patch.browser_setup import launch_context_from_profile, close_all
   from bazos_playwright_patch.ua_manager import generate_profile

   profile = generate_profile("bazos_playwright_patch/user_agents.txt")
   p, browser, context, page = launch_context_from_profile(profile, headless=False)

   # ... perform registration using `page` (Playwright page API) ...
   # After done:
   close_all(p, browser, context)

   See QUICK_PATCH.txt for an example patch to copy/paste.

4) For production, run headless=True and rotate profiles between runs. Save context.storageState() or cookies
   if you want to persist session state. Example:
     context.storage_state(path="state.json")

Security & Notes:
- The stealth.js provided is a basic set of patches. For stronger evasion, integrate
  additional patches (fonts, audio, timing, TLS fingerprint) and keep Playwright updated.
- Always test manually the first few runs to ensure registration flow on bazos.cz works.
- Rotating profiles + IP addresses is important to avoid linkability and mass-blocking.
