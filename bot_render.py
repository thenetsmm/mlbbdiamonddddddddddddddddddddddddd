import os
import re
import json
import threading
import time
import traceback
import uuid
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from moogold_prices import get_mlbb_packages, URL, HEADERS
import moogold_buy as mb

TOKEN = os.environ.get("BOT_TOKEN")
SECRET = os.environ.get("WEBHOOK_SECRET")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
MONGODB_URI = os.environ.get("MONGODB_URI")
# ဝယ်ယူခြင်း: BUY_ENABLED=1 ထားမှ တကယ်ဝယ်မယ်၊ မဟုတ်ရင် DRY-RUN (အော်ဒါ မတင်ဘူး)
BUY_ENABLED = os.environ.get("BUY_ENABLED", "0") == "1"
MAX_ORDER_USD = Decimal(os.environ.get("MAX_ORDER_USD", "1.00"))
CONFIRM_SECONDS = 300
BUY_LOCK = threading.Lock()
# Session ထုတ်ခဲ့တဲ့ Chrome ရဲ့ User-Agent နဲ့ တူရမယ် (Cloudflare cookie တွေက UA နဲ့ ချိတ်တတ်လို့)
SESSION_UA = os.environ.get(
    "SESSION_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
)

if not TOKEN or not SECRET:
    raise SystemExit("BOT_TOKEN နဲ့ WEBHOOK_SECRET environment variable လိုပါတယ်")

API = f"https://api.telegram.org/bot{TOKEN}"


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    requests.post(f"{API}/sendMessage", json=payload, timeout=20)


def tg(method, **payload):
    try:
        return requests.post(f"{API}/{method}", json=payload, timeout=20)
    except requests.RequestException:
        traceback.print_exc()


def is_admin(from_id):
    return bool(ADMIN_ID) and from_id == ADMIN_ID


def in_stock():
    return [p for p in get_mlbb_packages() if p["in_stock"]]


def prices_text():
    lines = [f"{p['name']} — ${p['price']:.2f}" for p in in_stock()]
    return "Mobile Legends (MooGold)\n\n" + "\n".join(lines)


def price_text(q):
    hits = [p for p in in_stock()
            if re.match(rf"^{re.escape(q)}(\s|\+|$)", p["name"])]
    if not hits:
        return f"'{q}' နဲ့ ကိုက်တဲ့ package မတွေ့ပါ။ /prices နဲ့ စာရင်းကြည့်ပါ။"
    return "\n".join(f"{p['name']} — ${p['price']:.2f}" for p in hits)


def check_text():
    r = requests.get(URL, headers=HEADERS, timeout=20)
    challenge = "Just a moment" in r.text
    form = "variations_form" in r.text
    return (f"MooGold HTTP status: {r.status_code}\n"
            f"Page size: {len(r.text)}\n"
            f"Cloudflare challenge: {'ပေါ်နေတယ်' if challenge else 'မပေါ်ဘူး'}\n"
            f"Variations form: {'ရှိတယ်' if form else 'မရှိဘူး'}")


# ---------- session (MongoDB) ----------
_mongo = {"col": None}


def state_col():
    if _mongo["col"] is None:
        if not MONGODB_URI:
            raise RuntimeError("MONGODB_URI မသတ်မှတ်ရသေးပါ")
        from pymongo import MongoClient
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
        _mongo["col"] = client["moogold"]["bot_state"]
    return _mongo["col"]


def orders_col():
    return state_col().database["buy_orders"]


def save_session(state):
    state_col().update_one(
        {"_id": "session"},
        {"$set": {"state": state, "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}},
        upsert=True,
    )


def load_session():
    return state_col().find_one({"_id": "session"})


def make_session(state):
    s = requests.Session()
    s.headers.update({"User-Agent": SESSION_UA, "Accept-Language": "en-US,en;q=0.9"})
    for c in state.get("cookies", []):
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    return s


def inspect_session():
    """Session ကို စစ်ပြီး dict ပြန်ပေးတယ်။ code: nosession / ok / expired / challenge"""
    doc = load_session()
    if not doc:
        return {"code": "nosession", "doc": None}
    state = doc["state"]
    has_cf = any(c.get("name") == "cf_clearance" for c in state.get("cookies", []))
    r = make_session(state).get("https://moogold.com/account/", timeout=20)
    raw = r.text
    t = raw.lower()
    login_form = "woocommerce-login-nonce" in raw
    overview = "account overview" in t
    m = re.search(r"<title>(.*?)</title>", raw, re.S)
    title = m.group(1).strip() if m else "?"
    if "just a moment" in t:
        code = "challenge"
    elif overview and not login_form:
        code = "ok"
    elif login_form:
        code = "expired"
    else:
        code = "unknown"
    return {"code": code, "doc": doc, "status": r.status_code, "title": title,
            "has_cf": has_cf, "login_form": login_form, "overview": overview}


STATUS_TEXT = {
    "ok": "Login ဝင်ထားဆဲ ✅ (session အလုပ်လုပ်တယ်)",
    "expired": "Login မဝင်ထားဘူး (login form ပေါ်နေတယ်၊ session ကုန် ဒါမှမဟုတ် Render IP/browser မကိုက်)",
    "challenge": "Cloudflare challenge ပေါ်နေတယ် (Render ကနေ session ကို ပယ်ချခံရတယ်)",
    "unknown": "မသေချာဘူး (title ကို ကြည့်ပါ)",
}


def check_session_text():
    info = inspect_session()
    if info["code"] == "nosession":
        return "Session မရှိသေးပါ။ laptop မှာ ထုတ်ထားတဲ့ moogold_session.json ကို ဒီ chat ထဲ ဖိုင်အနေနဲ့ ပို့ပါ။"
    return (f"HTTP status: {info['status']}\n"
            f"Title: {info['title']}\n"
            f"Session သိမ်းထားတဲ့အချိန်: {info['doc'].get('updated')}\n"
            f"cf_clearance cookie: {'ပါတယ်' if info['has_cf'] else 'မပါဘူး'}\n"
            f"Login form: {'ပါတယ်' if info['login_form'] else 'မပါဘူး'} | "
            f"Account overview: {'ပါတယ်' if info['overview'] else 'မပါဘူး'}\n"
            f"ရလဒ်: {STATUS_TEXT.get(info['code'])}")


# ---------- session သက်တမ်း စောင့်ကြည့်ခြင်း ----------
WATCH_MINUTES = int(os.environ.get("SESSION_WATCH_MINUTES", "30"))


def watch_decision(last, code):
    """အရင်အခြေအနေ (last) နဲ့ အခုအခြေအနေ (code) ကိုကြည့်ပြီး admin ကို ပို့ရမယ့်စာ ပြန်ပေးတယ် (မလိုရင် None)"""
    if code == last:
        return None
    if code in ("expired", "challenge"):
        return ("⚠️ MooGold session ကုန်သွားပြီ (သို့မဟုတ် လက်မခံတော့ဘူး)။\n"
                "Laptop မှာ debug Chrome နဲ့ login ဝင်ပြီး save_session.py ပြေးကာ "
                "moogold_session.json ကို ဒီ chat ထဲ ပြန်ပို့ပါ။")
    if code == "ok" and last in ("expired", "challenge", "unknown"):
        return "✅ MooGold session ပြန်အလုပ်လုပ်ပြီ။"
    return None


def set_watch_state(code):
    state_col().update_one({"_id": "watch"}, {"$set": {"last": code}}, upsert=True)


def session_watch_loop():
    time.sleep(60)
    while True:
        try:
            if ADMIN_ID and MONGODB_URI:
                info = inspect_session()
                code = info["code"]
                if code != "nosession":
                    meta = state_col().find_one({"_id": "watch"}) or {}
                    msg = watch_decision(meta.get("last"), code)
                    if msg:
                        send(ADMIN_ID, msg)
                    if code != meta.get("last"):
                        set_watch_state(code)
        except Exception:
            traceback.print_exc()
        time.sleep(WATCH_MINUTES * 60)


# ---------- ဝယ်ယူခြင်း / လက်ကျန် / အော်ဒါစာရင်း ----------
def get_live_session():
    """Session ok ဖြစ်ရင် (requests session, None)၊ မဟုတ်ရင် (None, ပြောပြရမယ့်စာ)"""
    info = inspect_session()
    code = info["code"]
    if code == "nosession":
        return None, "Session မရှိသေးပါ။ moogold_session.json ကို ဒီ chat ထဲ ပို့ပါ။"
    if code != "ok":
        return None, "Session အလုပ်မလုပ်ဘူး: " + STATUS_TEXT.get(code, code)
    return make_session(info["doc"]["state"]), None


def find_packages(q):
    return [p for p in in_stock() if re.match(rf"^{re.escape(q)}(\s|\+|$)", p["name"])]


def cmd_buy(chat_id, from_id, arg):
    if not is_admin(from_id):
        send(chat_id, "admin သာ ဝယ်လို့ရပါတယ်။")
        return
    parts = arg.split()
    if len(parts) != 3:
        send(chat_id, "သုံးပုံ: /buy <package> <User ID> <Server ID>\nဥပမာ: /buy 5 824412642 12267")
        return
    q, uid, sid = parts
    if not re.fullmatch(r"\d{5,12}", uid) or not re.fullmatch(r"\d{1,6}", sid):
        send(chat_id, "User ID (ဂဏန်း ၅-၁၂ လုံး) နဲ့ Server ID (ဂဏန်း ၁-၆ လုံး) ကို ပြန်စစ်ပါ။")
        return
    hits = find_packages(q)
    if not hits:
        send(chat_id, f"'{q}' နဲ့ ကိုက်တဲ့ package (stock ရှိတာ) မတွေ့ပါ။ /prices ကိုကြည့်ပါ။")
        return
    if len(hits) > 1:
        send(chat_id, "အများကြီး ကိုက်နေတယ်၊ ပိုတိကျအောင် ရေးပါ:\n" + "\n".join(p["name"] for p in hits))
        return
    pkg = hits[0]
    if Decimal(str(pkg["price"])) > MAX_ORDER_USD:
        send(chat_id, f"ဈေး ${pkg['price']:.2f} က ကန့်သတ်ပမာဏ ${MAX_ORDER_USD} ထက် များတယ်။ (MAX_ORDER_USD ကို Render မှာ ပြင်ပါ)")
        return
    s, msg = get_live_session()
    if not s:
        send(chat_id, msg)
        return
    token = uuid.uuid4().hex[:10]
    orders_col().insert_one({
        "_id": token, "status": "pending", "created": time.time(),
        "pkg": pkg, "user_id": uid, "server_id": sid,
    })
    mode = "🟥 REAL (အမှန်တကယ် ဝယ်မယ်)" if BUY_ENABLED else "🧪 DRY-RUN (အော်ဒါ မတင်ဘူး)"
    send(chat_id,
         f"အတည်ပြုပါ\n\nPackage: {pkg['name']}\nဈေး: ${pkg['price']:.2f}\n"
         f"User ID: {uid}\nServer ID: {sid}\nပေးချေမှု: MooGold Wallet\nမုဒ်: {mode}\n\n"
         f"(၅ မိနစ်အတွင်း နှိပ်ရပါမယ်)",
         keyboard=[[{"text": "✅ အတည်ပြုမယ်", "callback_data": f"buy:ok:{token}"},
                    {"text": "❌ ပယ်ဖျက်", "callback_data": f"buy:no:{token}"}]])


def handle_callback(cb):
    try:
        from_id = (cb.get("from") or {}).get("id")
        msg = cb.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        tg("answerCallbackQuery", callback_query_id=cb["id"])
        if not chat_id or not is_admin(from_id):
            return
        try:
            _, action, token = (cb.get("data") or "").split(":")
        except ValueError:
            return
        col = orders_col()
        if action == "no":
            col.find_one_and_update({"_id": token, "status": "pending"}, {"$set": {"status": "cancelled"}})
            tg("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})
            send(chat_id, "ပယ်ဖျက်ပြီး။")
            return
        if action != "ok":
            return
        # တစ်ကြိမ်ပဲ သုံးလို့ရမယ်: pending -> processing (atomic)
        doc = col.find_one_and_update({"_id": token, "status": "pending"}, {"$set": {"status": "processing"}})
        tg("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})
        if not doc:
            send(chat_id, "ဒီ request ကို သုံးပြီးသား ဒါမှမဟုတ် မရှိတော့ဘူး။ ထပ်ဝယ်ချင်ရင် /buy ကို ပြန်ရိုက်ပါ။")
            return
        if time.time() - doc["created"] > CONFIRM_SECONDS:
            col.update_one({"_id": token}, {"$set": {"status": "expired"}})
            send(chat_id, "၅ မိနစ်ကျော်သွားပြီ၊ /buy ကို ပြန်ရိုက်ပါ။")
            return
        if not BUY_LOCK.acquire(blocking=False):
            col.update_one({"_id": token}, {"$set": {"status": "busy"}})
            send(chat_id, "တခြားအော်ဒါ လုပ်နေတုန်းပါ၊ ခဏစောင့်ပြီး /buy ပြန်ရိုက်ပါ။")
            return
        try:
            send(chat_id, "လုပ်ဆောင်နေပါတယ်...")
            s, smsg = get_live_session()
            if not s:
                col.update_one({"_id": token}, {"$set": {"status": "aborted", "note": smsg}})
                send(chat_id, smsg)
                return
            try:
                result = mb.run_purchase(s, doc["pkg"], doc["user_id"], doc["server_id"],
                                         MAX_ORDER_USD, BUY_ENABLED)
            except mb.BuyError as e:
                col.update_one({"_id": token}, {"$set": {"status": "aborted", "note": str(e)}})
                send(chat_id, f"🛑 မဝယ်ဘဲ ရပ်လိုက်တယ်: {e}\n(ငွေ မထွက်ပါဘူး)")
                return
            col.update_one({"_id": token}, {"$set": {"status": result["status"],
                                                     "order_id": result.get("order_id")}})
            send(chat_id, result["text"])
        finally:
            BUY_LOCK.release()
    except Exception:
        traceback.print_exc()
        if chat_id:
            send(chat_id, "⚠️ မမျှော်လင့်တဲ့ error ဖြစ်သွားတယ်။ အော်ဒါ တင်ပြီးသားဖြစ်နိုင်လို့ /orders နဲ့ စစ်ပါ၊ ထပ်မတင်ပါနဲ့။")


def cmd_balance(chat_id, from_id):
    if not is_admin(from_id):
        send(chat_id, "admin သာ သုံးလို့ရပါတယ်။")
        return
    s, msg = get_live_session()
    if not s:
        send(chat_id, msg)
        return
    bal = mb.get_wallet_balance(s)
    send(chat_id, f"MooGold Wallet လက်ကျန်: ${bal}" if bal is not None else "လက်ကျန် ဖတ်မရဘူး။")


def cmd_orders(chat_id, from_id):
    if not is_admin(from_id):
        send(chat_id, "admin သာ သုံးလို့ရပါတယ်။")
        return
    s, msg = get_live_session()
    if not s:
        send(chat_id, msg)
        return
    rows = mb.get_orders(s)
    if not rows:
        send(chat_id, "အော်ဒါစာရင်း ဖတ်မရဘူး။")
        return
    send(chat_id, "နောက်ဆုံး အော်ဒါများ:\n\n" + "\n".join(" | ".join(r) for r in rows))


def handle_document(chat_id, from_id, msg):
    if not (ADMIN_ID and from_id == ADMIN_ID):
        send(chat_id, "admin သာ ဖိုင်ပို့လို့ရပါတယ်။")
        return
    doc = msg["document"]
    name = (doc.get("file_name") or "").lower()
    if not name.endswith(".json") or doc.get("file_size", 0) > 1_000_000:
        send(chat_id, "moogold_session.json လို့ .json ဖိုင် (1MB အောက်) ကိုပဲ လက်ခံပါတယ်။")
        return
    try:
        info = requests.get(f"{API}/getFile", params={"file_id": doc["file_id"]}, timeout=20).json()
        raw = requests.get(
            f"https://api.telegram.org/file/bot{TOKEN}/{info['result']['file_path']}", timeout=30
        ).content
        state = json.loads(raw)
        cookies = [c for c in state.get("cookies", []) if "moogold.com" in (c.get("domain") or "")]
        if not cookies:
            send(chat_id, "ဖိုင်ထဲမှာ moogold cookie မတွေ့ပါ။ moogold_session.json ဟုတ်မဟုတ် စစ်ပါ။")
            return
        save_session({"cookies": cookies})
        # Session ဖိုင်က account နဲ့ တူတာမို့ chat ထဲက ဖိုင်ကို ဖျက်မယ်
        requests.post(f"{API}/deleteMessage",
                      json={"chat_id": chat_id, "message_id": msg["message_id"]}, timeout=20)
        send(chat_id, f"Session သိမ်းပြီးပြီ (cookie {len(cookies)} ခု)။ ပို့ထားတဲ့ဖိုင်ကို chat ထဲက ဖျက်ထားပါတယ်။ စစ်နေပါတယ်...")
        info = inspect_session()
        set_watch_state(info["code"])
        send(chat_id, check_session_text())
    except Exception:
        traceback.print_exc()
        send(chat_id, "Session သိမ်းမရပါ။ Render Logs ကို ကြည့်ပါ (MONGODB_URI၊ ဖိုင်ပုံစံ စစ်ပါ)။")


def handle(chat_id, from_id, text):
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    try:
        if cmd == "/start":
            send(chat_id, "MLBB ဈေးစာရင်း bot ပါ။\n/prices — စာရင်းအကုန်\n/price 5 — Diamond အရေအတွက်နဲ့ ရှာမယ်\n/check — MooGold ချိတ်ဆက်မှု စစ်မယ်\n/myid — မင့် Telegram ID\n/session_check — (admin) login session စစ်မယ်\n/balance — (admin) wallet လက်ကျန်\n/orders — (admin) အော်ဒါစာရင်း\n/buy 5 <UserID> <ServerID> — (admin) wallet နဲ့ ဝယ်မယ်")
        elif cmd == "/prices":
            send(chat_id, prices_text())
        elif cmd == "/price" and arg:
            send(chat_id, price_text(arg))
        elif cmd == "/price":
            send(chat_id, "ဥပမာ: /price 5")
        elif cmd == "/check":
            send(chat_id, check_text())
        elif cmd == "/buy":
            cmd_buy(chat_id, from_id, arg)
        elif cmd == "/balance":
            cmd_balance(chat_id, from_id)
        elif cmd == "/orders":
            cmd_orders(chat_id, from_id)
        elif cmd == "/myid":
            send(chat_id, f"မင့် Telegram ID: {from_id}")
        elif cmd == "/session_check":
            if ADMIN_ID and from_id == ADMIN_ID:
                send(chat_id, check_session_text())
            else:
                send(chat_id, "admin သာ သုံးလို့ရပါတယ်။")
    except Exception:
        traceback.print_exc()
        send(chat_id, "MooGold ကနေ ဖတ်လို့မရပါ၊ နောက်မှ ပြန်စမ်းပါ။ (/check နဲ့ စစ်ကြည့်နိုင်ပါတယ်)")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body=b"ok"):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply(200)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path != "/webhook" or \
           self.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET:
            self._reply(403, b"forbidden")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            update = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._reply(400, b"bad request")
            return
        self._reply(200)  # Telegram ကို အရင် ချက်ချင်း ပြန်ဖြေမယ်
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = (msg.get("chat") or {}).get("id")
        from_id = (msg.get("from") or {}).get("id")
        if update.get("callback_query"):
            threading.Thread(target=handle_callback, args=(update["callback_query"],), daemon=True).start()
        elif chat_id and msg.get("document"):
            threading.Thread(target=handle_document, args=(chat_id, from_id, msg), daemon=True).start()
        elif chat_id and text.startswith("/"):
            threading.Thread(target=handle, args=(chat_id, from_id, text), daemon=True).start()

    def log_message(self, *args):
        pass


def set_webhook():
    if not BASE_URL:
        print("RENDER_EXTERNAL_URL မတွေ့ပါ၊ webhook မသတ်မှတ်ရသေးပါ")
        return
    r = requests.post(f"{API}/setWebhook", timeout=20, json={
        "url": f"{BASE_URL}/webhook",
        "secret_token": SECRET,
        "allowed_updates": ["message", "callback_query"],
    })
    print("setWebhook:", r.status_code, r.text)


if __name__ == "__main__":
    set_webhook()
    threading.Thread(target=session_watch_loop, daemon=True).start()
    print(f"Listening on port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
