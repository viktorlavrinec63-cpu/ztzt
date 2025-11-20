
from .browser_setup import launch_context_from_profile, close_all
import json, time, os

def run_diagnostics(profile, out_dir="logs", headless=True):
    os.makedirs(out_dir, exist_ok=True)
    p, browser, context, page = launch_context_from_profile(profile, headless=headless)
    try:
        results = {}
        page.goto("https://amiunique.org/fp", wait_until="networkidle", timeout=60000)
        time.sleep(2)
        # try to extract window.__profile_meta if present
        try:
            meta = page.evaluate("() => window.__profile_meta || {}")
            results['meta'] = meta
        except Exception as e:
            results['meta_eval_error'] = str(e)
        # get navigator object
        try:
            nav = page.evaluate("""() => {
                const n = navigator;
                return {userAgent: n.userAgent, platform: n.platform, languages: n.languages, hardwareConcurrency: n.hardwareConcurrency, deviceMemory: n.deviceMemory, maxTouchPoints: n.maxTouchPoints};
            }""")
            results['navigator'] = nav
        except Exception as e:
            results['navigator_error'] = str(e)
        # try canvas fingerprint data (if available via page)
        try:
            canvas = page.evaluate("""() => {
                try {
                    const cvs = document.createElement('canvas');
                    cvs.width = 200; cvs.height = 60;
                    const ctx = cvs.getContext('2d');
                    ctx.textBaseline = "alphabetic";
                    ctx.fillStyle = "#f60";
                    ctx.fillRect(0,0,200,60);
                    ctx.fillStyle = "#069";
                    ctx.font = "11px 'Arial'";
                    ctx.fillText("Cwm fjordbank glyphs vext quiz, 😃", 2, 15);
                    return cvs.toDataURL();
                } catch (e) { return null; }
            }""")
            results['canvas'] = bool(canvas)
        except Exception as e:
            results['canvas_error'] = str(e)
        # save screenshot
        try:
            ss_path = os.path.join(out_dir, "diag_amiunique.png")
            page.screenshot(path=ss_path, full_page=True)
            results['screenshot'] = ss_path
        except Exception as e:
            results['screenshot_error'] = str(e)
        # write results
        with open(os.path.join(out_dir, "diag_amiunique.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        return results
    finally:
        close_all(p, browser, context)
