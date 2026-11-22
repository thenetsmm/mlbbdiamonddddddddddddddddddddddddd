# Laptop မှာ လုပ်ရမယ့်အဆင့်များ (session ထုတ်တာ)

CAPTCHA က login မှာပဲ ရှိတာမို့ admin က ကိုယ်တိုင် ဖြေရပါမယ်။

1. Chrome ကို debug port နဲ့ ဖွင့်ပါ (PowerShell):

   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\moogold\chrome_profile"

2. ပွင့်လာတဲ့ Chrome မှာ https://moogold.com/account/ ကိုသွားပြီး email/password ရိုက်၊ Verify နှိပ်၊ Log in ဝင်ပါ။
3. Chrome ကို မပိတ်ဘဲ တခြား PowerShell တစ်ခုမှာ:

   Set-Location D:\moogold
   python -m pip install playwright
   python save_session.py

4. ထွက်လာတဲ့ moogold_session.json ကို Telegram bot chat ထဲ ဖိုင်အနေနဲ့ ပို့ပါ (bot က MongoDB ထဲသိမ်းပြီး chat ထဲက ဖိုင်ကို ဖျက်ပေးမယ်)။
5. ပြီးရင် Chrome ကို ပိတ်ပါ (debug port ပွင့်နေတာ မလုံခြုံဘူး)။

moogold_session.json ကို GitHub ပေါ် မတင်ပါနဲ့၊ chat ထဲ မျှဝေမပေးပါနဲ့။
