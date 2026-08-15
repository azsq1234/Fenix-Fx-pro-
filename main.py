import sys
import subprocess
import os

# --- دالة التثبيت الذاتي (معدلة لاسم المكتبة الصحيح tvDatafeed) ---
def setup_environment():
    # لاحظ أن اسم الحزمة هنا هو tvDatafeed (بالحرف الكبير D)
    packages = {
        "tvDatafeed": "tvDatafeed",
        "pandas": "pandas",
        "python-telegram-bot": "telegram",
        "requests": "requests",
        "matplotlib": "matplotlib"
    }
    
    for package_name, import_name in packages.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"جاري تثبيت المكتبة الناقصة: {package_name}...")
            # استخدام اسم المكتبة الصحيح هنا
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

# تنفيذ التثبيت قبل بدء البوت
setup_environment()

# --- الاستيرادات الأساسية ---
import json
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import asyncio
import requests
import pandas as pd

from tvDatafeed import TvDatafeed, Interval

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from telegram import Bot
from telegram.error import TelegramError

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"

TRADES_FILE = "active_trades.json"

tv = TvDatafeed()

MONITORED_PAIRS = {
    "EUR/USD": ("EURUSD", "OANDA"),
    "GBP/USD": ("GBPUSD", "OANDA"),
    "USD/JPY": ("USDJPY", "OANDA"),
    "AUD/USD": ("AUDUSD", "OANDA"),
    "USD/CAD": ("USDCAD", "OANDA"),
    "USD/CHF": ("USDCHF", "OANDA"),
    "NZD/USD": ("NZDUSD", "OANDA"),
    "GBP/JPY": ("GBPJPY", "OANDA"),
    "EUR/JPY": ("EURJPY", "OANDA"),
    "EUR/GBP": ("EURGBP", "OANDA"),
    "GOLD": ("XAUUSD", "OANDA"),
    "USOIL": ("USOIL", "TVC"),
    "Bitcoin": ("BTCUSDT", "BINANCE"),
    "Ethereum": ("ETHUSDT", "BINANCE"),
    "Solana": ("SOLUSDT", "BINANCE")
}

def load_active_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE, "r") as f: return json.load(f)
    except: return []

def save_active_trades(trades):
    try:
        with open(TRADES_FILE, "w") as f: json.dump(trades, f, indent=2)
    except Exception as e: logging.error(f"Error saving trades: {e}")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Multi-Timeframe SMC Engine is LIVE!")
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_multi_tf_data(symbol, exchange):
    try:
        df_1d = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=100)
        df_4h = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_4_hour, n_bars=100)
        df_30m = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_30_minute, n_bars=150)
        df_15m = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_15_minute, n_bars=150)
        df_5m = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_5_minute, n_bars=200)
        
        if any(x is None or x.empty for x in [df_1d, df_4h, df_30m, df_15m, df_5m]):
            return None
        return {'1D': df_1d, '4H': df_4h, '30M': df_30m, '15M': df_15m, '5M': df_5m}
    except Exception as e:
        logging.error(f"Multi-TF fetch error for {symbol}: {e}")
        return None

def analyze_multi_timeframe(tfs):
    if not tfs: return None
    df_1d, df_4h, df_30m, df_15m, df_5m = tfs['1D'], tfs['4H'], tfs['30M'], tfs['15M'], tfs['5M']
    
    trend_1d = "BULLISH" if df_1d['Close'].iloc[-1] > df_1d['Close'].iloc[-5] else "BEARISH"
    struct_4h = "BULLISH" if df_4h['Close'].iloc[-1] > df_4h['Close'].iloc[-3] else "BEARISH"
    if trend_1d != struct_4h: return None

    sw_highs = df_30m['High'][(df_30m['High'] > df_30m['High'].shift(1)) & (df_30m['High'] > df_30m['High'].shift(-1))]
    sw_lows = df_30m['Low'][(df_30m['Low'] < df_30m['Low'].shift(1)) & (df_30m['Low'] < df_30m['Low'].shift(-1))]
    if len(sw_highs) < 1 or len(sw_lows) < 1: return None
    
    last_price = df_5m['Close'].iloc[-1]
    bullish_choch = last_price > df_5m['High'].shift(1).iloc[-1]
    bearish_choch = last_price < df_5m['Low'].shift(1).iloc[-1]
    
    fvg_bullish = df_5m['Low'].iloc[-1] > df_5m['High'].iloc[-3]
    fvg_bearish = df_5m['High'].iloc[-1] < df_5m['Low'].iloc[-3]

    signal = None
    if trend_1d == "BULLISH" and bullish_choch and fvg_bullish:
        signal = "BUY"
    elif trend_1d == "BEARISH" and bearish_choch and fvg_bearish:
        signal = "SELL"
    
    if not signal: return None
    
    sl = (sw_lows.iloc[-1] * 0.999) if signal == "BUY" else (sw_highs.iloc[-1] * 1.001)
    risk = abs(last_price - sl)
    return {'price': last_price, 'signal': signal, 'sl': sl, 'tp1': last_price+(risk*2), 'tp2': last_price+(risk*3.5), 'confluences': ["SMC Analysis"]}

def generate_chart(df, symbol_name, analysis, dec):
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        recent_df = df.tail(50)
        ax.bar(recent_df.index, recent_df['Close'] - recent_df['Open'], bottom=recent_df['Open'], color='#1dd1a1')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close(fig)
        return buf
    except: return None

async def bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    while True:
        try:
            for symbol_name, (tv_symbol, tv_exchange) in MONITORED_PAIRS.items():
                tfs = get_multi_tf_data(tv_symbol, tv_exchange)
                if not tfs: continue
                analysis = analyze_multi_timeframe(tfs)
                if not analysis: continue
                
                caption = f"SIGNAL: {analysis['signal']} for {symbol_name}"
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption)
            await asyncio.sleep(60)
        except Exception as e: logging.error(f"Loop Error: {e}")

if __name__ == "__main__":
    asyncio.run(bot_loop())
