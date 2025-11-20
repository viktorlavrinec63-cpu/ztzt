
from playwright.sync_api import sync_playwright
from ua_manager import generate_profile
import time, json, os

def launch_context_from_profile(profile=None, headless=False):
    if profile is None:
        profile = generate_profile()
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(
        user_agent=profile["user_agent"],
        viewport=profile["viewport"],
        locale=profile["locale"],
        timezone_id=profile["timezone"],
        java_script_enabled=True,
        device_scale_factor=profile.get("deviceScaleFactor",1),
    )
    # load stealth/init scripts
    stealth_path = os.path.join(os.path.dirname(__file__), "stealth.js")
    if os.path.exists(stealth_path):
        with open(stealth_path, "r", encoding="utf-8") as f:
            js = f.read()
        context.add_init_script(js)
    else:
        # minimal patches
        context.add_init_script("""Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});""")
    page = context.new_page()
    page.set_default_timeout(60000)
    return p, browser, context, page

def close_all(p, browser, context):
    try:
        context.close()
    except: pass
    try:
        browser.close()
    except: pass
    try:
        p.stop()
    except: pass
