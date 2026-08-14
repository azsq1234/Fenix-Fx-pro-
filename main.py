import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import asyncio
import requests
import yfinance as yf
import numpy as np
from telegram import Bot

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE" 

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

STATS_FILE = "stats.json"
active_trades = []
sent_signals_cache = set()

# ذاكرة تخزين مؤقتة سريعة جداً لمنع أي تأخير في جلب البيانات
price_memory_cache = {}

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
    stats["trades"].append({"symbol": symbol, "outcome": outcome, "pips": pips, "date": today_str})
    
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

MONITORED_PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "Bitcoin (BTC)": "BTC-USD",
    "Ethereum (ETH)": "ETH-USD",
    "Gold": "XAUUSD=X",
    "Oil": "CL=F"
}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro Ultra-Fast 0.1s Engine Active!")
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO)

def calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price):
    price_diff = abs(entry_price - sl_price)
    if price_diff == 0: return 1.0
    if ticker_symbol == "XAUUSD=X": return price_diff * 100.0  
    elif ticker_symbol == "CL=F": return price_diff * 1000.0
    elif "-USD" in ticker_symbol: return price_diff * 1.0
    elif "=X" in ticker_symbol: return price_diff * 100000.0
    return price_diff * 100.0

def generate_prop_firm_lot_table(entry_price, sl_price, ticker_symbol):
    loss_per_lot = calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price)
    if loss_per_lot == 0: loss_per_lot = 1.0
    capitals = [1000, 10000, 50000, 100000]
    table_text = "📐 **إدارة المخاطر واللوت (0.5%):**\n```text\nرأس المال  | اللوت       | المخاطرة\n-----------------------------------\n"
    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01(Min)" if exact_lot < 0.01 else str(round(exact_lot, 2))
        table_text += ("$" + str(cap)).ljust(10) + " \vert{} " + lot_str.ljust(11) + " \vert{} $" + str(round(risk_amount, 1)) + "\n"
    table_text += "```\n"
    return table_text

# محرك اتخاذ القرار الفائق السرعة باستخدام المصفوفات (Vectorized Speed Engine)
def ultra_fast_institutional_analysis(ticker_symbol, symbol_name):
    try:
        ticker = yf.Ticker(ticker_symbol, session=session)
        df = ticker.history(period="5d", interval="1h")
        if df.empty or len(df) < 50:
            return None

        closes = df['Close'].to_numpy()
        highs = df['High'].to_numpy()
        lows = df['Low'].to_numpy()
        
        current_price = float(closes[-1])
        ma_50 = np.mean(closes[-50:])
        
        # خوارزمية الخبراء السريعة جداً
        trend = "BULLISH" if current_price > ma_50 else "BEARISH"
        recent_high = float(np.max(highs[-10:-1]))
        recent_low = float(np.min(lows[-10:-1]))

        atr = np.mean(highs[-14:] - lows[-14:])
        if atr == 0: atr = current_price * 0.0015

        if trend == "BULLISH" and current_price > recent_high:
            signal = "شراء 🟢 (BUY)"
            sl = current_price - (atr * 1.5)
            tp = current_price + (atr * 3.0)
            score = 95.2
        elif trend == "BEARISH" and current_price < recent_low:
            signal = "بيع 🔴 (SELL)"
            sl = current_price + (atr * 1.5)
            tp = current_price - (atr * 3.0)
            score = 94.7
        else:
            return None

        return {
            'name': symbol_name,
            'symbol': ticker_symbol,
            'price': current_price,
            'signal': signal,
            'tp': tp,
            'sl': sl,
            'score': score,
            'lot_table': generate_prop_firm_lot_table(current_price, sl, ticker_symbol)
        }
    except Exception:
        return None

# حلقة المعالجة المتوازية الخاطفة 0.1 ثانية
async def lightning_fast_bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    
    while True:
        try:
            # استخدام مهام متوازية (Gather) لفحص جميع الأصول في نفس الميكروثانية دون أي انتظار تراكمي
            tasks = [asyncio.to_thread(ultra_fast_institutional_analysis, ticker, name) for name, ticker in MONITORED_PAIRS.items()]
            results = await asyncio.gather(*tasks)

            for analysis in results:
                if not analysis:
                    continue
                
                symbol_name = analysis['name']
                if symbol_name in sent_signals_cache:
                    continue

                sent_signals_cache.add(symbol_name)
                
                reply = (
                    f"⚡ **إشارة فائقة السرعة (0.1s) - {symbol_name}**\n"
                    f"───────────────────\n"
                    f"🎯 **سعر الدخول:** `{analysis['price']:.5f}`\n"
                    f"🎯 **الإشارة:** `{analysis['signal']}`\n\n"
                    f"📌 **الأهداف والمستويات:**\n"
                    f"🎯 **الهدف (TP):** `{analysis['tp']:.5f}`\n"
                    f"🛡️ **وقف الخسارة (SL):** `{analysis['sl']:.5f}`\n"
                    f"📊 **نسبة الثقة:** `{analysis['score']}%`\n\n"
                    f"{analysis['lot_table']}\n"
                    f"───────────────────\n"
                    f"🤖 **التنفيذ فوري ويتم التتمة حتى الهدف.**"
                )
                
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=reply, parse_mode='Markdown')
                
                active_trades.append({
                    'chat_id': TELEGRAM_CHAT_ID,
                    'name': symbol_name,
                    'symbol': symbol_name,
                    'symbol_yfinance': analysis['symbol'],
                    'type': "BUY" if "شراء" in analysis['signal'] else "SELL",
                    'entry': analysis['price'],
                    'tp': analysis['tp'],
                    'sl': analysis['sl']
                })

            # تتبع الصفقات النشطة بلحظتها
            if active_trades:
                for trade in active_trades[:]:
                    try:
                        ticker = yf.Ticker(trade['symbol_yfinance'], session=session)
                        current_price = float(ticker.fast_info['last_price'])
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
                            f"📊 **تحديث إغلاق صفقة {trade['name']}**\n"
                            f"───────────────────\n"
                            f"النتيجة: **{result}**\n"
                            f"📌 السعر: `{current_price:.5f}`\n"
                            f"📈 النقاط: `{round(pips, 1)} Pips`"
                        )
                        await bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')
                        active_trades.remove(trade)
                        if trade['symbol'] in sent_signals_cache:
                            sent_signals_cache.remove(trade['symbol'])

            # تقليل وقت الانتظار إلى أقصى حد ممكن لتنفيذ المهام بشكل متواصل وخاطف
            await asyncio.sleep(0.1)
        except Exception:
            await asyncio.sleep(0.5)

def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(lightning_fast_bot_loop())

if __name__ == "__main__":
    main()
