
"""
Telegram WooCommerce Product Bot
GitHub Actions Edition
"""
import html
import json
import os
import re
import time
import mimetypes
from urllib.parse import urlparse

import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
SITE_URL = os.environ["SITE_URL"].rstrip("/")

DELAY_BETWEEN_POSTS = 4
STATE_FILE = "sent_ids.json"
MAX_IMAGE_SIZE = 10 * 1024 * 1024

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ProductBot/1.0)",
})


def load_sent():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def fetch_products():
    products = []
    page = 1

    while True:
        try:
            r = SESSION.get(
                f"{SITE_URL}/wp-json/wc/store/v1/products",
                params={
                    "per_page": 100,
                    "page": page,
                    "orderby": "date",
                    "order": "asc",
                },
                timeout=30,
            )

            r.raise_for_status()
            data = r.json()

            if not data:
                break

            products.extend(data)
            print(f"صفحه {page}: {len(data)} محصول دریافت شد")

            if len(data) < 100:
                break

            page += 1

        except Exception as e:
            print("خطا در دریافت محصولات:", str(e))
            break

    print("مجموع محصولات دریافت‌شده:", len(products))
    return products


def clean(text):
    return html.unescape(
        re.sub(r"<[^>]+>", "", str(text or ""))
    ).strip()


def build_caption(p):
    prices = p.get("prices") or {}

    try:
        minor = int(prices.get("currency_minor_unit") or 0)
        price = int(prices.get("price") or 0) / (10 ** minor)
    except (ValueError, TypeError, ZeroDivisionError):
        price = 0

    symbol = prices.get("currency_symbol", "")

    name = html.escape(clean(p.get("name")))
    caption = f"<b>{name}</b>\n"

    if price:
        caption += f"💰 {price:,.0f} {html.escape(symbol)}\n"

    desc = clean(p.get("short_description"))

    if desc:
        caption += f"\n{html.escape(desc[:200])}\n"

    permalink = html.escape(p.get("permalink", ""), quote=True)
    caption += f"\n🔗 {permalink}"

    return caption[:1024]


def telegram_post(method, data, files=None):
    url = f"{API}/{method}"

    for attempt in range(3):
        try:
            r = SESSION.post(
                url,
                data=data,
                files=files,
                timeout=60,
            )

            result = r.json()

            if result.get("ok"):
                return True

            if result.get("error_code") == 429:
                wait = result.get(
                    "parameters", {}
                ).get("retry_after", 30)

                print(f"محدودیت تلگرام؛ انتظار {wait} ثانیه")
                time.sleep(wait)
                continue

            print("خطای تلگرام:", result)
            return False

        except Exception as e:
            print("خطای ارتباط با تلگرام:", str(e))
            time.sleep(3)

    return False


def download_image(image_url):
    try:
        headers = {
            "Referer": SITE_URL + "/",
            "User-Agent": "Mozilla/5.0",
        }

        r = SESSION.get(
            image_url,
            headers=headers,
            timeout=45,
            stream=True,
        )

        r.raise_for_status()

        content_type = r.headers.get(
            "Content-Type", ""
        ).split(";")[0].lower()

        if not content_type.startswith("image/"):
            print("آدرس موردنظر تصویر نیست:", content_type)
            return None

        content_length = int(
            r.headers.get("Content-Length", 0)
        )

        if content_length > MAX_IMAGE_SIZE:
            print("حجم تصویر بیشتر از 10 مگابایت است")
            return None

        image_data = bytearray()

        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                image_data.extend(chunk)

                if len(image_data) > MAX_IMAGE_SIZE:
                    print("حجم تصویر بیشتر از حد مجاز است")
                    return None

        if not image_data:
            return None

        ext = mimetypes.guess_extension(content_type)

        if content_type == "image/jpeg":
            ext = ".jpg"

        ext = ext or ".jpg"

        return bytes(image_data), ext, content_type

    except Exception as e:
        print("خطا در دانلود تصویر:", str(e))
        return None


def send_product(p):
    caption = build_caption(p)
    images = p.get("images") or []

    # تلاش برای ارسال تصویر
    if images:
        image_url = images[0].get("src", "")

        if image_url:
            print("دانلود تصویر:", p.get("name"))

            downloaded = download_image(image_url)

            if downloaded:
                image_data, ext, mime = downloaded

                success = telegram_post(
                    "sendPhoto",
                    {
                        "chat_id": CHANNEL,
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                    files={
                        "photo": (
                            f"product{ext}",
                            image_data,
                            mime,
                        )
                    },
                )

                if success:
                    return True

                print("ارسال عکس ناموفق بود؛ ارسال متنی امتحان می‌شود")

    # ارسال متنی در صورت نبودن یا خرابی تصویر
    print("ارسال محصول بدون تصویر:", p.get("name"))

    return telegram_post(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
    )


if __name__ == "__main__":

    sent = load_sent()

    print("محصولات قبلاً ارسال‌شده:", len(sent))

    products = fetch_products()

    print("شروع ارسال محصولات...")

    try:
        for p in products:

            product_id = str(p["id"])

            if product_id in sent:
                continue

            print("در حال پردازش:", p.get("name"))

            try:
                success = send_product(p)

                if success:
                    sent.add(product_id)
                    save_sent(sent)

                    print("ارسال شد:", clean(p.get("name")))

                    time.sleep(DELAY_BETWEEN_POSTS)

                else:
                    print(
                        "ارسال ناموفق:",
                        clean(p.get("name")),
                        "- در اجرای بعدی مجدداً تلاش می‌شود"
                    )

            except Exception as e:
                print("خطای محصول:", p.get("name"), str(e))
                continue

    finally:
        save_sent(sent)

    print("پایان عملیات")
    print("تعداد محصولات ثبت‌شده:", len(sent))
