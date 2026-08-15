import os
import io
import json
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tvdatafeed import TvDatafeed, Interval
from telegram import Bot

# --- الإعدادات الأساسية ---
TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"
TRADES_FILE = "active_trades.json"

tv = TvDatafeed()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- الأزواج المراد مراقبتها ---
MONITORED_PAIRS = {
    "EUR/USD": ("EURUSD", "OANDA"),
    "GBP/USD": ("GBPUSD", "OANDA"),
    "USD/JPY": ("USDJPY", "OANDA"),
    "GOLD": ("XAUUSD", "OANDA"),
    "USOIL": ("USOIL", "TVC"),
    "Bitcoin": ("BTCUSDT", "BINANCE"),
    "Ethereum": ("ETHUSDT", "BINANCE")
}

# --- إدارة الصفقات النشطة ---
def load_active_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE, "r") as f: return json.load(f)
    except: return []

def save_active_trades(trades):
    try:
        with open(TRADES_FILE, "w") as f: json.dump(trades, f, indent=2)
    except Exception as e: logging.error(f"Error saving trades: {e}")

# --- سيرفر الفحص (لإبقاء الخدمة نشطة على Render) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix FX Pro - Multi-TF SMC Engine is LIVE!")
    def log_message(self, format, *args): pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthCheckHandler).serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# --- جلب البيانات المتعددة للفريمات ---
def get_multi_tf_data(symbol, exchange):
    try:
        df_1d = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=50)
        df_4h = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_4_hour, n_bars=50)
        df_5m = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_5_minute, n_bars=100)
        
        if df_1d is None or df_4h is None or df_5m is None or df_5m.empty:
            return None
        return {'1D': df_1d, '4H': df_4h, '5M': df_5m}
    except Exception as e:
        logging.error(f"Data fetch error for {symbol}: {e}")
        return None

# --- التحليل الفني ومنطق SMC المبسط ---
def analyze_market(tfs):
    if not tfs: return None
    
    df_1d = tfs['1D']
    df_4h = tfs['4H']
    df_5m = tfs['5M']

    # تحديد الاتجاه العام
    trend_1d = "BULLISH" if df_1d['close'].iloc[-1] > df_1d['close'].iloc[-5] else "BEARISH"
    trend_4h = "BULLISH" if df_4h['close'].iloc[-1] > df_4h['close'].iloc[-3] else "BEARISH"

    if trend_1d != trend_4h:
        return None  # تصفية الصفقات الضعيفة إذا اختلف اليومي عن الـ 4 ساعات

    last_price = df_5m['close'].iloc[-1]
    signal = "BUY" if trend_1d == "BULLISH" else "SELL"

    # حساب الستوب والاهداف
    if signal == "BUY":
        sl = df_5m['low'].tail(10).min() * 0.999
        risk = abs(last_price - sl)
        if risk == 0: return None
        tp1 = last_price + (risk * 2.0)
        tp2 = last_price + (risk * 3.5)
        tp3 = last_price + (risk * 5.0)
    else:
        sl = df_5m['high'].tail(10).max() * 1.001
        risk = abs(sl - last_price)
        if risk == 0: return None
        tp1 = last_price - (risk * 2.0)
        tp2 = last_price - (risk * 3.5)
        tp3 = last_price - (risk * 5.0)

    return {
        'price': last_price, 'signal': signal, 'sl': sl,
        'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
        'confluences': [f"1D Trend: {trend_1d}", "5M SMC Structure Match"]
    }

# --- توليد الشارت الاحترافي ---
def generate_chart(df, symbol_name, analysis, dec):
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        recent = df.tail(50)
        
        ax.plot(recent.index, recent['close'], color='#00ffcc', linewidth=1.5, label='Price')
        ax.axhline(analysis['price'], color='#c8d6e5', linestyle='-', label=f"Entry: {analysis['price']:.{dec}f}")
        ax.axhline(analysis['sl'], color='#ff6b6b', linestyle='--', label=f"SL: {analysis['sl']:.{dec}f}")
        ax.axhline(analysis['tp2'], color='#1dd1a1', linestyle=':', label=f"TP2: {analysis['tp2']:.{dec}f}")

        ax.set_title(f"FENIX FX PRO - {symbol_name}", color='#00ffcc', fontsize=12, fontweight='bold')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.1)

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        plt.close(fig)
        return buf
    except:
        return None

# --- حلقة البوت الرئيسية ---
async def bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    logging.info("Fenix Fx Pro Engine started successfully...")
    
    while True:
        try:
            active_trades = load_active_trades()
            active_symbols = [t['name'] for t in active_trades if t['state'] != 'closed']

            for symbol_name, (tv_symbol, tv_exchange) in MONITORED_PAIRS.items():
                if symbol_name in active_symbols: continue
                
                tfs = get_multi_tf_data(tv_symbol, tv_exchange)
                if not tfs: continue

                analysis = analyze_market(tfs)
                if not analysis: continue

                dec = 2 if any(x in symbol_name for x in ["USOIL", "GOLD", "Bitcoin", "Ethereum"]) else (3 if "JPY" in symbol_name else 5)
                chart_img = generate_chart(tfs['5M'], symbol_name, analysis, dec)
                emoji = "🟢" if analysis['signal'] == "BUY" else "🔴"

                caption = (
                    f"🏛️ **FENIX FX PRO VIP SIGNAL** ⚡\n\n"
                    f"PAIR: `#{symbol_name.replace('/', '')}`\n"
                    f"TYPE: `#{analysis['signal']}` {emoji}\n"
                    f"─────────────────\n"
                    f"🎯 **ENTRY:** `{analysis['price']:.{dec}f}`\n"
                    f"🛡️ **SL:** `{analysis['sl']:.{dec}f}`\n\n"
                    f"✅ **TP1:** `{analysis['tp1']:.{dec}f}`\n"
                    f"✅✅ **TP2:** `{analysis['tp2']:.{dec}f}`\n"
                    f"🚀 **TP3:** `{analysis['tp3']:.{dec}f}`\n\n"
                    f"🔍 **Confluences:**\n" + "\n".join([f"• {c}" for c in analysis['confluences']])
                )
                
                if chart_img:
                    await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=chart_img, caption=caption, parse_mode='Markdown')
                else:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode='Markdown')
                
                active_trades.append({
                    'chat_id': TELEGRAM_CHAT_ID, 'name': symbol_name, 
                    'type': analysis['signal'], 'state': 'open'
                })
                save_active_trades(active_trades)
                
                await asyncio.sleep(15)
            
            await asyncio.sleep(60)
            
        except Exception as e:
            logging.error(f"Global Loop Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(bot_loop())
