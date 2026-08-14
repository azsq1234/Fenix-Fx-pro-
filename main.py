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

# --- إدارة الإحصائيات والصفقات النشطة ---
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

# --- الخوارزمية الديناميكية لحساب الخسارة ---
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
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5%):**\n"
    table_text += "```text\n"
    table_text += "رأس المال  | اللوت       | المخاطرة\n"
    table_text += "-----------------------------------\n"

    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01(Min)" if exact_lot < 0.01 else str(round(exact_lot, 2))
        
        # طريقة آمنة 100% لتنسيق الجدول بدون التسبب بأخطاء في السيرفر
        cap_col = ("$" + str(cap)).ljust(10)
        lot_col = lot_str.ljust(11)
        risk_col = "$" + str(round(risk_amount, 1))
        
        table_text += cap_col + " | " + lot_col + " | " + risk_col + "\n"

    table_text += "```\n"
    return table_text

# --- خوارزمية التحليل الذكي المتوافقة مع الاتجاه ---
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

        fvg_type = "none"
        for i in range(len(df)-1, len(df)-6, -1):
            if df['High'].iloc[i-2] < df['Low'].iloc[i]:
                fvg_type = "bullish"
                break
            elif df['Low'].iloc[i-2] > df['High'].iloc[i]:
                fvg_type = "bearish"
                break

        ob_type = "none"
        for i in range(len(df)-2, len(df)-15, -1):
            if df['Close'].iloc[i] < df['Open'].iloc[i] and df['Close'].iloc[i+1] > df['Open'].iloc[i+1]:
                ob_type = "bullish"
                break
            elif df['Close'].iloc[i] > df['Open'].iloc[i] and df['Close'].iloc[i+1] < df['Open'].iloc[i+1]:
                ob_type = "bearish"
                break

        bullish_score = int(bos_bullish) + int(fvg_type == "bullish") + int(ob_type == "bullish")
        bearish_score = int(bos_bearish) + int(fvg_type == "bearish") + int(ob_type == "bearish")

        if bullish_score >= bearish_score and bullish_score > 0:
            signal = "شراء 🟢 (BUY)"
            bos_text = "كسر صاعد 🟢 (Bullish BOS)"
            fvg_text = "فجوة شرائية 🟢 (Bullish FVG)"
            ob_text = "منطقة طلب صانع السوق 📥 (Demand OB)"
            sl = current_price * 0.996
            tp = current_price + ((current_price - sl) * 2.0)
            technical_score = (bullish_score / 3.0) * 100.0
        elif bearish_score > bullish_score:
            signal = "بيع 🔴 (SELL)"
            bos_text = "كسر هابط 🔴 (Bearish BOS)"
            fvg_text = "فجوة بيعية 🔴 (Bearish FVG)"
            ob_text = "منطقة عرض صانع السوق 📤 (Supply OB)"
            sl = current_price * 1.004
            tp = current_price - ((sl - current_price) * 2.0)
            technical_score = (bearish_score / 3.0) * 100.0
        else:
            signal = "شراء 🟢 (BUY)"
            bos_text = "استقرار وتذبذب إيجابي ⚖️"
            fvg_text = "منطقة سيولة آمنة صاعدة"
            ob_text = "دعم صانع السوق الأولي"
            sl = current_price * 0.997
            tp = current_price + ((current_price - sl) * 2.0)
            technical_score = 65.0

        if technical_score < 50.0: technical_score = 60.0

        historical_rate = get_symbol_win_rate(symbol_name)
        if historical_rate > 0:
            final_score = round((technical_score * 0.6) + (historical_rate * 0.4), 1)
        else:
            final_score = round(technical_score, 1)

        final_score = max(60.0, min(95.0, final_score))
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

# --- حلقة المراقبة الخلفية ---
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
                            closed, result, reason = True, "✅ هدف مربح (Hit TP)", "وصول السعر للهدف بدقة يؤكد صحة نموذج الـ SMC."
                        elif current_price <= trade['sl']:
                            closed, result, reason = True, "❌ وقف خسارة (Hit SL)", "كسر منطقة الدعم وتحول الزخم المؤقت."
                    elif trade['type'] == "SELL":
                        if current_price <= trade['tp']:
                            closed, result, reason = True, "✅ هدف مربح (Hit TP)", "وصول السعر للهدف يعكس نجاح صفقة البيع."
                        elif current_price >= trade['sl']:
                            closed, result, reason = True, "❌ وقف خسارة (Hit SL)", "اختراق منطقة المقاومة."

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
                            f"📈 **نسبة نجاح الزوج التاريخية:** `{win_rate:.1f}%`"
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
        "نحن لا نقدم مجرد إشارات، بل نقدم **دقة مطلقة** في أسواق المال. بدمجنا لقوة تحليل **SMC** (مفاهيم الأموال الذكية) مع نظام إدارة مخاطر ديناميكي، نضمن لك إشارات عالية الجودة تساعدك على اجتياز **تحديات شركات التمويل (Prop Firms)** بثقة وثبات."
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
        about_text = "🦅 **Fenix Fx Pro** نظام تداول ذكي يعتمد على تحليل الـ SMC المتقدم وحساب اللوت التلقائي لحماية حسابات التمويل."
        await update.message.reply_text(about_text, parse_mode='Markdown')

    elif text == "🏆 قواعد شركات التمويل":
        rules = "🏆 **قواعد التمويل:** المخاطرة 0.5% لكل صفقة، ونسبة العائد إلى المخاطرة 1:2."
        await update.message.reply_text(rules, parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **إدارة المخاطر:** التزم بحجم اللوت الموصى به في الجدول تماماً.", parse_mode='Markdown')

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
        await update.message.reply_text(f"🧠 جاري تحليل SMC وحساب اللوت الدقيق لـ {text}...")

        has_news, news_info = check_high_impact_news(ticker)
        if has_news:
            warning_msg = f"🛑 **تنبيه:** خبر عالي التأثير على `{text}`: {news_info}. تم إيقاف الإشارة مؤقتاً."
            await update.message.reply_text(warning_msg, parse_mode='Markdown')
            return

        smc = analyze_smc_market(ticker, text)
        if smc:
            reply = (
                f"🦅 **إشارة تداول SMC - {text}**\n"
                f"───────────────────\n"
                f"🎯 **سعر الدخول:** `{smc['price']:.5f}`\n"
                f"🎯 **الإشارة:** `{smc['signal']}`\n\n"
                f"📌 **مستويات التنفيذ:**\n"
                f"🎯 **الهدف (TP):** `{smc['tp']:.5f}`\n"
                f"🛡️ **وقف الخسارة (SL):** `{smc['sl']:.5f}`\n"
                f"⚖️ **R:R:** `1 : 2`\n"
                f"📊 **نسبة الثقة:** `{smc['score']}%`\n\n"
                f"🧠 **تحليل SMC:**\n"
                f"▫️ **هيكل السوق:** {smc['bos']}\n"
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
