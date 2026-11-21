import os
import re
import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from moogold_prices import get_mlbb_packages, URL, HEADERS

TOKEN = os.environ.get("BOT_TOKEN")
SECRET = os.environ.get("WEBHOOK_SECRET")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
MONGODB_URI = os.environ.get("MONGODB_URI")
# Session ထုတ်ခဲ့တဲ့ Chrome ရဲ့ User-Agent နဲ့ တူရမယ် (Cloudflare cookie တွေက UA နဲ့ ချိတ်တတ်လို့)
SESSION_UA = os.environ.get(
    "SESSION_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
)

if not TOKEN or not SECRET:
    raise SystemExit("BOT_TOKEN နဲ့ WEBHOOK_SECRET environment variable လိုပါတယ်")

API = f"https://api.telegram.org/bot{TOKEN}"


def send(chat_id, text):
    requests.post(f"{API}/sendMessage",
                  json={"chat_id": chat_id, "text": text}, timeout=20)


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


def check_session_text():
    doc = load_session()
    if not doc:
        return "Session မရှိသေးပါ။ laptop မှာ ထုတ်ထားတဲ့ moogold_session.json ကို ဒီ chat ထဲ ဖိုင်အနေနဲ့ ပို့ပါ။"
    state = doc["state"]
    has_cf = any(c.get("name") == "cf_clearance" for c in state.get("cookies", []))
    r = make_session(state).get("https://moogold.com/account/", timeout=20)
    t = r.text.lower()
    if "just a moment" in t:
        status = "Cloudflare challenge ပေါ်နေတယ် (Render ကနေ session ကို ပယ်ချခံရတယ်)"
    elif ("logout" in t or "log out" in t) and 'type="password"' not in t:
        status = "Login ဝင်ထားဆဲ ✅ (session အလုပ်လုပ်တယ်)"
    else:
        status = "Login မဝင်ထားဘူး (session ကုန်၊ ဒါမှမဟုတ် Render IP/browser မကိုက်)"
    return (f"HTTP status: {r.status_code}\n"
            f"Session သိမ်းထားတဲ့အချိန်: {doc.get('updated')}\n"
            f"cf_clearance cookie: {'ပါတယ်' if has_cf else 'မပါဘူး'}\n"
            f"ရလဒ်: {status}")


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
            send(chat_id, "MLBB ဈေးစာရင်း bot ပါ။\n/prices — စာရင်းအကုန်\n/price 5 — Diamond အရေအတွက်နဲ့ ရှာမယ်\n/check — MooGold ချိတ်ဆက်မှု စစ်မယ်\n/myid — မင့် Telegram ID\n/session_check — (admin) login session စစ်မယ်")
        elif cmd == "/prices":
            send(chat_id, prices_text())
        elif cmd == "/price" and arg:
            send(chat_id, price_text(arg))
        elif cmd == "/price":
            send(chat_id, "ဥပမာ: /price 5")
        elif cmd == "/check":
            send(chat_id, check_text())
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
        if chat_id and msg.get("document"):
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
        "allowed_updates": ["message"],
    })
    print("setWebhook:", r.status_code, r.text)


if __name__ == "__main__":
    set_webhook()
    print(f"Listening on port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
