
import html
import json
import os
import re
import time
import mimetypes
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
SITE_URL = os.environ["SITE_URL"].rstrip("/")

DELAY_BETWEEN_POSTS = 4
STATE_FILE = "sent_ids.json"
MAX_IMAGE_SIZE = 10 * 1024 * 1024

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

FOOTER = (
    "-------------------------------------------------------------------------------\n"
    "@Mahzyarrrs\n"
    "09945286021"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ProductBot/1.0)"
})


def load_sent():
    if not os.path.exists(STATE_FILE):
        return set()

    with open(STATE_FILE, encoding="utf-8") as f:
        return {str(item) for item in json.load(f)}


def save_sent(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(str(item) for item in ids), f)


def fetch_products():
    products = []
    page = 1

    while True:
        try:
            response = SESSION.get(
                f"{SITE_URL}/wp-json/wc/store/v1/products",
                params={
                    "per_page": 100,
                    "page": page,
                    "orderby": "date",
                    "order": "asc",
                },
                timeout=30,
            )

            response.raise_for_status()
            data = response.json()

            if not data:
                break

            products.extend(data)

            print(f"صفحه {page}: {len(data)} محصول دریافت شد")

            if len(data) < 100:
                break

            page += 1

        except Exception as error:
            print("خطا در دریافت محصولات:", str(error))
            break

    # مرتب‌سازی محلی از قدیمی به جدید
    products.sort(
        key=lambda p: p.get("date_created", "") or ""
    )

    print("مجموع محصولات:", len(products))

    return products


def clean(text):
    text = str(text or "")
    text = re.sub(
        r"(?is)<(script|style).*?>.*?</\\1>",
        "",
        text
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\\s+", " ", text).strip()


def extract_sizes(product):
    size_names = {
        "size",
        "sizes",
        "pa_size",
        "attribute_pa_size",
        "clothing size",
        "shoe size",
        "سایز",
        "اندازه",
        "سایز بندی",
        "سایزبندی",
    }

    found = []

    for attribute in product.get("attributes") or []:

        name = clean(attribute.get("name", "")).lower()
        taxonomy = clean(attribute.get("taxonomy", "")).lower()

        is_size = (
            name in size_names
            or taxonomy in size_names
            or "سایز" in name
            or "اندازه" in name
            or "size" in name
            or "size" in taxonomy
        )

        if not is_size:
            continue

        values = []

        for term in attribute.get("terms") or []:

            if isinstance(term, dict):
                value = term.get("name") or term.get("slug")
            else:
                value = term

            if value:
                values.append(clean(value))

        for option in attribute.get("options") or []:
            if option:
                values.append(clean(option))

        for value in values:
            if value and value not in found:
                found.append(value)

    return found


def build_caption(product):
    name = clean(product.get("name"))
    permalink = product.get("permalink", "")
    prices = product.get("prices") or {}

    try:
        minor = int(prices.get("currency_minor_unit") or 0)

        price = (
            int(prices.get("price") or 0)
            / (10 ** minor)
        )

    except (ValueError, TypeError, ZeroDivisionError):
        price = 0

    symbol = clean(prices.get("currency_symbol", ""))

    parts = [
        f"<b>{html.escape(name)}</b>"
    ]

    if price:
        parts.append(
            f"💰 {price:,.0f} {html.escape(symbol)}"
        )

    sizes = extract_sizes(product)

    if sizes:
        parts.append(
            "📏 سایز: " + html.escape("، ".join(sizes))
        )

    # توضیحات اصلی محصول
    description = clean(product.get("description", ""))

    if description:
        parts.append(
            html.escape(description[:400])
        )

    # لینک قابل کلیک
    if permalink:
        safe_url = html.escape(permalink, quote=True)

        parts.append(
            f'🔗 <a href="{safe_url}">مشاهده در سایت</a>'
        )

    # امضای ثابت انتهای تمام پیام‌ها
    parts.append(html.escape(FOOTER))

    caption = "\n\n".join(parts)

    # محدودیت کپشن تلگرام
    if len(caption) > 1024:
        # ابتدا توضیحات را کوتاه می‌کنیم
        description = clean(product.get("description", ""))

        if description:
            remaining = max(0, 1024 - len(caption) + len(
                html.escape(description[:400])
            ) - 3)

            shortened = html.escape(description[:remaining]) + "..."

            parts = [
                f"<b>{html.escape(name)}</b>"
            ]

            if price:
                parts.append(
                    f"💰 {price:,.0f} {html.escape(symbol)}"
                )

            if sizes:
                parts.append(
                    "📏 سایز: " + html.escape("، ".join(sizes))
                )

            if shortened != "...":
                parts.append(shortened)

            if permalink:
                parts.append(
                    f'🔗 <a href="{safe_url}">مشاهده در سایت</a>'
                )

            parts.append(html.escape(FOOTER))

            caption = "\n\n".join(parts)

    return caption


def telegram_post(method, data, files=None):

    url = f"{API}/{method}"

    for attempt in range(3):

        try:
            response = SESSION.post(
                url,
                data=data,
                files=files,
                timeout=60,
            )

            result = response.json()

            if result.get("ok"):
                return True

            if result.get("error_code") == 429:

                wait = result.get(
                    "parameters", {}
                ).get("retry_after", 30)

                print(f"محدودیت تلگرام: {wait} ثانیه")

                time.sleep(wait)
                continue

            print("خطای تلگرام:", result)

            return False

        except Exception as error:

            print("خطای ارتباط با تلگرام:", str(error))

            if attempt < 2:
                time.sleep(3)

    return False


def download_image(image_url):

    try:
        response = SESSION.get(
            image_url,
            headers={
                "Referer": SITE_URL + "/",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=45,
            stream=True,
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type", ""
        ).split(";")[0].lower()

        if not content_type.startswith("image/"):
            print("آدرس دریافت‌شده تصویر نیست:", content_type)
            return None

        content_length = int(
            response.headers.get("Content-Length", 0)
        )

        if content_length > MAX_IMAGE_SIZE:
            print("حجم تصویر بیش از حد مجاز است")
            return None

        image_data = bytearray()

        for chunk in response.iter_content(chunk_size=8192):

            if chunk:
                image_data.extend(chunk)

                if len(image_data) > MAX_IMAGE_SIZE:
                    print("حجم تصویر بیش از 10 مگابایت است")
                    return None

        if not image_data:
            return None

        extension = mimetypes.guess_extension(content_type) or ".jpg"

        if content_type == "image/jpeg":
            extension = ".jpg"

        return bytes(image_data), extension, content_type

    except Exception as error:

        print("خطا در دانلود تصویر:", str(error))

        return None


def send_product(product):

    caption = build_caption(product)
    images = product.get("images") or []

    # تلاش برای ارسال تصویر
    if images:

        image_url = images[0].get("src", "")

        if image_url:

            print("دانلود تصویر:", product.get("name"))

            downloaded = download_image(image_url)

            if downloaded:

                image_data, extension, mime_type = downloaded

                success = telegram_post(
                    "sendPhoto",
                    {
                        "chat_id": CHANNEL,
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                    files={
                        "photo": (
                            f"product{extension}",
                            image_data,
                            mime_type,
                        )
                    },
                )

                if success:
                    return True

                print("ارسال تصویر ناموفق بود")

    # ارسال متن در صورت نبود تصویر یا خرابی آن
    print("ارسال محصول بدون تصویر:", product.get("name"))

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

    print("تعداد محصولات قبلاً ارسال‌شده:", len(sent))

    products = fetch_products()

    print("شروع ارسال محصولات...")

    try:

        for product in products:

            product_id = str(product["id"])

            if product_id in sent:
                continue

            print("در حال پردازش:", product.get("name"))

            try:

                success = send_product(product)

                if success:

                    sent.add(product_id)
                    save_sent(sent)

                    print(
                        "ارسال شد:",
                        clean(product.get("name"))
                    )

                    time.sleep(DELAY_BETWEEN_POSTS)

                else:

                    print(
                        "ارسال ناموفق:",
                        clean(product.get("name"))
                    )

            except Exception as error:

                print(
                    "خطای محصول:",
                    product.get("name"),
                    str(error)
                )

                continue

    finally:

        save_sent(sent)

    print("پایان عملیات")
    print("تعداد محصولات ثبت‌شده:", len(sent))
