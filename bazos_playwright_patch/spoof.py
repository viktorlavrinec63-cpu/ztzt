
# bazos_playwright_patch/spoof.py
from __future__ import annotations
import json

def _derive_platform_from_ua(ua: str) -> str:
    ua = ua or ""
    if "Windows" in ua: return "Win32"
    if "Linux" in ua: return "Linux x86_64"
    if "Mac" in ua or "Macintosh" in ua: return "MacIntel"
    if "iPhone" in ua: return "iPhone"
    if "iPad" in ua: return "iPad"
    return "Win32"

def build_init_js(kwargs: dict) -> str:
    ua = kwargs.get("user_agent") or ""
    platform = _derive_platform_from_ua(ua)
    locale = kwargs.get("locale") or "cs-CZ"
    viewport = kwargs.get("viewport") or {"width":1366,"height":768}
    screen = {"width": viewport.get("width",1366), "height": viewport.get("height",768),
              "availWidth": viewport.get("width",1366), "availHeight": viewport.get("height",768)}
    max_touch = 0
    devmem = 8
    hwc = 4
    # pick a realistic GPU based on UA
    if "Android" in ua:
        webgl_vendor, webgl_renderer = "Qualcomm", "Adreno (TM) 640"
    elif "iPhone" in ua or "iPad" in ua or "Mac OS X" in ua or "Macintosh" in ua:
        webgl_vendor, webgl_renderer = "Apple", "Apple M1"
    elif "Linux" in ua:
        webgl_vendor, webgl_renderer = "X.Org", "AMD Radeon RX 5700 (RADV NAVI10)"
    elif "Windows" in ua:
        webgl_vendor, webgl_renderer = "Google Inc. (Intel)", "ANGLE (Intel, Intel UHD Graphics 630)"
    else:
        webgl_vendor, webgl_renderer = "Google Inc. (Intel)", "ANGLE (Intel, Intel UHD Graphics 630)"
    init_js = f"""
    (()=>{{
      try{{
        const spoofVendor = "{webgl_vendor}";
        const spoofRenderer = "{webgl_renderer}";
        Object.defineProperty(navigator,'platform',{{get:()=>"{platform}"}});
        Object.defineProperty(navigator,'languages',{{get:()=>["{locale}","{locale.split('-')[0]}","en-US"]}});
        Object.defineProperty(navigator,'language',{{get:()=>"{locale.split('-')[0]}"}});
        Object.defineProperty(navigator,'deviceMemory',{{get:()=>{devmem}}});
        Object.defineProperty(navigator,'hardwareConcurrency',{{get:()=>{hwc}}});
        Object.defineProperty(navigator,'maxTouchPoints',{{get:()=>{max_touch}}});
        try {{
          Object.defineProperty(window,'screen',{{value:{{width:{screen['width']},height:{screen['height']},availWidth:{screen['availWidth']},availHeight:{screen['availHeight']},colorDepth:24}}}});
        }} catch(e){{}}
        function patch(proto){{
          if(!proto)return;
          const gp = proto.getParameter;
          proto.getParameter = function(p){{
            if(p===37445) return spoofVendor;
            if(p===37446) return spoofRenderer;
            return gp.apply(this, arguments);
          }};
          const ge = proto.getExtension;
          proto.getExtension = function(name){{
            if(name==='WEBGL_debug_renderer_info') return {{UNMASKED_VENDOR_WEBGL:37445,UNMASKED_RENDERER_WEBGL:37446}};
            return ge.apply(this, arguments);
          }};
          const gs = proto.getSupportedExtensions;
          proto.getSupportedExtensions = function(){{
            const list = gs ? gs.apply(this, arguments)||[] : [];
            if(list.indexOf('WEBGL_debug_renderer_info')===-1) list.push('WEBGL_debug_renderer_info');
            return list;
          }};
        }}
        try{{patch(WebGLRenderingContext.prototype);}}catch(e){{}}
        try{{patch(WebGL2RenderingContext.prototype);}}catch(e){{}}
      }}catch(e){{console.error('spoof_init_error',e);}}
    }})();
    """
    return init_js

def build_accept_language(kwargs: dict) -> str:
    locale = kwargs.get("locale") or "cs-CZ"
    base = locale.split("-")[0]
    return f"{locale},{base};q=0.9,en;q=0.8"
