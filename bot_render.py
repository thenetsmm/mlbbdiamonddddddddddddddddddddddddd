import os
import re
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from moogold_prices import get_mlbb_packages, URL, HEADERS

TOKEN = os.environ.get("BOT_TOKEN")
SECRET = os.environ.get("WEBHOOK_SECRET")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
PORT = int(os.environ.get("PORT", "10000"))

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


def handle(chat_id, text):
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    try:
        if cmd == "/start":
            send(chat_id, "MLBB ဈေးစာရင်း bot ပါ။\n/prices — စာရင်းအကုန်\n/price 5 — Diamond အရေအတွက်နဲ့ ရှာမယ်\n/check — MooGold ချိတ်ဆက်မှု စစ်မယ်")
        elif cmd == "/prices":
            send(chat_id, prices_text())
        elif cmd == "/price" and arg:
            send(chat_id, price_text(arg))
        elif cmd == "/price":
            send(chat_id, "ဥပမာ: /price 5")
        elif cmd == "/check":
            send(chat_id, check_text())
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
        if chat_id and text.startswith("/"):
            threading.Thread(target=handle, args=(chat_id, text), daemon=True).start()

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
