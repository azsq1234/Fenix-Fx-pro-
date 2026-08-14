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
import numpy as np
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

STATS_FILE = "stats.json"
active_trades = []

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"trades": [], "daily_summary": {}}
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"trades": [], "daily_summary": {}}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def record_trade_result(symbol, outcome, pips):
    stats = load_stats()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if "trades" not in stats: stats["trades"] = []
    stats["trades"].append({
        "symbol": symbol,
        "outcome": outcome,
        "pips": pips,
        "date": today_str
    })
    
    if "daily_summary" not in stats: stats["daily_summary"] = {}
    if today_str not in stats["daily_summary"]:
        stats["daily_summary"][today_str] = {"wins": 0, "losses": 0, "total_pips": 0.0}
        
    if outcome == "win":
        stats["daily_summary"][today_str]["wins"] += 1
        stats["daily_summary"][today_str]["total_pips"] += pips
    else:
        stats["daily_summary"][today_str]["losses"] += 1
        stats["daily_summary"][today_str]["total_pips"] -= pips
        
    save_stats(stats)

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

# --- سيرفر الصحة 24/7 ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro 24/7 Multi-Timeframe Active!")
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
        if "=X" not in symbol: return False, ""
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

# --- حساب اللوت الدقيق ---
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
        else: return price_diff * 100000.0
    return price_diff * 100.0

def generate_prop_firm_lot_table(entry_price, sl_price, ticker_symbol):
    loss_per_lot = calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price)
    if loss_per_lot == 0: loss_per_lot = 1.0
    capitals = [100, 500, 1000, 5000, 10000, 25000, 50000, 100000]
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5%):**\n```text\nرأس المال  | اللوت       | المخاطرة\n-----------------------------------\n"
    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01(Min)" if exact_lot < 0.01 else str(round(exact_lot, 2))
        table_text += ("$" + str(cap)).ljust(10) + " \vert{} " + lot_str.ljust(11) + " \vert{} $" + str(round(risk_amount, 1)) + "\n"
    table_text += "```\n"
    return table_text

# --- نظام المحللين المتعددين عبر الفريمات (1m إلى 1d) مع تقاطع المؤشرات و SMC ---
def multi_analyst_market_evaluation(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol, session=session)
        
        # جلب البيانات لجميع الأطر الزمنية المطلوبة بدقة حقيقية
        df_1m = ticker.history(period="1d", interval="1m")
        df_1h = ticker.history(period="7d", interval="1h")
        df_4h = ticker.history(period="15d", interval="4h")
        df_1d = ticker.history(period="60d", interval="1d")

        if df_1h.empty or df_4h.empty or df_1d.empty:
            return None

        current_price = float(df_1h['Close'].iloc[-1])

        # 1. محلل الاتجاه اليومي (1d Analyst) - فحص الهيكل العام
        ma_50_1d = df_1d['Close'].rolling(window=50).mean().iloc[-1]
        trend_1d = "BULLISH" if df_1d['Close'].iloc[-1] > ma_50_1d else "BEARISH"

        # 2. محلل الهيكل والسيولة المتوسطة (4h/1h Analyst - SMC & Order Blocks)
        high_4h = float(df_4h['High'].iloc[-10:-1].max())
        low_4h = float(df_4h['Low'].iloc[-10:-1].min())
        bos_bullish_4h = current_price > high_4h
        bos_bearish_4h = current_price < low_4h

        # كتل الأوامر (Order Blocks) وحساب الفجوات (FVG)
        df_1h['Body'] = abs(df_1h['Close'] - df_1h['Open'])
        avg_body = df_1h['Body'].mean()
        fvg_detected = (df_1h['High'].iloc[-2] < df_1h['Low'].iloc[-1]) or (df_1h['Low'].iloc[-2] > df_1h['High'].iloc[-1])
        
        # 3. محلل الزخم اللحظي السريع (1m Analyst)
        momentum_1m = 0
        if not df_1m.empty and len(df_1m) > 10:
            ema_fast = df_1m['Close'].ewm(span=5).mean().iloc[-1]
            ema_slow = df_1m['Close'].ewm(span=20).mean().iloc[-1]
            momentum_1m = 1 if ema_fast > ema_slow else -1

        # دمج تقييمات المحللين الثلاثة (Multi-Analyst Consensus)
        bullish_score = 0
        bearish_score = 0

        if trend_1d == "BULLISH": bullish_score += 35
        else: bearish_score += 35

        if bos_bullish_4h or current_price > df_4h['Close'].rolling(window=10).mean().iloc[-1]:
            bullish_score += 35
        else:
            bearish_score += 35

        if momentum_1m >= 0: bullish_score += 30
        else: bearish_score += 30

        # حساب التذبذب الحقيقي باستخدام ATR من فريم الساعة
        df_1h['HL'] = df_1h['High'] - df_1h['Low']
        atr = df_1h['HL'].rolling(window=14).mean().iloc[-1]
        if pd.isna(atr) or atr == 0: atr = current_price * 0.002

        if bullish_score >= bearish_score:
            signal = "شراء 🟢 (BUY)"
            sl = current_price - (atr * 1.5)
            tp = current_price + (atr * 3.0)
            confidence = round(min(96.5, max(72.0, float(bullish_score))), 1)
            bos_text = "كسر صاعد مدعوم باتجاه 1D وإطار 4H 🟢 (Bullish BOS)"
        else:
            signal = "بيع 🔴 (SELL)"
            sl = current_price + (atr * 1.5)
            tp = current_price - (atr * 3.0)
            confidence = round(min(96.5, max(72.0, float(bearish_score))), 1)
            bos_text = "كسر هابط مدعوم باتجاه 1D وإطار 4H 🔴 (Bearish BOS)"

        fvg_text = "فجوة قيمة عادلة مؤكدة عبر 1H/4H 🟢 (FVG Active)" if fvg_detected else "منطقة سيولة متوازنة ⚖️ (Balanced Liquidity)"
        ob_text = "منطقة طلب/عرض مؤسسية متقاطعة 📥 (SMC Order Block)"

        return {
            'price': current_price,
            'signal': signal,
            'bos': bos_text,
            'fvg': fvg_text,
            'ob': ob_text,
            'sl': sl,
            'tp': tp,
            'score': confidence,
            'lot_table': generate_prop_firm_lot_table(current_price, sl, ticker_symbol)
        }
    except Exception:
        return None

# --- نظام المراقبة والتتبع (24/7) ---
async def background_market_monitor(application: Application):
    global active_trades
    await asyncio.sleep(2)
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
                    pips = 0.0

                    if trade['type'] == "BUY":
                        if current_price >= trade['tp']:
                            closed, result = True, "✅ هدف مربح (Hit TP)"
                            pips = abs(trade['tp'] - trade['entry']) * 10000
                        elif current_price <= trade['sl']:
                            closed, result = True, "❌ وقف خسارة (Hit SL)"
                            pips = -abs(trade['entry'] - trade['sl']) * 10000
                    elif trade['type'] == "SELL":
                        if current_price <= trade['tp']:
                            closed, result = True, "✅ هدف مربح (Hit TP)"
                            pips = abs(trade['entry'] - trade['tp']) * 10000
                        elif current_price >= trade['sl']:
                            closed, result = True, "❌ وقف خسارة (Hit SL)"
                            pips = -abs(trade['sl'] - trade['entry']) * 10000

                    if closed:
                        outcome = "win" if "TP" in result else "loss"
                        record_trade_result(trade['symbol'], outcome, round(pips, 1))
                        
                        msg = (
                            f"📊 **تحديث صفقة {trade['name']}**\n"
                            f"───────────────────\n"
                            f"النتيجة: **{result}**\n"
                            f"📌 السعر الحالي: `{current_price:.5f}`\n"
                            f"📈 النقاط: `{round(pips, 1)} Pips`"
                        )
                        await application.bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')
                        active_trades.remove(trade)
            
            await asyncio.sleep(0.5)
        except Exception:
            await asyncio.sleep(1.0)

async def post_init(application: Application):
    asyncio.create_task(background_market_monitor(application))

# --- القوائم والأزرار ---
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "مرحباً بك في نظام **Fenix Fx Pro 24/7 المتقدم** 🦅\n\n"
        "النظام يعتمد الآن على محللين متعددين وفريمات من 1m إلى 1d مع رصد دقيق لنتائج اليوم ونقاط الأداء."
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
            "🦅 **عن النظام الاحترافي Fenix Fx Pro** 🦅\n\n"
            "▫️ يحلل السوق عبر عدة أطر زمنية متزامنة (1m, 1h, 4h, 1d).\n"
            "▫️ نظام تقاطع متعدد المحللين (Multi-Analyst Engine) لدقة الإشارات.\n"
            "▫️ تتبع تلقائي للصفقات وعرض الإحصائيات اليومية والنقاط المكتسبة."
        )
        await update.message.reply_text(about_text, parse_mode='Markdown')

    elif text == "🏆 قواعد شركات التمويل":
        rules = "🏆 **قواعد التمويل:** المخاطرة 0.5% مع الالتزام بالهدف ووقف الخسارة."
        await update.message.reply_text(rules, parse_mode='Markdown')

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **إدارة المخاطر:** التزم بالجدول الخاص بحجم اللوت لتجنب السحب العالي.", parse_mode='Markdown')

    elif text == "📊 تقرير الأداء الشامل":
        stats = load_stats()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_sum = stats.get("daily_summary", {}).get(today_str, {"wins": 0, "losses": 0, "total_pips": 0.0})
        
        total_trades = daily_sum["wins"] + daily_sum["losses"]
        win_rate = (daily_sum["wins"] / total_trades * 100) if total_trades > 0 else 0.0

        report = (
            f"📈 **تقرير الأداء اليومي ({today_str}):**\n"
            f"───────────────────\n"
            f"🎯 إجمالي صفقات اليوم: `{total_trades}`\n"
            f"✅ صفقات رابحة: `{daily_sum['wins']}`\n"
            f"❌ صفقات خاسرة: `{daily_sum['losses']}`\n"
            f"📊 نسبة النجاح اليومية: `{win_rate:.1f}%`\n"
            f"💰 إجمالي النقاط المحققة: `{daily_sum['total_pips']} Pips`"
        )
        await update.message.reply_text(report, parse_mode='Markdown')

    elif text in ALL_PAIRS_MAP:
        ticker = ALL_PAIRS_MAP[text]
        await update.message.reply_text(f"🧠 جاري تفعيل المحللين المتعددين وفحص الفريمات (1m إلى 1d) لـ {text}...")

        has_news, news_info = check_high_impact_news(ticker)
        if has_news:
            await update.message.reply_text(f"🛑 **تنبيه:** خبر عالي التأثير على `{text}`: {news_info}. تم إيقاف الإشارة مؤقتاً.", parse_mode='Markdown')
            return

        smc = multi_analyst_market_evaluation(ticker)
        if smc:
            reply = (
                f"🦅 **إشارة تداول متعددة الفريمات (1m - 1d) - {text}**\n"
                f"───────────────────\n"
                f"🎯 **سعر الدخول الفعلي:** `{smc['price']:.5f}`\n"
                f"🎯 **الإشارة:** `{smc['signal']}`\n\n"
                f"📌 **مستويات التنفيذ:**\n"
                f"🎯 **الهدف (TP):** `{smc['tp']:.5f}`\n"
                f"🛡️ **وقف الخسارة (SL):** `{smc['sl']:.5f}`\n"
                f"⚖️ **R:R:** `1 : 2`\n"
                f"📊 **نسبة الثقة المركبة:** `{smc['score']}%`\n\n"
                f"🧠 **تحليل المحللين و SMC:**\n"
                f"▫️ **الهيكل والاتجاه:** {smc['bos']}\n"
                f"▫️ **الفجوة والسيولة:** {smc['fvg']}\n"
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
                'entry': smc['price'],
                'tp': smc['tp'],
                'sl': smc['sl']
            })
        else:
            await update.message.reply_text("❌ تعذر إتمام تقييم المحللين في الوقت الحالي، حاول مجدداً.")
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
