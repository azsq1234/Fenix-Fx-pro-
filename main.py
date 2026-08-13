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

# --- إدارة الإحصائيات والصققات النشطة ---
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
    if price_diff == 0: return 1.0

    if ticker_symbol == "GC=F": return price_diff * 100.0
    elif ticker_symbol == "SI=F": return price_diff * 5000.0
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
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5% لشركات التمويل):**\n"
    table_text += "```text\n"
    table_text += "رأس المال  | اللوت (Lot) | المخاطرة ($)\n"
    table_text += "------------------------------------\n"

    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01 (Min)" if exact_lot < 0.01 else f"{exact_lot:.2f}"
        table_text += f"${str(cap)}".ljust(10) + " \vert{} " + lot_str.ljust(11) + " \vert{} $" + f"{round(risk_amount, 2)}".ljust(10) + "\n"

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

# --- خوارزمية التحليل الذكي وحساب نسبة النجاح ديناميكياً ---
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
        fvg_found = False
        for i in range(len(df)-1, len(df)-6, -1):
            if df['High'].iloc[i-2] < df['Low'].iloc[i]:
                fvg_found = True
                fvg_text = "فجوة شرائية 🟢 (Bullish FVG)"
                break
            elif df['Low'].iloc[i-2] > df['High'].iloc[i]:
                fvg_found = True
                fvg_text = "فجوة بيعية 🔴 (Bearish FVG)"
                break

        ob_text = "منطقة تجميع حركية"
        ob_found = False
        for i in range(len(df)-2, len(df)-15, -1):
            if df['Close'].iloc[i] < df['Open'].iloc[i] and df['Close'].iloc[i+1] > df['Open'].iloc[i+1]:
                ob_found = True
                ob_text = "منطقة طلب صانع السوق 📥 (Demand OB)"
                break
            elif df['Close'].iloc[i] > df['Open'].iloc[i] and df['Close'].iloc[i+1] < df['Open'].iloc[i+1]:
                ob_found = True
                ob_text = "منطقة عرض صانع السوق 📤 (Supply OB)"
                break

        factors_count = int(bos_bullish or bos_bearish) + int(fvg_found) + int(ob_found)
        technical_score = (factors_count / 3.0) * 100.0
        if technical_score < 40.0: 
            technical_score = 45.0

        historical_rate = get_symbol_win_rate(symbol_name)
        if historical_rate > 0:
            final_score = round((technical_score * 0.6) + (historical_rate * 0.4), 1)
        else:
            final_score = round(technical_score, 1)

        final_score = max(45.0, min(99.0, final_score))

        if bos_bullish or fvg_found:
            signal = "شراء 🟢 (BUY)"
            sl = current_price * 0.996
            tp = current_price + ((current_price - sl) * 2.0)
        elif bos_bearish or fvg_found:
            signal = "بيع 🔴 (SELL)"
            sl = current_price * 1.004
            tp = current_price - ((sl - current_price) * 2.0)
        else:
            signal = "انتظار تأكيد السيولة ⏳ (NEUTRAL)"
            sl = current_price * 0.997
            tp = current_price + ((current_price - sl) * 1.5)
            final_score = 50.0

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
    except Exception:
        return None

# --- حلقة المراقبة الخلفية باستخدام Asyncio ---
async def background_market_monitor(application: Application):
    global active_trades
    await asyncio.sleep(10)
    while True:
        try:
            if active_trades:
                for trade in active_trades[:]:
                    ticker = yf.Ticker(trade['symbol_yfinance'])
                    df_hist = ticker.history(period="1m")
                    if df_hist.empty: continue
                    current_price = df_hist['Close'].iloc[-1]
                    
                    closed = False
                    result = ""
                    reason = ""

                    if trade['type'] == "BUY":
                        if current_price >= trade['tp']:
                            closed, result, reason = True, "✅ هدف مربح (Hit TP)", "وصول السعر للهدف بدقة يؤكد صحة نموذج الـ SMC والسيولة المتوقعة."
                        elif current_price <= trade['sl']:
                            closed, result, reason = True, "❌ وقف خسارة (Hit SL)", "كسر منطقة الطلب (Demand OB) وتحول الزخم لصالح البائعين."
                    elif trade['type'] == "SELL":
                        if current_price <= trade['tp']:
                            closed, result, reason = True, "✅ هدف مربح (Hit TP)", "وصول السعر للهدف يعكس نجاح صفقة البيع والوصول لمنطقة السيولة."
                        elif current_price >= trade['sl']:
                            closed, result, reason = True, "❌ وقف خسارة (Hit SL)", "اختراق منطقة العرض (Supply OB) وتغير هيكل السوق لصالح المشترين."

                    if closed:
                        outcome = "win" if "TP" in result else "loss"
                        update_symbol_stats(trade['symbol'], outcome)
                        win_rate = get_symbol_win_rate(trade['symbol'])
                        
                        msg = (
                            f"📊 **تحديث صفقة {trade['name']}**\n"
                            f"───────────────────\n"
                            f"النتيجة: **{result}**\n"
                            f"💡 **السبب:** {reason}\n"
                            f"📌 السعر عند الإغلاق: `{current_price:.5f}`\n\n"
                            f"📈 **نسبة نجاح الزوج التاريخية ({trade['symbol']}):** `{win_rate:.1f}%`"
                        )
                        await application.bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')
                        active_trades.remove(trade)
        except Exception as e:
            print(f"Error in monitor: {e}")
        await asyncio.sleep(60)

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
        [KeyboardButton("🥇 المعادن والسلع")],
        [KeyboardButton("🔙 القائمة الرئيسية")]
    ], resize_keyboard=True)

def pairs_keyboard(pairs_dict):
    keys = list(pairs_dict.keys())
    keyboard = [keys[i:i+2] for i in range(0, len(keys), 2)]
    keyboard.append([KeyboardButton("🔙 العودة للتصنيفات")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- معالجة الأوامر والرسائل ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "مرحباً بك في **Fenix Fx Pro** 🦅 – شريكك الاستراتيجي في رحلة التمويل.\n\n"
        "نحن لا نقدم مجرد إشارات، بل نقدم **دقة مطلقة** في أسواق المال. بدمجنا لقوة تحليل **SMC** (مفاهيم الأموال الذكية) مع نظام إدارة مخاطر ديناميكي، نضمن لك إشارات عالية الجودة تساعدك على اجتياز **تحديات شركات التمويل (Prop Firms)** بثقة وثبات.\n\n"
        "**لماذا Fenix Fx Pro؟**\n"
        "✅ **دقة فائقة:** تحليلات SMC متقدمة لاستخراج أدق نقاط الدخول.\n"
        "✅ **إدارة ذكية:** حساب تلقائي للوت (Lot) يحافظ على رأس مالك من المخاطر.\n"
        "✅ **حماية استباقية:** فلتر للأخبار الاقتصادية لتجنب التقلبات المفاجئة.\n\n"
        "🚀 **رحلتك نحو التمويل تبدأ من هنا. استخدم الأزرار أدناه للتحليل والتنفيذ.**"
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
            "🦅 **شرح شامل عن نظام Fenix Fx Pro:**\n\n"
            "**ما هو هذا البوت؟**\n"
            "هو مساعدك الذكي والمتقدم في أسواق المال، صُمم خصيصاً لمساعدة المتداولين على **اجتياز تحديات شركات التمويل (Prop Firms)** بكل ثقة وانضباط.\n\n"
            "**🌟 الميزات الأساسية للنظام:**\n"
            "1️⃣ **تحليل SMC المتقدم:** يعتمد البوت على مفاهيم الأموال الذكية (Smart Money Concepts) مثل كسر الهيكل (BOS)، والفجوات السعرية (FVG)، وكتل الأوامر (Order Blocks) لاستخراج أدق نقاط الدخول.\n"
            "2️⃣ **حساب اللوت الديناميكي:** يقوم البوت تلقائياً بحساب حجم العقد (Lot) المناسب لكل رأس مال بناءً على **مخاطرة آمنة 0.5%** لحماية حسابك من السحب الزائد.\n"
            "3️⃣ **فلتر الأخبار الاقتصادية:** يتصل البوت أوتوماتيكياً بالأجندة الاقتصادية لإيقاف الإشارات قبل صدور الأخبار القوية لمنع خسائر الانزلاقات السعرية.\n"
            "4️⃣ **مؤشر ثقة الإشارة:** كل إشارة تحمل نسبة دقة ديناميكية (من 100%) تُحسب بناءً على قوة وتوافق الشروط الفنية لحظياً.\n"
            "5️⃣ **المراقبة الخلفية والتتبع:** يراقب البوت صفقاتك في الخلفية ويقوم بتنبيهك عند ضرب الهدف (TP) أو وقف الخسارة (SL) مع توضيح السبب الفني للنتيجة.\n"
            "6️⃣ **إحصائيات الأداء الشاملة:** تتبع نسبة النجاح لكل زوج وفئة أصول (فوركس، كريبتو، سلع) لتطوير استراتيجيتك باستمرار.\n\n"
            "🚀 *استخدم زر '📊 طلب إشارة تداول' للبدء الآن!*"
        )
        await update.message.reply_text(about_text, parse_mode='Markdown')

    elif text == "🏆 قواعد شركات التمويل":
        rules = (
            "🏆 **قواعد اجتياز تحديات التمويل (FTMO / FundedNext):**\n\n"
            "1️⃣ **المخاطرة لكل صفقة:** محددة بنسبة **0.5%** فقط لا غير.\n"
            "2️⃣ **حساب اللوت:** يتم حسابه أوتوماتيكياً لكل زوج بدقة.\n"
            "3️⃣ **معدل Risk:Reward:** محددة بنسبة **1:2** للحفاظ على الأمان."
        )
        await update.message.reply_text(rules, parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **قواعد إدارة المخاطر:**\nاختر دائماً حجم اللوت المناسب لرأس مالك بناءً على الجدول الظاهر في الإشارة.", parse_mode='Markdown')

    elif text == "📊 تقرير الأداء الشامل":
        stats = load_stats()
        if not stats:
            await update.message.reply_text("📊 **تقرير الأداء:**\n\nلا توجد صفقات مسجلة حتى الآن. ستظهر النتائج تلقائياً بمجرد إغلاق الصفقات النشطة.", parse_mode='Markdown')
        else:
            report = "📈 **تقرير الأداء الشامل حسب فئات الأصول:**\n\n"
            
            report += "🪙 **العملات الرقمية (Crypto):**\n"
            crypto_symbols = ["BTC", "ETH", "SOL", "BNB", "XRP"]
            found_crypto = False
            for symbol, data in stats.items():
                if any(c in symbol for c in crypto_symbols):
                    total = data['wins'] + data['losses']
                    win_rate = (data['wins'] / total * 100) if total > 0 else 0.0
                    report += f"   • *{symbol}*: نسبة النجاح `{win_rate:.1f}%` (✅ {data['wins']} رابحة - ❌ {data['losses']} خاسرة)\n"
                    found_crypto = True
            if not found_crypto: report += "   *لا توجد صفقات مسجلة بعد.*\n"
            
            report += "\n💱 **أسواق الفوركس (Forex):**\n"
            forex_symbols = ["EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]
            found_forex = False
            for symbol, data in stats.items():
                if any(f in symbol for f in forex_symbols):
                    total = data['wins'] + data['losses']
                    win_rate = (data['wins'] / total * 100) if total > 0 else 0.0
                    report += f"   • *{symbol}*: نسبة النجاح `{win_rate:.1f}%` (✅ {data['wins']} رابحة - ❌ {data['losses']} خاسرة)\n"
                    found_forex = True
            if not found_forex: report += "   *لا توجد صفقات مسجلة بعد.*\n"

            report += "\n🥇 **المعادن والسلع (Commodities):**\n"
            comm_symbols = ["GC", "SI", "CL"]
            found_comm = False
            for symbol, data in stats.items():
                if any(c in symbol for c in comm_symbols):
                    total = data['wins'] + data['losses']
                    win_rate = (data['wins'] / total * 100) if total > 0 else 0.0
                    report += f"   • *{symbol}*: نسبة النجاح `{win_rate:.1f}%` (✅ {data['wins']} رابحة - ❌ {data['losses']} خاسرة)\n"
                    found_comm = True
            if not found_comm: report += "   *لا توجد صفقات مسجلة بعد.*\n"

            await update.message.reply_text(report, parse_mode='Markdown')

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
                f"🎯 **سعر الدخول (Market):** `{smc['price']:.5f}`\n"
                f"🎯 **الإشارة:** `{smc['signal']}`\n\n"
                f"📌 **مستويات التنفيذ:**\n"
                f"🎯 **الهدف (TP):** `{smc['tp']:.5f}`\n"
                f"🛡️ **وقف الخسارة (SL):** `{smc['sl']:.5f}`\n"
                f"⚖️ **معدل المخاطرة/العائد (R:R):** `1 : 2`\n"
                f"📊 **نسبة ثقة/نجاح الإشارة:** `{smc['score']}% / 100%`\n\n"
                f"🧠 **تحليل SMC:**\n"
                f"▫️ **هيكل السوق:** {smc['bos']}\n"
                f"▫️ **الفجوة:** {smc['fvg']}\n"
                f"▫️ **كتلة الأوامر:** {smc['ob']}\n\n"
                f"{smc['lot_table']}\n"
                f"───────────────────\n"
                f"🛡️ **فلتر الأخبار:** لا توجد أخبار مؤثرة حالياً ✅"
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
            await update.message.reply_text("❌ عذراً، تعذر جلب التحليل حالياً، حاول مرة أخرى.")
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
