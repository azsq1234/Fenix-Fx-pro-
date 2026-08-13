import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import requests
import yfinance as yf
import pandas as pd
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
    "🇳ℤ NZD/USD": "NZDUSD=X",
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

ALL_PAIRS_MAP = {**FOREX_PAIRS, **CRYPTO_PAIRS, **COMMODITIES_PAIRS}

MINUTES_BEFORE_NEWS = 30
MINUTES_AFTER_NEWS = 30

# --- سيرفر فحص الصحة لـ Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro Active!")

    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO)

# --- فلتر الأخبار عالية التأثير ---
def check_high_impact_news(symbol):
    try:
        if "=X" not in symbol:
            return False, ""
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

# --- الخوارزمية الديناميكية لحساب الخسارة لكل عقد قياسي (1.00 Lot) ---
def calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price):
    price_diff = abs(entry_price - sl_price)
    if price_diff == 0:
        return 1.0

    if ticker_symbol == "GC=F":      # الذهب
        return price_diff * 100.0
    elif ticker_symbol == "SI=F":    # الفضة
        return price_diff * 5000.0
    elif ticker_symbol == "CL=F":    # النفط
        return price_diff * 1000.0
    elif "-USD" in ticker_symbol:    # الكريبتو
        return price_diff * 1.0
    elif "=X" in ticker_symbol:      # الفوركس
        clean_symbol = ticker_symbol.replace("=X", "")
        base_curr = clean_symbol[:3]
        quote_curr = clean_symbol[3:]

        if quote_curr == "USD":
            return price_diff * 100000.0
        elif base_curr == "USD":
            return (price_diff * 100000.0) / entry_price
        elif quote_curr == "GBP":
            return price_diff * 100000.0 * 1.28
        else:
            return price_diff * 100000.0

    return price_diff * 100.0

# --- دالة توليد جدول اللوت لشركات التمويل ---
def generate_prop_firm_lot_table(entry_price, sl_price, ticker_symbol):
    loss_per_lot = calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price)
    if loss_per_lot == 0:
        loss_per_lot = 1.0

    capitals = [100, 500, 1000, 5000, 10000, 25000, 50000, 100000]
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5% لشركات التمويل):**\n"
    table_text += "```text\n"
    table_text += "رأس المال  | اللوت (Lot) | المخاطرة ($)\n"
    table_text += "------------------------------------\n"

    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot

        if exact_lot < 0.01:
            lot_str = "0.01 (Min)"
        else:
            lot_str = f"{exact_lot:.2f}"

        c_str = "$" + str(cap)
        r_str = "$" + str(round(risk_amount, 2))
        table_text += c_str.ljust(10) + " | " + lot_str.ljust(11) + " | " + r_str + "\n"

    table_text += "```\n"

    if "JPY" in ticker_symbol:
        pips = abs(entry_price - sl_price) / 0.01
        p_type = "Pips"
    elif "=X" in ticker_symbol:
        pips = abs(entry_price - sl_price) / 0.0001
        p_type = "Pips"
    else:
        pips = abs(entry_price - sl_price)
        p_type = "دولار/نقطة"

    table_text += f"📌 **مسافة الستوب لوز:** `{pips:.1f} {p_type}`"
    return table_text

# --- خوارزمية التحليل الذكي بناءً على SMC ---
def analyze_smc_market(ticker_symbol, symbol_name):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="10d", interval="1h")
        if len(df) < 30: return None

        current_price = df['Close'].iloc[-1]
        
        recent_high = df['High'].iloc[-20:-1].max()
        recent_low = df['Low'].iloc[-20:-1].min()

        bos_bullish = current_price > recent_high
        bos_bearish = current_price < recent_low

        bos_text = "كسر صاعد 🟢 (Bullish BOS)" if bos_bullish else ("كسر هابط 🔴 (Bearish BOS)" if bos_bearish else "تذبذب / إعادة اختبار ⚖️")

        fvg_text = "لا توجد فجوة قريبة"
        fvg_bullish = False
        fvg_bearish = False

        for i in range(len(df)-1, len(df)-6, -1):
            if df['High'].iloc[i-2] < df['Low'].iloc[i]:
                fvg_bullish = True
                fvg_text = "فجوة شرائية 🟢 (Bullish FVG)"
                break
            elif df['Low'].iloc[i-2] > df['High'].iloc[i]:
                fvg_bearish = True
                fvg_text = "فجوة بيعية 🔴 (Bearish FVG)"
                break

        ob_text = "منطقة تجميع حركية"
        for i in range(len(df)-2, len(df)-15, -1):
            if df['Close'].iloc[i] < df['Open'].iloc[i] and df['Close'].iloc[i+1] > df['Open'].iloc[i+1]:
                ob_text = "منطقة طلب صانع السوق 📥 (Demand OB)"
                break
            elif df['Close'].iloc[i] > df['Open'].iloc[i] and df['Close'].iloc[i+1] < df['Open'].iloc[i+1]:
                ob_text = "منطقة عرض صانع السوق 📤 (Supply OB)"
                break

        if bos_bullish or fvg_bullish:
            signal = "شراء 🟢 (BUY)"
            sl = current_price * 0.996
            tp = current_price + ((current_price - sl) * 2.0)
        elif bos_bearish or fvg_bearish:
            signal = "بيع 🔴 (SELL)"
            sl = current_price * 1.004
            tp = current_price - ((sl - current_price) * 2.0)
        else:
            signal = "انتظار تأكيد السيولة ⏳ (NEUTRAL)"
            sl = current_price * 0.997
            tp = current_price + ((current_price - sl) * 1.5)

        lot_table = generate_prop_firm_lot_table(current_price, sl, ticker_symbol)

        return {
            'price': current_price,
            'signal': signal,
            'bos': bos_text,
            'fvg': fvg_text,
            'ob': ob_text,
            'sl': sl,
            'tp': tp,
            'lot_table': lot_table
        }
    except Exception:
        return None

# --- اللوحات والأزرار ---
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 طلب إشارة تداول"), KeyboardButton("🏆 قواعد شركات التمويل")],
        [KeyboardButton("ℹ️ حول البوت"), KeyboardButton("⚠️ إدارة المخاطر")]
    ], resize_keyboard=True)

def categories_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💱 أسواق الفوركس"), KeyboardButton("🪙 العملات الرقمية")],
        [KeyboardButton("🥇 المعادن والسلع")],
        [KeyboardButton("🔙 القائمة الرئيسية")]
    ], resize_keyboard=True)

def pairs_keyboard(pairs_dict):
    keys = list(pairs_dict.keys())
    keyboard = [keys[i:i+2] for i in range(0, len(keys), 2)]
    keyboard.append([KeyboardButton("🔙 العودة للتصنيفات")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- معالجة الرسائل والأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🦅 **مرحباً بك في Fenix Fx Pro - Prop Firm Edition** 🦅\n\n"
        "النظام المطور لتوليد الإشارات واجتياز **تحديات شركات التمويل** مع حساب اللوت المباشر بدون أخطاء.\n\n"
        "👇 استخدم الأزرار بالأسفل للتنقل:"
    )
    await update.message.reply_text(welcome, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ["📊 طلب إشارة تداول", "🔙 العودة للتصنيفات"]:
        await update.message.reply_text("📂 **اختر قسم السوق المطلوب:**", reply_markup=categories_keyboard(), parse_mode='Markdown')

    elif text == "🔙 القائمة الرئيسية":
        await update.message.reply_text("🏠 **القائمة الرئيسية:**", reply_markup=main_menu_keyboard(), parse_mode='Markdown')

    elif text == "💱 أسواق الفوركس":
        await update.message.reply_text("💱 **اختر زوج الفوركس:**", reply_markup=pairs_keyboard(FOREX_PAIRS), parse_mode='Markdown')

    elif text == "🪙 العملات الرقمية":
        await update.message.reply_text("🪙 **اختر العملة الرقمية:**", reply_markup=pairs_keyboard(CRYPTO_PAIRS), parse_mode='Markdown')

    elif text == "🥇 المعادن والسلع":
        await update.message.reply_text("🥇 **اختر الرمز المطلوب:**", reply_markup=pairs_keyboard(COMMODITIES_PAIRS), parse_mode='Markdown')

    elif text == "🏆 قواعد شركات التمويل":
        rules = (
            "🏆 **استراتيجية اجتياز تحديات شركات التمويل (FTMO / FundedNext):**\n\n"
            "1️⃣ **المخاطرة لكل صفقة:** محددة بنسبة **0.5%** فقط لا غير.\n"
            "2️⃣ **حساب اللوت:** يتم حسابه أوتوماتيكياً حسب كل زوج وضبط المواصفات بدقة متناهية.\n"
            "3️⃣ **معدل Risk:Reward:** صفقات SMC محددة بنسبة **1:2** أو أكثر للحصول على أقصى عائد."
        )
        await update.message.reply_text(rules, parse_mode='Markdown')

    elif text == "ℹ️ حول البوت":
        await update.message.reply_text("🤖 **Fenix Fx Pro**: بوت تداول ذكي يربط تحليل SMC بحاسبة لوت ديناميكية دقيقة جداً لكل أداة مالية.", parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **قواعد إدارة المخاطر:**\nاختر دائماً حجم اللوت المناسب لرأس مالك المقابل لرسالة الإشارة بالضبط.", parse_mode='Markdown')

    elif text in ALL_PAIRS_MAP:
        ticker = ALL_PAIRS_MAP[text]
        await update.message.reply_text(f"🧠 جاري تحليل SMC وحساب اللوت الدقيق لـ {text}...")

        has_news, news_info = check_high_impact_news(ticker)
        if has_news:
            warning_msg = (
                f"🛑 **تنبيه: التداول متوقف حالياً!**\n"
                f"───────────────────\n"
                f"⚠️ خبر عالي التأثير قادم/حالي على `{text}`:\n"
                f"📌 **الخبر:** {news_info}\n\n"
                f"💡 *تم إيقاف الإشارة حمايةً لحساب التمويل من الانزلاقات السعرية.*"
            )
            await update.message.reply_text(warning_msg, parse_mode='Markdown')
            return

        smc = analyze_smc_market(ticker, text)
        if smc:
            reply = (
                f"🦅 **إشارة تداول SMC - {text}**\n"
                f"───────────────────\n"
                f"💵 **السعر الحالي:** `{smc['price']:.5f}`\n"
                f"🎯 **الإشارة:** `{smc['signal']}`\n\n"
                f"📌 **مستويات التنفيذ:**\n"
                f"🎯 **الهدف (TP):** `{smc['tp']:.5f}`\n"
                f"🛡️ **وقف الخسارة (SL):** `{smc['sl']:.5f}`\n"
                f"⚖️ **معدل المخاطرة/العائد (R:R):** `1 : 2`\n\n"
                f"🧠 **تحليل SMC:**\n"
                f"▫️ **هيكل السوق:** {smc['bos']}\n"
                f"▫️ **الفجوة:** {smc['fvg']}\n"
                f"▫️ **كتلة الأوامر:** {smc['ob']}\n\n"
                f"{smc['lot_table']}\n"
                f"───────────────────\n"
                f"🛡️ **فلتر الأخبار:** لا توجد أخبار مؤثثة حالياً ✅"
            )
            await update.message.reply_text(reply, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ عذراً، تعذر جلب التحليل حالياً، حاول مرة أخرى.")
    else:
        await update.message.reply_text("استخدم الأزرار في الأسفل للتنقل.")

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
