import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import requests
import yfinance as yf
import pandas_ta as ta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"

# --- تقسيم الأسواق والأزواج ---
FOREX_PAIRS = {
    "💶 EUR/USD": "EURUSD=X",
    "💷 GBP/USD": "GBPUSD=X",
    "💴 USD/JPY": "USDJPY=X",
    "🇨🇭 USD/CHF": "USDCHF=X",
    "🇨🇦 USD/CAD": "USDCAD=X",
    "🇦🇺 AUD/USD": "AUDUSD=X",
    "🇳🇿 NZD/USD": "NZDUSD=X",
    "🇪🇺 EUR/GBP": "EURGBP=X"
}

CRYPTO_PAIRS = {
    "₿ البيتكوين (BTC)": "BTC-USD",
    "💎 الإيثريوم (ETH)": "ETH-USD",
    "☀️ سولانا (SOL)": "SOL-USD",
    "🟡 باينانس (BNB)": "BNB-USD",
    "✕ ريبل (XRP)": "XRP-USD"
}

COMMODITIES_PAIRS = {
    "🥇 الذهب (Gold)": "GC=F",
    "🥈 الفضة (Silver)": "SI=F",
    "🛢 النفط (Oil)": "CL=F"
}

# دمج الأكواد للبحث
ALL_PAIRS_MAP = {**FOREX_PAIRS, **CRYPTO_PAIRS, **COMMODITIES_PAIRS}

MINUTES_BEFORE_NEWS = 30
MINUTES_AFTER_NEWS = 30

# --- سيرفر فحص الصحة لـ Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro Categorized Active!")

    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO)

# --- دالة فحص الأخبار (خاصة بالفوركس) ---
def check_high_impact_news(symbol):
    try:
        if "=X" not in symbol:
            return False, "" # استثناء الكريبتو والسلع من فلتر أخبار الفوركس
        clean_symbol = symbol.replace("=X", "")
        currency1, currency2 = clean_symbol[:3], clean_symbol[3:]

        url = "https://nodedata.forexfactory.com/forex/calendar/thisWeek.json"
        response = requests.get(url, timeout=5)
        if response.status_code != 200: return False, ""

        events = response.json()
        now_utc = datetime.now(timezone.utc)

        for event in events:
            if event.get("impact") == "High" and event.get("country") in [currency1, currency2]:
                event_time = datetime.fromisoformat(event.get("date")).astimezone(timezone.utc)
                diff_minutes = (event_time - now_utc).total_seconds() / 60.0
                if -MINUTES_AFTER_NEWS <= diff_minutes <= MINUTES_BEFORE_NEWS:
                    return True, f"{event.get('title')} ({event.get('country')})"

        return False, ""
    except Exception:
        return False, ""

# --- دالة جلب الأسعار المباشرة ---
def get_real_market_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="5d", interval="1h")
        if df.empty: return None
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['EMA20'] = ta.ema(df['Close'], length=20)
        data = df.iloc[-1]
        return {'price': data['Close'], 'rsi': data['RSI'], 'ema': data['EMA20']}
    except Exception:
        return None

# --- لوحات الأزرار (Keyboards) ---
def main_menu_keyboard():
    keyboard = [
        [KeyboardButton("📊 طلب إشارة تداول")],
        [KeyboardButton("ℹ️ حول البوت"), KeyboardButton("⚠️ إدارة المخاطر")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def categories_keyboard():
    keyboard = [
        [KeyboardButton("💱 أسواق الفوركس"), KeyboardButton("🪙 العملات الرقمية")],
        [KeyboardButton("🥇 المعادن والسلع")],
        [KeyboardButton("🔙 القائمة الرئيسية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def pairs_keyboard(pairs_dict):
    keys = list(pairs_dict.keys())
    keyboard = [keys[i:i+2] for i in range(0, len(keys), 2)]
    keyboard.append([KeyboardButton("🔙 العودة للتصنيفات")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- معالجة الأوامر والرسائل ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🦅 **مرحباً بك في Fenix Fx Pro** 🦅\n\n"
        "النظام المطور لتحليل الأسواق المالية بناءً على **Smart Money Concepts (SMC)** والسيولة.\n\n"
        "👇 **استخدم الأزرار بالأسفل للتنقل والحصول على الإشارات:**"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # 1️⃣ القوائم الرئيسية والتصنيفات
    if text in ["📊 طلب إشارة تداول", "🔙 العودة للتصنيفات"]:
        await update.message.reply_text("📂 **اختر تصنيف السوق المطلوب:**", reply_markup=categories_keyboard(), parse_mode='Markdown')

    elif text == "🔙 القائمة الرئيسية":
        await update.message.reply_text("🏠 **القائمة الرئيسية:**", reply_markup=main_menu_keyboard(), parse_mode='Markdown')

    elif text == "💱 أسواق الفوركس":
        await update.message.reply_text("💱 **اختر زوج الفوركس:**", reply_markup=pairs_keyboard(FOREX_PAIRS), parse_mode='Markdown')

    elif text == "🪙 العملات الرقمية":
        await update.message.reply_text("🪙 **اختر العملة الرقمية:**", reply_markup=pairs_keyboard(CRYPTO_PAIRS), parse_mode='Markdown')

    elif text == "🥇 المعادن والسلع":
        await update.message.reply_text("🥇 **اختر الرمز المطلوب:**", reply_markup=pairs_keyboard(COMMODITIES_PAIRS), parse_mode='Markdown')

    elif text == "ℹ️ حول البوت":
        await update.message.reply_text("🤖 **Fenix Fx Pro**: نظام ذكي يحلل أسواق الفوركس، الكريبتو، والسلع بناءً على المؤشرات الفنية وفلتر الأخبار.", parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **قواعد التداول:**\n1. لا تخاطر بأكثر من 1-2% لكل صفقة.\n2. التزم دائماً بوقف الخسارة (SL).", parse_mode='Markdown')

    # 2️⃣ معالجة اختيار أي زوج أو رمز
    elif text in ALL_PAIRS_MAP:
        ticker = ALL_PAIRS_MAP[text]
        await update.message.reply_text(f"🔍 جاري فحص البيانات لـ {text}...")

        # فحص الأخبار للفوركس
        has_news, news_info = check_high_impact_news(ticker)
        if has_news:
            warning_msg = (
                f"🛑 **تنبيه: التداول متوقف حالياً!**\n"
                f"───────────────────\n"
                f"⚠️ يوجد خبر عالي التأثير على `{text}`:\n"
                f"📌 **الخبر:** {news_info}\n\n"
                f"💡 *تم إيقاف التحليل حمايةً لرأس المال.*"
            )
            await update.message.reply_text(warning_msg, parse_mode='Markdown')
            return

        # جلب التحليل المباشر
        data = get_real_market_data(ticker)
        if data:
            trend = "صعود 🟢" if data['price'] > data['ema'] else "هبوط 🔴"
            reply = (
                f"📈 **تحليل {text} المباشر**\n"
                f"───────────────────\n"
                f"💵 **السعر الحالي:** `{data['price']:.4f}`\n"
                f"📊 **مؤشر RSI:** `{data['rsi']:.2f}`\n"
                f"💡 ** الاتجاه (EMA20):** {trend}\n"
                f"───────────────────\n"
                f"⚡ *بيانات حقيقية لحظية*"
            )
            await update.message.reply_text(reply, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ عذراً، لم أتمكن من جلب بيانات هذا الزوج حالياً.")
    else:
        await update.message.reply_text("الرجاء استخدام الأزرار المتاحة في الأسفل.")

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
