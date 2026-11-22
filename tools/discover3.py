"""
MooGold dry-run discovery (ဘာမှ မဝယ်ပါ)
 အပိုင်း A: product page က User ID / Server ID field နာမည်တွေ ဖတ်မယ် (ဖတ်ရုံသာ)
 အပိုင်း B: (y ဖြေမှ) cart ထဲ 5 Diamonds ကို အတု ID နဲ့ ထည့် -> checkout က payment method ကြည့် -> cart ကို ပြန်ရှင်းမယ်
"""
import html as H
import json
import re
import sys

import requests
from bs4 import BeautifulSoup

BASE = "https://moogold.com"
PRODUCT_URL = f"{BASE}/product/mobile-legends/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")

state = json.load(open("moogold_session.json", encoding="utf-8"))
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
for c in state["cookies"]:
    if "moogold.com" in (c.get("domain") or ""):
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))


def mask(t):
    return re.sub(r"\d", "#", t)


def notices(soup):
    out = []
    for el in soup.select(".woocommerce-error, .woocommerce-message, .woocommerce-info, "
                          ".wc-block-components-notice-banner"):
        txt = el.get_text(" ", strip=True)
        if txt:
            out.append(mask(txt)[:200])
    return out


def cart_info():
    r = s.get(f"{BASE}/shopping-cart/", timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("tr.cart_item, .cart_item, .woocommerce-cart-form__cart-item")
    removes = [a["href"] for a in soup.select("a.remove, a[href*='remove_item']") if a.get("href")]
    return r, soup, rows, removes


# ===================== အပိုင်း A =====================
print("===== A) Product page field နာမည်များ =====")
r = s.get(PRODUCT_URL, timeout=20)
print("status:", r.status_code)
page = H.unescape(r.text)
soup = BeautifulSoup(r.text, "html.parser")

found = []
for eid, label in re.findall(r'"elementId":"(wcpa-[\w-]+)","label":"([^"]*)"', page):
    if (eid, label) not in found:
        found.append((eid, label))
for eid, label in found:
    print(f"  field: name/id = {eid!r} | label = {label!r}")
if not found:
    print("  WCPA field မတွေ့ဘူး (page ပုံစံ ပြောင်းထားနိုင်)")

print("  wcpa/sbw ပါတဲ့ HTML input တွေ:")
for el in soup.find_all(["input", "button"]):
    nm = el.get("name") or ""
    if "wcpa" in nm.lower() or "sbw" in nm.lower():
        print("   -", el.name, nm, el.get("type"))

form = soup.select_one("form.variations_form")
vid = None
if form:
    for v in json.loads(form["data-product_variations"]):
        if v["attributes"].get("attribute_amount") == "5 Diamonds":
            vid = v["variation_id"]
print("  5 Diamonds variation_id:", vid)

user_f = next((e for e, l in found if "user" in l.lower()), None)
server_f = next((e for e, l in found if "server" in l.lower()), None)
if not (vid and user_f and server_f):
    print("\nလိုအပ်တဲ့ field မပြည့်စုံလို့ B ကို မလုပ်ပါဘူး။ ဒီ output ကို ပြောပြပါ။")
    sys.exit()

# ===================== အပိုင်း B =====================
ans = input("\nB) Cart ထဲ '5 Diamonds' (အတု ID) ထည့်ပြီး checkout payment method ကြည့်မလား? ဘာမှ မဝယ်ပါ။ [y/N]: ")
if ans.strip().lower() != "y":
    sys.exit("B ကို မလုပ်ဘဲ ရပ်လိုက်ပါတယ်။")

_, _, rows, removes = cart_info()
if rows:
    print(f"\nCart ထဲမှာ item {len(rows)} ခု ရှိနေပါတယ်။ ဆိုက်မှာ ကိုယ်တိုင် ဖယ်ပြီးမှ ပြန်ပြေးပါ။")
    sys.exit()

print("\n--- cart ထဲ ထည့်မယ် ---")
data = {
    "add-to-cart": "15145",
    "product_id": "15145",
    "variation_id": str(vid),
    "attribute_amount": "5 Diamonds",
    "quantity": "1",
    user_f: "12345678",
    server_f: "1234",
}
resp = s.post(PRODUCT_URL, data=data, headers={"Referer": PRODUCT_URL}, timeout=30)
print("add-to-cart status:", resp.status_code, "| final url:", resp.url)
for n in notices(BeautifulSoup(resp.text, "html.parser")):
    print("  notice:", n)

_, csoup, rows, removes = cart_info()
print("cart item အရေအတွက်:", len(rows))
for row in rows:
    print("  ", mask(row.get_text(" ", strip=True))[:160])

if rows:
    print("\n--- checkout ---")
    ck = s.get(f"{BASE}/checkout/", timeout=20)
    print("status:", ck.status_code, "| final url:", ck.url)
    ksoup = BeautifulSoup(ck.text, "html.parser")
    for inp in ksoup.select("input[name='payment_method']"):
        lab = ksoup.select_one(f"label[for='{inp.get('id')}']")
        print("  payment method:", repr(inp.get("value")), "|",
              lab.get_text(" ", strip=True)[:60] if lab else "?")
    for line in ksoup.get_text("\n", strip=True).splitlines():
        if "balance" in line.lower() and len(line) < 80:
            print("  wallet line:", line)
    names = sorted({el.get("name") for el in ksoup.select("form.checkout input, form.checkout select, form.checkout textarea")
                    if el.get("name") and "token" not in el.get("name") and "intent" not in el.get("name")})
    print("  checkout form field နာမည်များ:", names)
    print("  checkout nonce ပါလား:", "woocommerce-process-checkout-nonce" in ck.text)
    for key in ("wc_ajax_url", "checkout_url"):
        m = re.search(rf'"{key}":"([^"]+)"', H.unescape(ck.text).replace("\\/", "/"))
        print(f"  {key}:", m.group(1) if m else None)

    print("\n--- cart ကို ပြန်ရှင်းမယ် ---")
    _, _, rows, removes = cart_info()
    for href in removes:
        s.get(href if href.startswith("http") else BASE + href, timeout=20)
    _, _, rows, _ = cart_info()
    print("ရှင်းပြီးနောက် cart item အရေအတွက်:", len(rows))
    if rows:
        print("Cart မရှင်းနိုင်ဘူး၊ ဆိုက်မှာ ကိုယ်တိုင် ဖယ်ပါ။")
print("\nပြီးပါပြီ။ ဘာမှ မဝယ်ထားပါဘူး။")
