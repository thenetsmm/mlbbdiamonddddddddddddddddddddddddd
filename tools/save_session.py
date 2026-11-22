"""Debug Chrome (port 9222) ထဲမှာ login ဝင်ပြီးမှ run ပါ -> moogold_session.json ထုတ်ပေးတယ်"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]
    ctx.storage_state(path="moogold_session.json")
    print("session သိမ်းပြီးပြီ: moogold_session.json")
    browser.close()
