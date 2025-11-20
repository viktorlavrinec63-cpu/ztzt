
import random, json, os
def load_user_agents(path="user_agents.txt"):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    return lines

def pick_ua(path="user_agents.txt"):
    uas = load_user_agents(path)
    return random.choice(uas)

def pick_viewport_for_ua(ua):
    ua_l = ua.lower()
    if "mobile" in ua_l or "iphone" in ua_l or "android" in ua_l:
        widths = [360,375,390,412,428]
        heights = [800,780,844,852,915]
        return {"width": random.choice(widths), "height": random.choice(heights), "deviceScaleFactor": random.choice([2,3])}
    else:
        widths = [1366,1440,1536,1600,1920,2560]
        heights = [768,800,900,960,1080,1440]
        return {"width": random.choice(widths), "height": random.choice(heights), "deviceScaleFactor": 1}

def pick_locale_and_timezone():
    locales = [("cs-CZ","Europe/Prague"),("pl-PL","Europe/Warsaw"),("en-US","America/New_York"),("en-GB","Europe/London"),("de-DE","Europe/Berlin"),("sk-SK","Europe/Bratislava")]
    return random.choice(locales)

def generate_profile(ua_path="user_agents.txt"):
    ua = pick_ua(ua_path)
    vp = pick_viewport_for_ua(ua)
    locale, tz = pick_locale_and_timezone()
    profile = {
        "user_agent": ua,
        "viewport": vp,
        "locale": locale,
        "timezone": tz,
        "deviceMemory": random.choice([4,8,16]),
        "hardwareConcurrency": random.choice([2,4,6,8]),
        "plugins_count": random.choice([3,4,5,6]),
        "fonts_sample": random.sample(["Arial","Times New Roman","Roboto","Segoe UI","Helvetica","Courier New","Tahoma","Verdana","Georgia"], 4)
    }
    return profile
