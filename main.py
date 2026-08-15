import os
import json
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
import numpy as np
from tvDatafeed import TvDatafeed, Interval
from telegram import Bot

# --- الإعدادات الأساسية ---
TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"
TRADES_FILE = "active_trades.json"

# --- روابط صور الـ GIF ---
BUY_GIF_URL = "https://media.giphy.com/media/Q8I5u6AL18H28/giphy.gif"
SELL_GIF_URL = "https://media.giphy.com/media/W3gH7rhoXasdO/giphy.gif"

tv = TvDatafeed()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- الأزواج المراد مراقبتها (15 زوجاً) ---
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

# --- سيرفر الحماية لـ Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix FX Pro - Pro SMC Engine is LIVE!")
    def log_message(self, format, *args): pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthCheckHandler).serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# --- جلب بيانات الأطر الزمنية المتعددة ---
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
        logging.error(f"Fetch error for {symbol}: {e}")
        return None

# --- استراتيجية Smart Money Concepts المؤسساتية المتكاملة ---
def analyze_multi_timeframe(tfs):
    if not tfs: return None
    
    df_1d, df_4h, df_30m, df_15m, df_5m = tfs['1D'], tfs['4H'], tfs['30M'], tfs['15M'], tfs['5M']
    
    ema_1d = df_1d['close'].ewm(span=20, adjust=False).mean().iloc[-1]
    trend_1d = "BULLISH" if df_1d['close'].iloc[-1] > ema_1d else "BEARISH"

    df_30m['swing_high'] = df_30m['high'][(df_30m['high'] > df_30m['high'].shift(1)) & (df_30m['high'] > df_30m['high'].shift(-1))]
    df_30m['swing_low'] = df_30m['low'][(df_30m['low'] < df_30m['low'].shift(1)) & (df_30m['low'] < df_30m['low'].shift(-1))]
    
    recent_highs = df_30m['swing_high'].dropna()
    recent_lows = df_30m['swing_low'].dropna()
    
    if len(recent_highs) < 2 or len(recent_lows) < 2: return None
    
    dealing_range_high = recent_highs.iloc[-1]
    dealing_range_low = recent_lows.iloc[-1]
    
    eq_level = (dealing_range_high + dealing_range_low) / 2
    last_price = df_5m['close'].iloc[-1]
    
    in_discount = last_price < eq_level
    in_premium = last_price > eq_level

    sweep_low = (df_15m['low'].iloc[-2] < dealing_range_low) and (df_15m['close'].iloc[-2] > dealing_range_low)
    sweep_high = (df_15m['high'].iloc[-2] > dealing_range_high) and (df_15m['close'].iloc[-2] < dealing_range_high)

    bullish_ob_valid = False
    bullish_choch = False
    ob_low = 0
    
    for i in range(-5, -1):
        if df_5m['close'].iloc[i] < df_5m['open'].iloc[i]:
            if df_5m['close'].iloc[i+1] > df_5m['high'].iloc[i]:
                if df_5m['low'].iloc[i+2] > df_5m['high'].iloc[i]:
                    bullish_ob_valid = True
                    ob_low = df_5m['low'].iloc[i]
                    break
    
    if df_5m['close'].iloc[-1] > df_5m['high'].iloc[-3:-1].max():
        bullish_choch = True

    bearish_ob_valid = False
    bearish_choch = False
    ob_high = 0
    
    for i in range(-5, -1):
        if df_5m['close'].iloc[i] > df_5m['open'].iloc[i]:
            if df_5m['close'].iloc[i+1] < df_5m['low'].iloc[i]:
                if df_5m['high'].iloc[i+2] < df_5m['low'].iloc[i]:
                    bearish_ob_valid = True
                    ob_high = df_5m['high'].iloc[i]
                    break
                    
    if df_5m['close'].iloc[-1] < df_5m['low'].iloc[-3:-1].min():
        bearish_choch = True

    signal, confluences = None, []

    if trend_1d == "BULLISH" and in_discount and bullish_ob_valid and bullish_choch:
        signal = "BUY"
        confluences.append("🟢 HTF Trend: Bullish")
        confluences.append("🟢 Zone: Discount (Below 50% EQ)")
        if sweep_low: confluences.append("💧 Sell-Side Liquidity Swept")
        confluences.append("📦 Valid Bullish Order Block + FVG")
        confluences.append("⚡ 5M Bullish CHoCH")
        
        sl = ob_low * 0.999
        risk = abs(last_price - sl)
        if risk == 0: return None
        tp1, tp2, tp3 = last_price + (risk * 2.0), last_price + (risk * 3.5), last_price + (risk * 5.0)

    elif trend_1d == "BEARISH" and in_premium and bearish_ob_valid and bearish_choch:
        signal = "SELL"
        confluences.append("🔴 HTF Trend: Bearish")
        confluences.append("🔴 Zone: Premium (Above 50% EQ)")
        if sweep_high: confluences.append("💧 Buy-Side Liquidity Swept")
        confluences.append("📦 Valid Bearish Order Block + FVG")
        confluences.append("⚡ 5M Bearish CHoCH")
        
        sl = ob_high * 1.001
        risk = abs(sl - last_price)
        if risk == 0: return None
        tp1, tp2, tp3 = last_price - (risk * 2.0), last_price - (risk * 3.5), last_price - (risk * 5.0)

    if not signal: return None

    return {
        'price': last_price, 'signal': signal, 'sl': sl, 
        'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'confluences': confluences
    }

# --- نظام متابعة الصفقات والـ TP / SL الفوري ---
async def monitor_active_trades(bot):
    trades = load_active_trades()
    updated = False

    for trade in trades:
        if trade.get('state') == 'closed': continue

        symbol_name = trade['name']
        tv_symbol, tv_exchange = MONITORED_PAIRS[symbol_name]

        try:
            df = tv.get_hist(symbol=tv_symbol, exchange=tv_exchange, interval=Interval.in_1_minute, n_bars=5)
            if df is None or df.empty: continue

            current_high = df['high'].max()
            current_low = df['low'].min()
            dec = trade.get('dec', 2)

            msg = None

            if trade['type'] == 'BUY':
                if current_low <= trade['sl']:
                    msg = f"❌ **TRADE CLOSED (STOP LOSS HIT)**\n\nPair: `#{symbol_name}`\nType: BUY 🔴\nSL Hit at: `{trade['sl']:.{dec}f}`"
                    trade['state'] = 'closed'
                elif current_high >= trade['tp3'] and trade.get('tp_hit') != 3:
                    msg = f"🚀🚀 **TARGET 3 HIT (FULL TAKE PROFIT)** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp3']:.{dec}f}`\nTrade Closed with Maximum Profit!"
                    trade['tp_hit'] = 3
                    trade['state'] = 'closed'
                elif current_high >= trade['tp2'] and trade.get('tp_hit') < 2:
                    msg = f"✅✅ **TARGET 2 HIT** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp2']:.{dec}f}`\nMove Stop Loss to Entry Point (SL = `{trade['entry']:.{dec}f}`)!"
                    trade['tp_hit'] = 2
                elif current_high >= trade['tp1'] and trade.get('tp_hit', 0) < 1:
                    msg = f"✅ **TARGET 1 HIT** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp1']:.{dec}f}`\nSecure Partial Profits!"
                    trade['tp_hit'] = 1

            elif trade['type'] == 'SELL':
                if current_high >= trade['sl']:
                    msg = f"❌ **TRADE CLOSED (STOP LOSS HIT)**\n\nPair: `#{symbol_name}`\nType: SELL 🔴\nSL Hit at: `{trade['sl']:.{dec}f}`"
                    trade['state'] = 'closed'
                elif current_low <= trade['tp3'] and trade.get('tp_hit') != 3:
                    msg = f"🚀🚀 **TARGET 3 HIT (FULL TAKE PROFIT)** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp3']:.{dec}f}`\nTrade Closed with Maximum Profit!"
                    trade['tp_hit'] = 3
                    trade['state'] = 'closed'
                elif current_low <= trade['tp2'] and trade.get('tp_hit') < 2:
                    msg = f"✅✅ **TARGET 2 HIT** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp2']:.{dec}f}`\nMove Stop Loss to Entry Point (SL = `{trade['entry']:.{dec}f}`)!"
                    trade['tp_hit'] = 2
                elif current_low <= trade['tp1'] and trade.get('tp_hit', 0) < 1:
                    msg = f"✅ **TARGET 1 HIT** 🟢\n\nPair: `#{symbol_name}`\nPrice reached: `{trade['tp1']:.{dec}f}`\nSecure Partial Profits!"
                    trade['tp_hit'] = 1

            if msg:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown')
                updated = True

        except Exception as e:
            logging.error(f"Error monitoring {symbol_name}: {e}")

    if updated:
        save_active_trades(trades)

# --- الحلقة الرئيسية لتشغيل البوت ---
async def bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    logging.info("Fenix FX Pro - Institutional SMC Engine Started Successfully...")
    
    while True:
        try:
            await monitor_active_trades(bot)

            active_trades = load_active_trades()
            active_symbols = [t['name'] for t in active_trades if t.get('state') != 'closed']

            for symbol_name, (tv_symbol, tv_exchange) in MONITORED_PAIRS.items():
                if symbol_name in active_symbols: continue
                
                tfs = get_multi_tf_data(tv_symbol, tv_exchange)
                if not tfs: continue

                analysis = analyze_multi_timeframe(tfs)
                if not analysis: continue

                dec = 2 if any(x in symbol_name for x in ["USOIL", "GOLD", "BTC", "Bitcoin", "Ethereum", "Solana"]) else (3 if "JPY" in symbol_name else 5)
                
                gif_url = BUY_GIF_URL if analysis['signal'] == "BUY" else SELL_GIF_URL
                emoji = "🟢" if analysis['signal'] == "BUY" else "🔴"

                caption = (
                    f"🏛️ **FENIX FX PRO - INSTITUTIONAL SMC** ⚡\n\n"
                    f"PAIR: `#{symbol_name.replace('/', '')}`\n"
                    f"TYPE: `#{analysis['signal']}` {emoji}\n"
                    f"─────────────────\n"
                    f"🎯 **ENTRY:** `{analysis['price']:.{dec}f}`\n"
                    f"🛡️ **SL:** `{analysis['sl']:.{dec}f}`\n\n"
                    f"✅ **TP1:** `{analysis['tp1']:.{dec}f}`\n"
                    f"✅✅ **TP2:** `{analysis['tp2']:.{dec}f}`\n"
                    f"🚀 **TP3:** `{analysis['tp3']:.{dec}f}`\n\n"
                    f"🔍 **Institutional Confluences:**\n" + "\n".join([f"• {c}" for c in analysis['confluences']])
                )
                
                try:
                    await bot.send_animation(chat_id=TELEGRAM_CHAT_ID, animation=gif_url, caption=caption, parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Failed to send GIF for {symbol_name}: {e}")
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode='Markdown')
                
                active_trades.append({
                    'chat_id': TELEGRAM_CHAT_ID, 'name': symbol_name, 
                    'type': analysis['signal'], 'entry': analysis['price'], 
                    'sl': analysis['sl'], 'tp1': analysis['tp1'], 'tp2': analysis['tp2'], 'tp3': analysis['tp3'], 
                    'state': 'open', 'tp_hit': 0, 'dec': dec
                })
                save_active_trades(active_trades)

            await asyncio.sleep(30)
            
        except Exception as e:
            logging.error(f"Global Loop Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(bot_loop())
