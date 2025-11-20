
# Auto-injected Playwright fingerprint spoof (drop-in, no code changes)
def _install():
    try:
        from playwright.sync_api import Browser  # type: ignore
    except Exception:
        return
    try:
        from bazos_playwright_patch.spoof import build_init_js, build_accept_language  # type: ignore
    except Exception:
        return

    if getattr(Browser.new_context, "_fp_spoof_patched", False):
        return

    _orig = Browser.new_context
    def _patched(self, *args, **kwargs):
        ctx = _orig(self, *args, **kwargs)
        try:
            js = build_init_js(kwargs or {})
            ctx.add_init_script(js)
        except Exception:
            pass
        try:
            al = build_accept_language(kwargs or {})
            ctx.set_extra_http_headers({"Accept-Language": al})
        except Exception:
            pass
        return ctx
    _patched._fp_spoof_patched = True  # type: ignore
    Browser.new_context = _patched  # type: ignore

_install()
