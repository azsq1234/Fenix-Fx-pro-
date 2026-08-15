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

# --- سيرفر الفحص لإبقاء الخدمة نشطة على Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Multi-Timeframe SMC Engine is LIVE!")
    def log_message(self, format, *args): pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthCheckHandler).serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# --- جلب البيانات المتعددة للفريمات ---
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

# --- تحليل الفريمات والاستراتيجية ---
def analyze_multi_timeframe(tfs):
    if not tfs: return None
    
    df_1d = tfs['1D']
    df_4h = tfs['4H']
    df_30m = tfs['30M']
    df_15m = tfs['15M']
    df_5m = tfs['5M']

    trend_1d = "BULLISH" if df_1d['close'].iloc[-1] > df_1d['close'].iloc[-5] else "BEARISH"
    struct_4h = "BULLISH" if df_4h['close'].iloc[-1] > df_4h['close'].iloc[-3] else "BEARISH"

    if trend_1d != struct_4h:
        return None

    sw_highs = df_30m['high'][(df_30m['high'] > df_30m['high'].shift(1)) & (df_30m['high'] > df_30m['high'].shift(-1))]
    sw_lows = df_30m['low'][(df_30m['low'] < df_30m['low'].shift(1)) & (df_30m['low'] < df_30m['low'].shift(-1))]
    if len(sw_highs) < 1 or len(sw_lows) < 1: return None
    last_sw_high = sw_highs.iloc[-1]
    last_sw_low = sw_lows.iloc[-1]

    support_15m = df_15m['low'].tail(30).min()
    resistance_15m = df_15m['high'].tail(30).max()

    last_price = df_5m['close'].iloc[-1]
    
    bullish_choch = last_price > df_5m['high'].shift(1).iloc[-1]
    bearish_choch = last_price < df_5m['low'].shift(1).iloc[-1]
    
    fvg_bullish = df_5m['low'].iloc[-1] > df_5m['high'].iloc[-3]
    fvg_bearish = df_5m['high'].iloc[-1] < df_5m['low'].iloc[-3]

    signal = None
    confluences = []

    if trend_1d == "BULLISH" and bullish_choch and (fvg_bullish or last_price >= support_15m):
        signal = "BUY"
        confluences.append("1D/4H Bullish Trend")
        confluences.append("30M Swing Structure")
        confluences.append("15M Support Zone")
        confluences.append("5M Bullish CHoCH + FVG")

    elif trend_1d == "BEARISH" and bearish_choch and (fvg_bearish or last_price <= resistance_15m):
        signal = "SELL"
        confluences.append("1D/4H Bearish Trend")
        confluences.append("30M Swing Structure")
        confluences.append("15M Resistance Zone")
        confluences.append("5M Bearish CHoCH + FVG")

    if not signal: return None

    if signal == "BUY":
        sl = last_sw_low * 0.999
        risk = abs(last_price - sl)
        if risk == 0: return None
        tp1, tp2, tp3 = last_price + (risk * 2.0), last_price + (risk * 3.5), last_price + (risk * 5.0)
    else:
        sl = last_sw_high * 1.001
        risk = abs(sl - last_price)
        if risk == 0: return None
        tp1, tp2, tp3 = last_price - (risk * 2.0), last_price - (risk * 3.5), last_price - (risk * 5.0)

    return {
        'price': last_price, 'signal': signal, 'sl': sl,
        'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
        'confluences': confluences
    }

# --- رسم الشارت ---
def generate_chart(df, symbol_name, analysis, dec):
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        recent_df = df.tail(50).copy()
        up = recent_df[recent_df['close'] >= recent_df['open']]
        down = recent_df[recent_df['close'] < recent_df['open']]
        width = 0.6

        ax.vlines(up.index, up['low'], up['high'], color='#1dd1a1', linewidth=1.2)
        ax.vlines(down.index, down['low'], down['high'], color='#ff6b6b', linewidth=1.2)
        ax.bar(up.index, up['close'] - up['open'], width, bottom=up['open'], color='#1dd1a1')
        ax.bar(down.index, down['open'] - down['close'], width, bottom=down['close'], color='#ff6b6b')

        fmt = f".{dec}f"
        ax.axhline(analysis['price'], color='#c8d6e5', linestyle='-', linewidth=1.2, label=f"ENTRY: {analysis['price']:{fmt}}")
        ax.axhline(analysis['sl'], color='#ff6b6b', linestyle='--', linewidth=1.2, label=f"SL: {analysis['sl']:{fmt}}")
        ax.axhline(analysis['tp2'], color='#1dd1a1', linestyle=':', linewidth=1.5, label=f"TP2: {analysis['tp2']:{fmt}}")

        title_color = '#1dd1a1' if analysis['signal'] == "BUY" else '#ff6b6b'
        ax.set_title(f"MULTI-TF SMC ENGINE ({symbol_name})", fontsize=11, color=title_color, fontweight='bold')
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

# --- الحلقة الرئيسية ---
async def bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    logging.info("Multi-Timeframe SMC Engine started...")
    
    while True:
        try:
            active_trades = load_active_trades()
            active_symbols = [t['name'] for t in active_trades if t['state'] != 'closed']

            for symbol_name, (tv_symbol, tv_exchange) in MONITORED_PAIRS.items():
                if symbol_name in active_symbols: continue
                
                tfs = get_multi_tf_data(tv_symbol, tv_exchange)
                if not tfs: continue

                analysis = analyze_multi_timeframe(tfs)
                if not analysis: continue

                dec = 2 if any(x in symbol_name for x in ["USOIL", "GOLD", "BTC", "Bitcoin", "Ethereum", "Solana"]) else (3 if "JPY" in symbol_name else 5)
                
                chart_img = generate_chart(tfs['5M'], symbol_name, analysis, dec)
                emoji = "🟢" if analysis['signal'] == "BUY" else "🔴"

                caption = (
                    f"🏛️ **MULTI-TF SMC STRATEGY** ⚡\n\n"
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
                
                try:
                    if chart_img:
                        await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=chart_img, caption=caption, parse_mode='Markdown')
                    else:
                        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode='Markdown')
                    
                    active_trades.append({
                        'chat_id': TELEGRAM_CHAT_ID, 'name': symbol_name, 
                        'type': analysis['signal'], 'entry': analysis['price'], 
                        'sl': analysis['sl'], 'tp1': analysis['tp1'], 'tp2': analysis['tp2'], 'tp3': analysis['tp3'], 
                        'state': 'open', 'dec': dec
                    })
                    save_active_trades(active_trades)
                except Exception as e:
                    logging.error(f"Telegram Error: {e}")
            
            await asyncio.sleep(20)
            
        except Exception as e:
            logging.error(f"Global Loop Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(bot_loop())
