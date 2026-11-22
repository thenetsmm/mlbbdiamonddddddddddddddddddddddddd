# MooGold MLBB Telegram bot (Render, webhook mode)

## ဖိုင်များ
- bot_render.py     : Telegram bot (webhook) + session စောင့်ကြည့်ခြင်း + /buy flow
- moogold_buy.py    : MooGold wallet ဝယ်ယူတဲ့ logic (လုံခြုံရေးစစ်ဆေးချက်များ ပါ)
- moogold_prices.py : ဈေးစာရင်း ဖတ်တာ
- tools/            : laptop မှာပဲ သုံးတဲ့ script များ (Render မှာ မလိုပါ)

## Render settings
- Build Command : pip install -r requirements.txt
- Start Command : python bot_render.py
- Instance type : Free

## Environment variables
| Key | Value |
|---|---|
| BOT_TOKEN | BotFather ပေးတဲ့ token |
| WEBHOOK_SECRET | ကျပန်းစာတန်း (စာလုံး၊ ဂဏန်း၊ - _ ပဲ) |
| ADMIN_ID | admin ရဲ့ Telegram user ID |
| MONGODB_URI | MongoDB connection string |
| BUY_ENABLED | 0 (DRY-RUN၊ default) / 1 (တကယ်ဝယ်) |
| MAX_ORDER_USD | တစ်ခါဝယ်လျှင် အများဆုံးပမာဏ (default 1.00) |

## Commands
/start /prices /price 5 /check /myid
Admin only: /session_check /balance /orders /buy 5 <UserID> <ServerID>

## ပထမဆုံး စမ်းပုံ
1. BUY_ENABLED=0 (DRY-RUN) နဲ့ /buy 5 <UserID> <ServerID> ကို အရင်စမ်းပါ။ cart ထဲထည့်၊ checkout ကြည့်၊ cart ပြန်ရှင်း၊ ဘာမှမဝယ်ပါ။
2. DRY-RUN ရလဒ်မှန်မှ BUY_ENABLED=1 ထားပြီး $0.09 အော်ဒါတစ်ခု စမ်းပါ။

tokens၊ MongoDB URI၊ moogold_session.json ကို GitHub ပေါ် မတင်ပါနဲ့။
