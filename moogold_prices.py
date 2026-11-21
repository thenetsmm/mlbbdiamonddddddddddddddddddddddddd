import json
import time
import requests
from bs4 import BeautifulSoup

URL = "https://moogold.com/product/mobile-legends/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
CACHE_SECONDS = 300
_cache = {"time": 0, "data": []}


def get_mlbb_packages(force=False):
    """MLBB package စာရင်း ပြန်ပေးတယ်: [{name, price, id, in_stock}, ...]"""
    if not force and time.time() - _cache["time"] < CACHE_SECONDS and _cache["data"]:
        return _cache["data"]

    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.select_one("form.variations_form")
    if not form:
        raise RuntimeError("variations form မတွေ့ပါ (site ပြောင်းသွားတာ ဒါမှမဟုတ် challenge ပေါ်တာ ဖြစ်နိုင်)")

    variations = json.loads(form["data-product_variations"])
    data = [
        {
            "name": v["attributes"].get("attribute_amount", "?"),
            "price": float(v["display_price"]),
            "id": v["variation_id"],
            "in_stock": bool(v.get("is_in_stock")),
        }
        for v in variations
    ]
    data.sort(key=lambda x: x["price"])
    _cache.update(time=time.time(), data=data)
    return data


if __name__ == "__main__":
    for p in get_mlbb_packages():
        flag = "" if p["in_stock"] else "  (stock မရှိ)"
        print(f"{p['name']:45} ${p['price']:>7.2f}{flag}")
