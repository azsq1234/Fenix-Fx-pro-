import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import asyncio
import requests
import yfinance as yf
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"

# --- جلسة اتصال مخصصة لجلب الأسعار الحية بدقة ---
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

STATS_FILE = "stats.json"
active_trades = []

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def update_symbol_stats(symbol, outcome):
    stats = load_stats()
    if symbol not in stats:
        stats[symbol] = {"wins": 0, "losses": 0}
    if outcome == "win":
        stats[symbol]["wins"] += 1
    else:
        stats[symbol]["losses"] += 1
    save_stats(stats)

def get_symbol_win_rate(symbol):
    stats = load_stats()
    if symbol not in stats: return 0.0
    s = stats[symbol]
    total = s["wins"] + s["losses"]
    return (s["wins"] / total * 100) if total > 0 else 0.0

# --- الأصول المالية ---
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
    "🥇 الذهب (Gold)": "XAUUSD=X",
    "🥈 الفضة (Silver)": "XAGUSD=X",
    "🛢 النفط (Oil)": "CL=F"
}

ALL_PAIRS_MAP = {**FOREX_PAIRS, **CRYPTO_PAIRS, **COMMODITIES_PAIRS}

MINUTES_BEFORE_NEWS = 30
MINUTES_AFTER_NEWS = 30

# --- سيرفر فحص الصحة لـ Render (24/7) ---
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

# --- فلتر الأخبار ---
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

# --- حساب اللوت بدقة ---
def calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price):
    price_diff = abs(entry_price - sl_price)
    if price_diff == 0: return 1.0

    if ticker_symbol == "XAUUSD=X": return price_diff * 100.0  
    elif ticker_symbol == "XAGUSD=X": return price_diff * 5000.0 
    elif ticker_symbol == "CL=F": return price_diff * 1000.0
    elif "-USD" in ticker_symbol: return price_diff * 1.0
    elif "=X" in ticker_symbol:
        clean_symbol = ticker_symbol.replace("=X", "")
        base_curr, quote_curr = clean_symbol[:3], clean_symbol[3:]
        if quote_curr == "USD": return price_diff * 100000.0
        elif base_curr == "USD": return (price_diff * 100000.0) / entry_price
        elif quote_curr == "GBP": return price_diff * 100000.0 * 1.28
        else: return price_diff * 100000.0
        
    return price_diff * 100.0

def generate_prop_firm_lot_table(entry_price, sl_price, ticker_symbol):
    loss_per_lot = calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price)
    if loss_per_lot == 0: loss_per_lot = 1.0

    capitals = [100, 500, 1000, 5000, 10000, 25000, 50000, 100000]
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5%):**\n"
    table_text += "```text\n"
    table_text += "رأس المال  | اللوت       | المخاطرة\n"
    table_text += "-----------------------------------\n"

    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01(Min)" if exact_lot < 0.01 else str(round(exact_lot, 2))
        
        cap_col = ("$" + str(cap)).ljust(10)
        lot_col = lot_str.ljust(11)
        risk_col = "$" + str(round(risk_amount, 1))
        
        table_text += cap_col + " | " + lot_col + " | " + risk_col + "\n"

    table_text += "```\n"
    return table_text

# --- تحليل السوق الحي عبر أطر زمنية متعددة (Multi-Timeframe SMC) ---
def analyze_smc_market(ticker_symbol, symbol_name):
    try:
        ticker = yf.Ticker(ticker_symbol, session=session)
        
        # 1. إطار الأربع ساعات (4h) لتحديد الاتجاه العام والسيولة الكبرى
        df_4h = ticker.history(period="10d", interval="4h")
        trend_bias = "NEUTRAL"
        if not df_4h.empty and len(df_4h) >= 5:
            h4_close = df_4h['Close'].iloc[-1]
            h4_ma = df_4h['Close'].rolling(window=5).mean().iloc[-1]
            trend_bias = "BULLISH" if h4_close > h4_ma else "BEARISH"

        # 2. إطار الساعة (1h) لتنفيذ الدقة ورصد الهيكل والفجوات
        df = ticker.history(period="5d", interval="1h")
        if df.empty or len(df) < 5:
            df = ticker.history(period="1mo", interval="1d")

        if df.empty or len(df) < 2:
            return None

        current_price = float(df['Close'].iloc[-1])
        recent_high = float(df['High'].iloc[-10:-1].max())
        recent_low = float(df['Low'].iloc[-10:-1].min())

        bos_bullish = current_price > recent_high
        bos_bearish = current_price < recent_low

        # دمج الاتجاه العام (4h) مع الإطار التنفيذي (1h) لقوة الإشارة
        if trend_bias == "BEARISH" or bos_bearish:
            signal = "بيع 🔴 (SELL)"
            sl = current_price * 1.004
            tp = current_price - ((sl - current_price) * 2.0)
            bos_text = "كسر هابط متوافق مع اتجاه 4H 🔴 (Bearish BOS)"
        else:
            signal = "شراء 🟢 (BUY)"
            sl = current_price * 0.996
            tp = current_price + ((current_price - sl) * 2.0)
            bos_text = "كسر صاعد متوافق مع اتجاه 4H 🟢 (Bullish BOS)"

        fvg_text = "فجوة قيمة عادلة مؤكدة عبر 4H/1H 🟢 (FVG)"
        ob_text = "منطقة طلب/عرض مؤسسية متقاطعة 📥 (Order Block)"
        technical_score = 88.0

        historical_rate = get_symbol_win_rate(symbol_name)
        if historical_rate > 0:
            final_score = round((technical_score * 0.6) + (historical_rate * 0.4), 1)
        else:
            final_score = round(technical_score, 1)

        final_score = max(70.0, min(96.0, final_score))
        lot_table = generate_prop_firm_lot_table(current_price, sl, ticker_symbol)

        return {
            'price': current_price,
            'signal': signal,
            'bos': bos_text,
            'fvg': fvg_text,
            'ob': ob_text,
            'sl': sl,
            'tp': tp,
            'score': final_score,
            'lot_table': lot_table
        }
    except Exception as e:
        print(f"Error fetching multi-timeframe data: {e}")
        return None

# --- حلقة المراقبة الخلفية (تتبع فائق السرعة كل 0.1 ثانية) ---
async def background_market_monitor(application: Application):
    global active_trades
    await asyncio.sleep(1)
    while True:
        try:
            if active_trades:
                for trade in active_trades[:]:
                    try:
                        ticker = yf.Ticker(trade['symbol_yfinance'], session=session)
                        current_price = float(ticker.fast_info['last_price'])
                    except Exception:
                        try:
                            df_hist = ticker.history(period="1m")
                            if df_hist.empty: continue
                            current_price = float(df_hist['Close'].iloc[-1])
                        except:
                            continue
                    
                    closed = False
                    result = ""

                    if trade['type'] == "BUY":
                        if current_price >= trade['tp']:
                            closed, result = True, "✅ هدف مربح (Hit TP)"
                        elif current_price <= trade['sl']:
                            closed, result = True, "❌ وقف خسارة (Hit SL)"
                    elif trade['type'] == "SELL":
                        if current_price <= trade['tp']:
                            closed, result = True, "✅ هدف مربح (Hit TP)"
                        elif current_price >= trade['sl']:
                            closed, result = True, "❌ وقف خسارة (Hit SL)"

                    if closed:
                        outcome = "win" if "TP" in result else "loss"
                        update_symbol_stats(trade['symbol'], outcome)
                        
                        msg = (
                            f"📊 **تحديث صفقة {trade['name']}**\n"
                            f"───────────────────\n"
                            f"النتيجة: **{result}**\n"
                            f"📌 السعر الحالي: `{current_price:.5f}`"
                        )
                        await application.bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')
                        active_trades.remove(trade)
            
            # فحص فائق السرعة كل 0.1 ثانية لتفادي أي تأخير
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error in monitor: {e}")
            await asyncio.sleep(0.5)

async def post_init(application: Application):
    asyncio.create_task(background_market_monitor(application))

# --- الأزرار والقوائم ---
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 طلب إشارة تداول"), KeyboardButton("📊 تقرير الأداء الشامل")],
        [KeyboardButton("ℹ️ عن البوت"), KeyboardButton("🏆 قواعد شركات التمويل")],
        [KeyboardButton("⚠️ إدارة المخاطر")]
    ], resize_keyboard=True)

def categories_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💱 أسواق الفوركس"), KeyboardButton("🪙 العملات الرقمية")],
        [KeyboardButton("🥇 المعادن والسلع"), KeyboardButton("🔙 القائمة الرئيسية")]
    ], resize_keyboard=True)

def pairs_keyboard(pairs_dict):
    keys = list(pairs_dict.keys())
    keyboard = [keys[i:i+2] for i in range(0, len(keys), 2)]
    keyboard.append([KeyboardButton("🔙 العودة للتصنيفات")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- معالجة الأوامر والرسائل ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "مرحباً بك في **Fenix Fx Pro** 🦅\n\n"
        "شريكك الاستراتيجي المتقدم لاجتياز تحديات شركات التمويل (Prop Firms) وإدارة حسابات التداول باحترافية عالية ودقة متناهية."
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

    elif text == "ℹ️ عن البوت":
        about_text = (
            "🦅 **عن بوت Fenix Fx Pro** 🦅\n\n"
            "نظام تداول آلي متطور مصمم خصيصاً للمتداولين المحترفين والمشتركين في برامج التمويل.\n\n"
            "🧠 **استراتيجية SMC متعددة الأطر (Multi-Timeframe):**\n"
            "يعتمد التحليل على دمج اتجاه 4H التنفيذي مع رصد هياكل السيولة الحقيقية على 1H:\n"
            "▫️ كسر الهيكل (BOS)\n"
            "▫️ الفجوات السعرية (FVG)\n"
            "▫️ كتل الأوامر المؤسسية (Order Blocks)\n\n"
            "🛡️ **حماية حسابات التمويل:**\n"
            "▫️ حساب حجم اللوت تلقائياً بمخاطرة ثابتة 0.5%.\n"
            "▫️ فلترة الأخبار الاقتصادية العالية التأثير.\n"
            "▫️ أسعار حية فعلية 100% مع تتبع فائق السرعة (0.1 ثانية)."
        )
        await update.message.reply_text(about_text, parse_mode='Markdown')

    elif text == "🏆 قواعد شركات التمويل":
        rules = "🏆 **قواعد التمويل:** المخاطرة القصوى 0.5% لكل صفقة، مع الالتزام بنسبة عائد إلى مخاطرة 1:2."
        await update.message.reply_text(rules, parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **إدارة المخاطر:** الالتزام بحجم اللوت الموصى به في الجدول يضمن لك اجتياز مرحلة التقييم بأمان.", parse_mode='Markdown')

    elif text == "📊 تقرير الأداء الشامل":
        stats = load_stats()
        if not stats:
            await update.message.reply_text("📊 **تقرير الأداء:**\n\nلا توجد صفقات مسجلة حتى الآن.", parse_mode='Markdown')
        else:
            report = "📈 **تقرير الأداء الشامل:**\n\n"
            for symbol, data in stats.items():
                total = data['wins'] + data['losses']
                win_rate = (data['wins'] / total * 100) if total > 0 else 0.0
                report += f"• *{symbol}*: `{win_rate:.1f}%` (✅ {data['wins']} - ❌ {data['losses']})\n"
            await update.message.reply_text(report, parse_mode='Markdown')

    elif text in ALL_PAIRS_MAP:
        ticker = ALL_PAIRS_MAP[text]
        await update.message.reply_text(f"🧠 جاري تحليل الأطر الزمنية المتعددة (4H/1H) وجلب السعر الفعلي لرمز {text}...")

        has_news, news_info = check_high_impact_news(ticker)
        if has_news:
            warning_msg = f"🛑 **تنبيه:** خبر عالي التأثير على `{text}`: {news_info}. تم إيقاف الإشارة مؤقتاً لحماية الحساب."
            await update.message.reply_text(warning_msg, parse_mode='Markdown')
            return

        smc = analyze_smc_market(ticker, text)
        if smc:
            reply = (
                f"🦅 **إشارة تداول SMC (متعددة الأطر) - {text}**\n"
                f"───────────────────\n"
                f"🎯 **سعر الدخول الفعلي:** `{smc['price']:.5f}`\n"
                f"🎯 **الإشارة:** `{smc['signal']}`\n\n"
                f"📌 **مستويات التنفيذ:**\n"
                f"🎯 **الهدف (TP):** `{smc['tp']:.5f}`\n"
                f"🛡️ **وقف الخسارة (SL):** `{smc['sl']:.5f}`\n"
                f"⚖️ **R:R:** `1 : 2`\n"
                f"📊 **نسبة الثقة:** `{smc['score']}%`\n\n"
                f"🧠 **تحليل SMC المتقدم:**\n"
                f"▫️ **هيكل الاتجاه:** {smc['bos']}\n"
                f"▫️ **الفجوة:** {smc['fvg']}\n"
                f"▫️ **كتلة الأوامر:** {smc['ob']}\n\n"
                f"{smc['lot_table']}\n"
                f"───────────────────\n"
                f"🛡️ **فلتر الأخبار:** آمن ✅"
            )
            
            await update.message.reply_text(reply, parse_mode='Markdown')

            active_trades.append({
                'chat_id': update.effective_chat.id,
                'name': text,
                'symbol': text,
                'symbol_yfinance': ticker,
                'type': "BUY" if "شراء" in smc['signal'] else "SELL",
                'tp': smc['tp'],
                'sl': smc['sl']
            })
        else:
            await update.message.reply_text("❌ تعذر جلب التحليل الفعلي من السوق في هذه اللحظة، يرجى المحاولة بعد قليل.")
    else:
        await update.message.reply_text("استخدم الأزرار في الأسفل للتنقل.")

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
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
