import os
import json
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import asyncio
import requests
import yfinance as yf

# ضبط مكتبة الرسم البياني للعمل في الخلفية السحابية دون شاشة
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from telegram import Bot

# ==================== الإعدادات الأساسية ====================
TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

STATS_FILE = "stats.json"
TRADES_FILE = "active_trades.json"

MONITORED_PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "GOLD": "XAUUSD=X",
    "USOIL": "CL=F"
}

# ==================== إدارة الملفات والبيانات ====================
def load_active_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE, "r") as f: return json.load(f)
    except: return []

def save_active_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def load_stats():
    if not os.path.exists(STATS_FILE): return {"trades": [], "daily_summary": {}}
    try:
        with open(STATS_FILE, "r") as f: return json.load(f)
    except: return {"trades": [], "daily_summary": {}}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def record_trade_result(symbol, outcome, pips):
    stats = load_stats()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "trades" not in stats: stats["trades"] = []
    stats["trades"].append({"symbol": symbol, "outcome": outcome, "pips": pips, "date": today_str})
    save_stats(stats)

# ==================== خادم الصحة (Health Server) ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro VIP Institutional Engine Active!")
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO)

# ==================== توليد الشارت التوضيحي (Auto Chart) ====================
def generate_trade_chart(df, symbol_name, signal, entry, sl, tp1, tp2, tp3):
    """إنشاء صورة الشارت وإرجاعها في الذاكرة بدون حفظها على القرص"""
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        
        # رسم آخر 40 شمعة
        recent_df = df.tail(40)
        ax.plot(recent_df.index, recent_df['Close'], color='#00d2d3', linewidth=1.5, label='Price')
        ax.plot(recent_df.index, recent_df['EMA_50'], color='#ff9f43', linestyle='--', label='EMA 50')

        # رسم مستويات الصفقة
        ax.axhline(entry, color='#c8d6e5', linestyle='-', linewidth=1.2, label=f'ENTRY: {entry:.4f}')
        ax.axhline(sl, color='#ff6b6b', linestyle='--', linewidth=1.2, label=f'SL: {sl:.4f}')
        ax.axhline(tp1, color='#1dd1a1', linestyle=':', linewidth=1.2, label=f'TP1: {tp1:.4f}')
        ax.axhline(tp2, color='#1dd1a1', linestyle='-.', linewidth=1.2, label=f'TP2: {tp2:.4f}')
        ax.axhline(tp3, color='#1dd1a1', linestyle='-', linewidth=1.5, label=f'TP3: {tp3:.4f}')

        title_color = '#1dd1a1' if signal == "BUY" else '#ff6b6b'
        ax.set_title(f"FENIX FX PRO VIP ANALYSIS | {symbol_name} ({signal})", fontsize=12, color=title_color, fontweight='bold')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.15)
        
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        logging.error(f"Chart error: {e}")
        return None

# ==================== حسابات المخاطرة واللوت ====================
def generate_vip_lot_table(entry, sl, ticker_symbol):
    diff = abs(entry - sl)
    if diff == 0: diff = 1.0
    
    # حساب قيمة النقطة لكل عائلة أسواق
    if "XAUUSD" in ticker_symbol: loss_per_lot = diff * 100.0
    elif "CL=F" in ticker_symbol: loss_per_lot = diff * 1000.0
    elif "-USD" in ticker_symbol: loss_per_lot = diff * 1.0
    else: loss_per_lot = diff * 100000.0

    capitals = [1000, 10000, 50000]
    table_text = "📐 **إدارة المخاطر المقترحة (Risk Management):**\n"
    for cap in capitals:
        lot_05 = (cap * 0.005) / loss_per_lot
        lot_10 = (cap * 0.010) / loss_per_lot
        str_05 = "0.01" if lot_05 < 0.01 else f"{lot_05:.2f}"
        str_10 = "0.01" if lot_10 < 0.01 else f"{lot_10:.2f}"
        table_text += f"• `{cap}$` ➔ Risk 0.5%: `{str_05}` | Risk 1%: `{str_10}`\n"
    return table_text

# ==================== التحليل الفني والمؤشرات ====================
def apply_indicators(df):
    if df is None or len(df) < 50: return None
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

def analyze_market_vip(ticker_symbol, symbol_name):
    try:
        ticker = yf.Ticker(ticker_symbol, session=session)
        df_5m = ticker.history(period="5d", interval="5m")
        if df_5m.empty: return None

        df_15m = df_5m.resample('15min').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        df_30m = df_5m.resample('30min').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()

        df_5m = apply_indicators(df_5m)
        df_15m = apply_indicators(df_15m)
        df_30m = apply_indicators(df_30m)

        if df_5m is None or df_15m is None or df_30m is None: return None

        price = float(df_5m['Close'].iloc[-1])
        trend_30m = "BULLISH" if df_30m['Close'].iloc[-1] > df_30m['EMA_50'].iloc[-1] else "BEARISH"
        trend_15m = "BULLISH" if df_15m['Close'].iloc[-1] > df_15m['EMA_50'].iloc[-1] else "BEARISH"
        
        rsi_5m = df_5m['RSI'].iloc[-1]
        macd_5m = df_5m['MACD'].iloc[-1]
        macd_sig_5m = df_5m['MACD_Signal'].iloc[-1]
        
        recent_high = float(df_5m['High'].iloc[-10:-1].max())
        recent_low = float(df_5m['Low'].iloc[-10:-1].min())
        atr = float(df_5m['High'].iloc[-14:].max() - df_5m['Low'].iloc[-14:].min())
        if atr == 0: atr = price * 0.0015

        score = 0
        signal = None
        sl = 0

        if trend_30m == "BULLISH" and trend_15m == "BULLISH":
            score += 40
            if macd_5m > macd_sig_5m: score += 25
            if 30 <= rsi_5m <= 65: score += 20 
            if price > recent_high: score += 15 
            if score >= 65:
                signal = "BUY"
                sl = price - (atr * 1.5)

        elif trend_30m == "BEARISH" and trend_15m == "BEARISH":
            score += 40
            if macd_5m < macd_sig_5m: score += 25
            if 35 <= rsi_5m <= 70: score += 20 
            if price < recent_low: score += 15 
            if score >= 65:
                signal = "SELL"
                sl = price + (atr * 1.5)

        if not signal: return None

        # فرض نسبة عائد إلى مخاطرة R:R لا تقل عن 1:2 للهدف الأول
        risk = abs(price - sl)
        if signal == "BUY":
            tp1 = price + (risk * 2.0) # 1:2 RR
            tp2 = price + (risk * 3.5) # 1:3.5 RR
            tp3 = price + (risk * 5.0) # 1:5 RR
        else:
            tp1 = price - (risk * 2.0)
            tp2 = price - (risk * 3.5)
            tp3 = price - (risk * 5.0)

        # إنشاء صورة الشارت
        chart_img = generate_trade_chart(df_5m, symbol_name, signal, price, sl, tp1, tp2, tp3)

        return {
            'name': symbol_name,
            'symbol': ticker_symbol,
            'price': price,
            'signal': signal,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'score': min(score + 15, 99),
            'chart': chart_img,
            'lot_table': generate_vip_lot_table(price, sl, ticker_symbol)
        }
    except Exception as e:
        logging.error(f"Analysis error: {e}")
        return None

# ==================== الحلقة الرئيسية لتشغيل البوت ====================
async def lightning_fast_bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    
    while True:
        try:
            active_trades = load_active_trades()
            active_symbols = [t['name'] for t in active_trades]

            tasks = [asyncio.to_thread(analyze_market_vip, ticker, name) for name, ticker in MONITORED_PAIRS.items()]
            results = await asyncio.gather(*tasks)

            for analysis in results:
                if not analysis: continue
                
                symbol_name = analysis['name']
                if symbol_name in active_symbols: continue

                clean_symbol = symbol_name.replace("/", "").replace(" ", "").upper()
                emoji = "🟢" if analysis['signal'] == "BUY" else "🔴"

                # نص التوصية المتوافق مع برامج النسخ Auto-Copier
                caption_text = (
                    f"⚡ **FENIX FX PRO VIP SIGNAL** ⚡\n\n"
                    f"PAIR: `#{clean_symbol}`\n"
                    f"TYPE: `#{analysis['signal']}` {emoji}\n"
                    f"─────────────────\n"
                    f"🎯 **ENTRY:** `{analysis['price']:.5f}`\n"
                    f"🛡️ **SL:** `{analysis['sl']:.5f}`\n\n"
                    f"📌 **TARGETS (Risk:Reward 1:2+):**\n"
                    f"✅ **TP1:** `{analysis['tp1']:.5f}` (1:2 RR)\n"
                    f"✅✅ **TP2:** `{analysis['tp2']:.5f}` (1:3.5 RR)\n"
                    f"🚀 **TP3:** `{analysis['tp3']:.5f}` (1:5 RR)\n\n"
                    f"{analysis['lot_table']}\n"
                    f"─────────────────\n"
                    f"📊 Institutional Confidence: `{analysis['score']}%`\n"
                    f"⚠️ *تنبيه: تابع القناة للحصول على إشارات تأمين الصفقة (Break-Even).*"
                )
                
                # إرسال الصورة مع النص
                if analysis['chart']:
                    await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=analysis['chart'], caption=caption_text, parse_mode='Markdown')
                else:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption_text, parse_mode='Markdown')
                
                new_trade = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'name': symbol_name,
                    'symbol_yfinance': analysis['symbol'],
                    'type': analysis['signal'],
                    'entry': analysis['price'],
                    'sl': analysis['sl'],
                    'tp1': analysis['tp1'],
                    'tp2': analysis['tp2'],

                    'tp3': analysis['tp3'],
                    'state': 'open'
                }
                active_trades.append(new_trade)
                save_active_trades(active_trades)

            # --- VIP Trade Management (التأمين الفوري وتأمين الأرباح) ---
            if active_trades:
                for trade in active_trades[:]:
                    try:
                        ticker = yf.Ticker(trade['symbol_yfinance'], session=session)
                        current_price = float(ticker.fast_info['last_price'])
                    except: continue
                    
                    closed = False
                    result_msg = ""
                    pips = 0.0
                    outcome = "loss"
                    is_buy = trade['type'] == "BUY"
                    clean_sym = trade['name'].replace("/", "").replace(" ", "").upper()

                    # 1. فحص ضرب الستوب لوز SL
                    if (is_buy and current_price <= trade['sl']) or (not is_buy and current_price >= trade['sl']):
                        if trade['state'] == 'open':
                            closed, result_msg = True, "❌ **Hit Stop Loss (SL)**"
                            pips = -abs(trade['entry'] - trade['sl']) * 10000
                        else:
                            closed, result_msg = True, "⚪ **Closed at Break-Even (0 Risk)** - تم حجز الأرباح المسبقة 🛡️"
                            pips = 0.0
                            outcome = "win"

                    # 2. ضرب TP1 -> تأمين الصفقة وتوجيه المشتركين لحجز 50%
                    elif trade['state'] == 'open' and ((is_buy and current_price >= trade['tp1']) or (not is_buy and current_price <= trade['tp1'])):
                        trade['state'] = 'tp1_hit'
                        trade['sl'] = trade['entry'] # نقل الستوب لوز لنقطة الدخول تلقائياً
                        save_active_trades(active_trades)
                        
                        msg = (
                            f"🎯 **TP1 HIT | #{clean_sym}** ✅\n"
                            f"─────────────────\n"
                            f"🔥 **تنعش الأرباح!**\n"
                            f"🔒 **تعليمات الـ VIP الإجبارية:**\n"
                            f"1️⃣ إغلاق **50% من حجم العقود (Close Partial Profits)**.\n"
                            f"2️⃣ نقل الستوب لوز فوراً إلى سعر الدخول (**Move SL to Break-Even: {trade['entry']:.5f}**).\n"
                            f"الصفقة الآن آمنة تماماً بدون أي مخاطرة! 🚀"
                        )
                        await bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')

                    # 3. ضرب TP2
                    elif trade['state'] == 'tp1_hit' and ((is_buy and current_price >= trade['tp2']) or (not is_buy and current_price <= trade['tp2'])):
                        trade['state'] = 'tp2_hit'
                        save_active_trades(active_trades)
                        msg = f"🎯🎯 **TP2 HIT | #{clean_sym}** ✅✅\n🔥 استمروا في حجز باقي الأرباح وتأمين الحسابات!"
                        await bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')

                    # 4. ضرب TP3 (الهدف النهائي)
                    elif (is_buy and current_price >= trade['tp3']) or (not is_buy and current_price <= trade['tp3']):
                        closed, result_msg = True, "🚀🚀 **FULL TAKE PROFIT (TP3 HIT) | R:R 1:5** 🔥"
                        pips = abs(trade['tp3'] - trade['entry']) * 10000
                        outcome = "win"

                    if closed:
                        record_trade_result(trade['name'], outcome, round(pips, 1))
                        final_msg = (
                            f"📊 **إغلاق صفقة #{clean_sym}**\n"
                            f"─────────────────\n"
                            f"{result_msg}\n"
                            f"📌 Price: `{current_price:.5f}`\n"
                            f"─────────────────"
                        )
                        await bot.send_message(chat_id=trade['chat_id'], text=final_msg, parse_mode='Markdown')
                        active_trades.remove(trade)
                        save_active_trades(active_trades)

            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Loop error: {e}")
            await asyncio.sleep(2)

def main():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(lightning_fast_bot_loop())

if __name__ == "__main__":
    main()
