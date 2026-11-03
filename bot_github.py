"""
نسخه‌ی GitHub Actions: هر بار اجرا می‌شود، محصولات جدید را می‌فرستد و تمام می‌شود.
اطلاعات حساس از Secrets خوانده می‌شوند (داخل کد نوشته نشده‌اند).
"""
import html
import json
import os
import re
import time

import requests

BOT_TOKEN = os.environ["9116559772:AAEI--HjhcnJF18QI3kGKRYTiZfEHtk3TkM"]
CHANNEL = os.environ["@Jojeshopir"]
SITE_URL = os.environ["https://jojeshop.ir/"].rstrip("/")
DELAY_BETWEEN_POSTS = 4
STATE_FILE = "sent_ids.json"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_sent():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def fetch_products():
    products, page = [], 1
    while True:
        r = requests.get(
            f"{SITE_URL}/wp-json/wc/store/v1/products",
            params={"per_page": 100, "page": page, "orderby": "date", "order": "asc"},
            timeout=30,
        )
        if r.status_code != 200:
            print("پاسخ سایت:", r.status_code)
            break
        data = r.json()
        if not data:
            break
        products.extend(data)
        page += 1
    return products


def clean(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def build_caption(p):
    prices = p.get("prices", {})
    minor = int(prices.get("currency_minor_unit", 0))
    price = int(prices.get("price") or 0) / (10 ** minor)
    symbol = prices.get("currency_symbol", "")
    caption = f"<b>{html.escape(clean(p['name']))}</b>\n"
    if price:
        caption += f"💰 {price:,.0f} {symbol}\n"
    desc = clean(p.get("short_description"))[:200]
    if desc:
        caption += f"\n{html.escape(desc)}\n"
    caption += f"\n🔗 {p['permalink']}"
    return caption[:1024]


def send_product(p):
    caption = build_caption(p)
    images = p.get("images") or []
    if images:
        r = requests.post(f"{API}/sendPhoto", data={
            "chat_id": CHANNEL, "photo": images[0]["src"],
            "caption": caption, "parse_mode": "HTML",
        }, timeout=30)
    else:
        r = requests.post(f"{API}/sendMessage", data={
            "chat_id": CHANNEL, "text": caption, "parse_mode": "HTML",
        }, timeout=30)
    if r.status_code == 429:
        time.sleep(r.json().get("parameters", {}).get("retry_after", 30))
        return send_product(p)
    if not r.ok:
        print("خطای تلگرام:", r.text)
    return r.ok


if __name__ == "__main__":
    sent = load_sent()
    try:
        for p in fetch_products():
            if p["id"] in sent:
                continue
            if send_product(p):
                sent.add(p["id"])
                save_sent(sent)
                print("ارسال شد:", clean(p["name"]))
                time.sleep(DELAY_BETWEEN_POSTS)
    finally:
        save_sent(sent)
