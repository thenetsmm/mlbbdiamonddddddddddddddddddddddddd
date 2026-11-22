"""MooGold MLBB ဝယ်ယူခြင်း (MooGold Wallet နဲ့ပဲ ပေးချေမယ်)

လုံခြုံရေးစည်းမျဉ်းများ
- cart ထဲ item ရှိနေရင် မဝယ်ဘူး
- cart ထဲက package / User ID / Server ID မကိုက်ရင် မဝယ်ဘူး
- checkout မှာ Wallet ရွေးစရာ မပေါ်ရင် မဝယ်ဘူး (တခြား ပေးချေမှုနည်း မရွေးဘူး)
- checkout ဈေး ≠ စာရင်းဈေး ဒါမှမဟုတ် ကန့်သတ်ပမာဏ ကျော်ရင် မဝယ်ဘူး
- wallet လက်ကျန် မလောက်ရင် မဝယ်ဘူး
- အော်ဒါ တစ်ခါပဲ ပို့တယ်၊ ထပ်မကြိုးစားဘူး
"""
import html as H
import json
import os
import re
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

BASE = "https://moogold.com"
PRODUCT_URL = f"{BASE}/product/mobile-legends/"
CART_URL = f"{BASE}/shopping-cart/"
CHECKOUT_URL = f"{BASE}/checkout/"
WALLET_URL = f"{BASE}/account/wallet/"
ORDERS_URL = f"{BASE}/account/orders/"
ORDER_AJAX_URL = f"{BASE}/?wc-ajax=checkout"
CART_ROW_SEL = "tr.cart_item, .cart_item, .woocommerce-cart-form__cart-item"
REMOVE_SEL = "a.remove, a[href*='remove_item']"


# ဘရောက်ဇာ form ကနေ တိုက်ရိုက်ဖမ်းထားတဲ့ တကယ့် input နာမည်များ (Render env နဲ့ ပြောင်းလို့ရ)
USER_FIELD = os.environ.get("MG_USER_FIELD", "text-5f6f144f8ffee")
SERVER_FIELD = os.environ.get("MG_SERVER_FIELD", "text-1601115253775")


def log(*a):
    print("[moogold]", *a, flush=True)


class BuyError(Exception):
    """User ကို ပြောပြရမယ့် စာနဲ့ ရပ်တဲ့ error (ဘာမှ မဝယ်ရသေးဘူး)"""


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def _norm(text):
    return " ".join((text or "").split())


def _dec(text):
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def force_usd(s):
    """MooGold က currency ကို ဆိုင်ရာနိုင်ငံအလိုက် ပြောင်းတတ်လို့ (aelia) USD ကို အတင်းသတ်မှတ်မယ်"""
    for c in list(s.cookies):
        if c.name == "aelia_cs_selected_currency":
            s.cookies.clear(c.domain, c.path, c.name)
    s.cookies.set("aelia_cs_selected_currency", "USD", domain="moogold.com", path="/")


# ---------- product page ----------
def read_fields(s):
    """Product id နဲ့ User ID / Server ID field နာမည်တွေကို page ကနေ ဖတ်မယ်"""
    r = s.get(PRODUCT_URL, timeout=20)
    if r.status_code != 200:
        raise BuyError(f"Product page ဖတ်မရဘူး (HTTP {r.status_code})")
    page = H.unescape(r.text)
    form = _soup(r.text).select_one("form.variations_form")
    if not form:
        raise BuyError("Product page မှာ variations form မတွေ့ဘူး (challenge ပေါ်နေတာ ဖြစ်နိုင်)")
    product_id = form.get("data-product_id")
    found = []
    for eid, label in re.findall(r'"elementId":"(wcpa-[\w-]+)","label":"([^"]*)"', page):
        if (eid, label) not in found:
            found.append((eid, label))
    auto_user = next((e for e, l in found if "user" in l.lower()), None)
    auto_server = next((e for e, l in found if "server" in l.lower()), None)
    log("page fields:", found, "| auto:", auto_user, auto_server, "| using:", USER_FIELD, SERVER_FIELD)
    user_f, server_f = USER_FIELD, SERVER_FIELD
    if not product_id:
        raise BuyError("Product id ရှာမတွေ့ဘူး (ဆိုက်ပုံစံ ပြောင်းသွားနိုင်)")
    return product_id, user_f, server_f


# ---------- cart ----------
def cart_state(s):
    r = s.get(CART_URL, timeout=20)
    soup = _soup(r.text)
    removes = [a["href"] for a in soup.select(REMOVE_SEL) if a.get("href")]
    rows = soup.select(CART_ROW_SEL)
    n = len(set(removes)) if removes else len(rows)
    return soup, n, removes


def clear_cart(s):
    """Cart ကို ရှင်းမယ်။ ကျန်တဲ့ item အရေအတွက် ပြန်ပေးတယ်"""
    for _ in range(5):
        _, n, removes = cart_state(s)
        if n == 0:
            return 0
        for href in set(removes):
            s.get(href if href.startswith("http") else BASE + href, timeout=20)
    return cart_state(s)[1]


def _form_hidden(s):
    """Product form ထဲက hidden/ပုံမှန် input အားလုံး (nonce, wcpa key စတာတွေ ပါမယ်)"""
    r = s.get(PRODUCT_URL, timeout=20)
    form = _soup(r.text).select_one("form.variations_form, form.cart")
    out = {}
    if not form:
        return out
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        typ = (el.get("type") or el.name).lower()
        if not name or typ in ("submit", "button", "image", "file", "radio", "checkbox"):
            continue
        out[name] = el.get("value", "") if el.name != "textarea" else el.get_text()
    return out


def add_to_cart(s, product_id, variation_id, amount_name, user_f, server_f, user_id, server_id):
    data = _form_hidden(s)
    data.update({
        "add-to-cart": product_id,
        "product_id": product_id,
        "variation_id": str(variation_id),
        "attribute_amount": amount_name,
        "quantity": "1",
        "confirm_add_to_cart": "yes",
        user_f: user_id,
        server_f: server_id,
    })
    # ဆိုက်ရဲ့ form က multipart/form-data နဲ့ ပို့တာမို့ ထိုနည်းတူ ပို့မယ်
    files = {k: (None, str(v)) for k, v in data.items()}
    r = s.post(PRODUCT_URL, files=files, headers={"Referer": PRODUCT_URL, "Origin": BASE}, timeout=30)
    errs = [e.get_text(" ", strip=True) for e in _soup(r.text).select(".woocommerce-error")]
    sent = sorted(k for k in data if k.startswith("text-") or k in ("confirm_add_to_cart", "variation_id", "attribute_amount"))
    log("add_to_cart HTTP", r.status_code, "| sent:", sent, "| errors:", errs,
        "| added-msg:", "has been added to your cart" in r.text)
    if errs:
        raise BuyError("Cart ထဲ မထည့်နိုင်ဘူး: " + errs[0][:200] + " | ပို့ခဲ့တဲ့ field: " + ", ".join(sent))


def verify_cart(s, amount_name, user_id, server_id):
    soup, n, _ = cart_state(s)
    if n != 1:
        raise BuyError(f"Cart ထဲ item {n} ခု ဖြစ်နေတယ် (၁ ခုပဲ ဖြစ်ရမယ်)")
    text = _norm(soup.get_text(" ", strip=True))
    for need in (amount_name, user_id, server_id):
        if need not in text:
            raise BuyError("Cart ထဲက အချက်အလက် (package / User ID / Server ID) မကိုက်ဘူး")


# ---------- checkout ----------
def open_checkout(s):
    r = s.get(CHECKOUT_URL, timeout=20)
    if r.status_code != 200 or "checkout" not in r.url.lower():
        raise BuyError("Checkout page ဖွင့်မရဘူး")
    soup = _soup(r.text)
    form = soup.select_one("form.checkout, form[name='checkout']")
    if not form:
        raise BuyError("Checkout form မတွေ့ဘူး")
    return r, soup, form


def wallet_option(soup, form):
    """MooGold Wallet radio ကို ရှာမယ်။ (value, လက်ကျန် or None) ပြန်ပေးတယ်"""
    for inp in form.select("input[name='payment_method']"):
        lab = soup.select_one(f"label[for='{inp.get('id')}']") if inp.get("id") else None
        label_text = _norm(lab.get_text(" ", strip=True)) if lab else ""
        if "wallet" not in f"{inp.get('value', '')} {label_text}".lower():
            continue
        box = inp.find_parent("li") or inp.parent
        container = _norm(box.get_text(" ", strip=True)) if box else ""
        balance = None
        for txt in (label_text, container):
            m = re.search(r"balance[^$\d]*\$?\s*([\d,]+(?:\.\d+)?)", txt, re.I)
            if m:
                balance = _dec(m.group(1))
                break
        return inp.get("value"), balance
    raise BuyError("Checkout မှာ MooGold Wallet ရွေးစရာ မပေါ်ဘူး (cart ထဲမှာ တခြား item ပါနေ ဒါမှမဟုတ် ဆိုက်ပြောင်းသွားနိုင်)")


def parse_total(soup):
    el = soup.select_one(".order-total .woocommerce-Price-amount, .order-total .amount, .order-total bdi")
    if el:
        m = re.search(r"([\d,]+(?:\.\d+)?)", el.get_text(" ", strip=True))
        if m and _dec(m.group(1)) is not None:
            return _dec(m.group(1))
    text = _norm(soup.get_text(" ", strip=True)).lower()
    m = re.search(r"(?<!sub)total\s*:?\s*\$\s*([\d,]+(?:\.\d+)?)", text)
    return _dec(m.group(1)) if m else None


def build_payload(form, wallet_value):
    payload = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or name == "payment_method":
            continue
        typ = (el.get("type") or el.name).lower()
        if typ in ("submit", "button", "image", "file"):
            continue
        if typ == "radio":
            if el.has_attr("checked"):
                payload[name] = el.get("value", "")
            continue
        if typ == "checkbox":
            if name == "terms":
                payload["terms"] = "on"
            elif el.has_attr("checked"):
                payload[name] = el.get("value", "on")
            continue
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            payload[name] = opt.get("value", "") if opt else ""
        elif el.name == "textarea":
            payload[name] = el.get_text()
        else:
            payload[name] = el.get("value", "")
    payload["payment_method"] = wallet_value
    for need in ("billing_first_name", "billing_last_name", "billing_email"):
        if not payload.get(need):
            raise BuyError(f"Checkout မှာ {need} အလွတ်ဖြစ်နေတယ်၊ MooGold account ထဲ ဖြည့်ထားပါ")
    return payload


def place_order(s, payload, referer):
    """အော်ဒါကို တစ်ကြိမ်ပဲ ပို့မယ်။ ('success', order_id) / ('failure', msg) / ('unknown', msg)"""
    r = s.post(ORDER_AJAX_URL, data=payload, timeout=60,
               headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
    try:
        data = r.json()
    except ValueError:
        return "unknown", f"JSON မဟုတ်တဲ့ အဖြေ (HTTP {r.status_code})"
    result = data.get("result")
    if result == "success":
        redirect = data.get("redirect") or ""
        m = re.search(r"order-received/(\d+)", redirect)
        return "success", (m.group(1) if m else "?")
    if result == "failure":
        msg = _norm(_soup(data.get("messages") or "").get_text(" ", strip=True))
        return "failure", msg[:300] or "အကြောင်းရင်း မသိရဘူး"
    return "unknown", f"မျှော်လင့်မထားတဲ့ အဖြေ (HTTP {r.status_code})"


# ---------- အစီအစဉ်တစ်ခုလုံး ----------
def run_purchase(s, pkg, user_id, server_id, max_usd, buy_enabled):
    """dict {status: dryrun/success/failed/unknown, text, order_id?} ပြန်ပေးတယ်။ ဝယ်မရခင် ရပ်ရင် BuyError"""
    price = Decimal(str(pkg["price"]))
    if price > max_usd:
        raise BuyError(f"ဈေး ${price} က ကန့်သတ်ပမာဏ ${max_usd} ထက် များနေတယ်")
    force_usd(s)
    product_id, user_f, server_f = read_fields(s)
    _, n, _ = cart_state(s)
    if n != 0:
        raise BuyError(f"Cart ထဲမှာ item {n} ခု ရှိနေတယ်။ ဆိုက်မှာ ကိုယ်တိုင် ဖယ်ပြီးမှ ပြန်စမ်းပါ")

    placed = False
    try:
        add_to_cart(s, product_id, pkg["id"], pkg["name"], user_f, server_f, user_id, server_id)
        verify_cart(s, pkg["name"], user_id, server_id)
        r, soup, form = open_checkout(s)
        wallet_value, balance = wallet_option(soup, form)
        total = parse_total(soup)
        if total is None:
            raise BuyError("Checkout ကနေ စုစုပေါင်းဈေး ဖတ်မရဘူး")
        if abs(total - price) > Decimal("0.005"):
            raise BuyError(f"Checkout ဈေး (${total}) နဲ့ စာရင်းဈေး (${price}) မကိုက်ဘူး")
        if total > max_usd:
            raise BuyError(f"Checkout ဈေး ${total} က ကန့်သတ်ပမာဏ ${max_usd} ထက် များနေတယ်")
        if balance is not None and balance < total:
            raise BuyError(f"Wallet လက်ကျန် ${balance} က မလောက်ဘူး (လိုတာ ${total})")
        payload = build_payload(form, wallet_value)

        if not buy_enabled:
            left = clear_cart(s)
            return {"status": "dryrun",
                    "text": (f"🧪 DRY-RUN ပြီးပါပြီ (အော်ဒါ မတင်ပါဘူး)\n"
                             f"Wallet ရွေးစရာ: ✅ ({wallet_value})\n"
                             f"Wallet လက်ကျန်: {'$' + str(balance) if balance is not None else 'ဖတ်မရ'}\n"
                             f"စုစုပေါင်း: ${total}\n"
                             f"Cart: {'ရှင်းပြီး' if left == 0 else 'မရှင်းနိုင်ဘူး၊ ဆိုက်မှာ ကိုယ်တိုင်ဖယ်ပါ'}\n\n"
                             f"တကယ်ဝယ်ချင်ရင် Render မှာ BUY_ENABLED=1 ထားပါ။")}

        placed = True  # ဒီအချိန်ကစပြီး မရှင်းတော့ဘူး
        status, info = place_order(s, payload, r.url)
    except BuyError:
        if not placed:
            try:
                clear_cart(s)
            except Exception:
                pass
        raise
    except requests.RequestException as e:
        if placed:
            return {"status": "unknown",
                    "text": ("⚠️ အော်ဒါပို့ပြီး အဖြေ မရလိုက်ဘူး (" + type(e).__name__ + ")။\n"
                             "အော်ဒါ တင်ပြီးသားဖြစ်နိုင်လို့ /orders နဲ့ စစ်ပါ။ ထပ်မတင်ပါနဲ့။")}
        try:
            clear_cart(s)
        except Exception:
            pass
        raise BuyError("MooGold နဲ့ ချိတ်ဆက်မှု မအောင်မြင်ဘူး၊ နောက်မှ ပြန်စမ်းပါ")

    if status == "success":
        return {"status": "success", "order_id": info,
                "text": (f"✅ Order #{info} တင်ပြီးပါပြီ (MooGold Wallet နဲ့ ပေးချေ)။\n"
                         f"/orders နဲ့ အခြေအနေ စစ်ပါ။")}
    if status == "failure":
        try:
            clear_cart(s)
        except Exception:
            pass
        return {"status": "failed",
                "text": f"❌ Order မအောင်မြင်ဘူး: {info}\nထပ်မကြိုးစားပါဘူး။ /balance နဲ့ /orders ကို စစ်ပါ။"}
    return {"status": "unknown",
            "text": f"⚠️ အော်ဒါ အခြေအနေ မသေချာဘူး ({info})။\n/orders နဲ့ စစ်ပါ၊ ထပ်မတင်ပါနဲ့။"}


# ---------- ဖတ်ရုံ အလုပ်များ ----------
def get_wallet_balance(s):
    r = s.get(WALLET_URL, timeout=20)
    text = _norm(_soup(r.text).get_text(" ", strip=True))
    m = re.search(r"balance\s*(?:usd|\$)?\s*\$?\s*([\d,]+(?:\.\d+)?)", text, re.I)
    return _dec(m.group(1)) if m else None


def get_orders(s, limit=8):
    r = s.get(ORDERS_URL, timeout=20)
    rows = []
    for tr in _soup(r.text).select("table tr"):
        cells = [_norm(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cells) >= 4:
            rows.append(cells[:4])
    return rows[:limit]
