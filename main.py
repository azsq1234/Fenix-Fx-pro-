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

# إعداد الرسم ليعمل في الخلفية بدون واجهة رسومية (مهم جداً لـ Render)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from telegram import Bot
from telegram.error import TelegramError

# ==================== الإعدادات الأساسية ====================
TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

STATS_FILE = "stats.json"
TRADES_FILE = "active_trades.json"

# الـ 15 زوجاً ومؤشراً المراقبة
MONITORED_PAIRS = {
    # 1. فوركس - الأزواج الرئيسية
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "USD/CHF": "USDCHF=X",
    "NZD/USD": "NZDUSD=X",
    
    # 2. فوركس - التقاطعات (Crosses)
    "GBP/JPY": "GBPJPY=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/GBP": "EURGBP=X",
    
    # 3. السلع (Commodities)
    "GOLD": "XAUUSD=X",
    "USOIL": "CL=F",
    
    # 4. العملات الرقمية (Crypto)
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
    "Solana": "SOL-USD"
}

# ==================== إدارة البيانات ====================
def load_active_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE, "r") as f: return json.load(f)
    except: return []

def save_active_trades(trades):
    try:
        with open(TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving trades: {e}")

def load_stats():
    if not os.path.exists(STATS_FILE): return {"trades": [], "daily_summary": {}}
    try:
        with open(STATS_FILE, "r") as f: return json.load(f)
    except: return {"trades": [], "daily_summary": {}}

def save_stats(stats):
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f)
    except Exception as e:
        logging.error(f"Error saving stats: {e}")

def record_trade_result(symbol, outcome, pips):
    stats = load_stats()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "trades" not in stats: stats["trades"] = []
    stats["trades"].append({"symbol": symbol, "outcome": outcome, "pips": pips, "date": today_str})
    save_stats(stats)

# ==================== خادم الصحة لـ Render ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro - SMC Smart Money Engine is LIVE!")
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== محرك تحليل SMC ====================
def analyze_smc_structure(df):
    """تحليل هياكل SMC واستخراج نقاط الدخول والأهداف"""
    if df is None or len(df) < 40: return None
    df = df.copy()
    
    # 1. تحديد القمم والقيعان الهيكلية
    df['Swing_High'] = (df['High'] > df['High'].shift(1)) & (df['High'] > df['High'].shift(2)) & \
                       (df['High'] > df['High'].shift(-1)) & (df['High'] > df['High'].shift(-2))
    df['Swing_Low'] = (df['Low'] < df['Low'].shift(1)) & (df['Low'] < df['Low'].shift(2)) & \
                      (df['Low'] < df['Low'].shift(-1)) & (df['Low'] < df['Low'].shift(-2))

    recent_highs = df[df['Swing_High']]['High']
    recent_lows = df[df['Swing_Low']]['Low']

    if len(recent_highs) < 2 or len(recent_lows) < 2: return None

    last_price = df['Close'].iloc[-1]
    last_high = df['High'].iloc[-1]
    last_low = df['Low'].iloc[-1]
    last_swing_high = recent_highs.iloc[-1]
    last_swing_low = recent_lows.iloc[-1]

    # 2. فحص تغير طبيعة السوق (CHoCH)
    bullish_choch = last_price > last_swing_high
    bearish_choch = last_price < last_swing_low

    # 3. فحص الفجوات السعرية (FVG)
    fvg_bullish = df['Low'].iloc[-1] > df['High'].iloc[-3]
    fvg_bearish = df['High'].iloc[-1] < df['Low'].iloc[-3]

    # 4. فحص سحب السيولة (Liquidity Sweep)
    ssl_sweep = (last_low < last_swing_low) and (last_price > last_swing_low)
    bsl_sweep = (last_high > last_swing_high) and (last_price < last_swing_high)

    # 5. تحديد مناطق الخصم والغلاء (Discount / Premium)
    range_high = df['High'].tail(30).max()
    range_low = df['Low'].tail(30).min()
    equilibrium = (range_high + range_low) / 2.0
    is_discount = last_price < equilibrium
    is_premium = last_price > equilibrium

    # 6. تحديد منطقة Order Block (OB)
    bullish_ob = df[df['Close'] < df['Open']].tail(5)['Low'].min() if bullish_choch else None
    bearish_ob = df[df['Close'] > df['Open']].tail(5)['High'].max() if bearish_choch else None

    score = 0
    signal = None
    confluences = []

    if bullish_choch or ssl_sweep:
        if bullish_choch: score += 35; confluences.append("Bullish CHoCH")
        if ssl_sweep: score += 25; confluences.append("Liquidity Sweep (SSL)")
        if fvg_bullish: score += 20; confluences.append("Fair Value Gap (FVG)")
        if is_discount: score += 20; confluences.append("Discount Zone")
        if score >= 65: signal = "BUY"

    elif bearish_choch or bsl_sweep:
        if bearish_choch: score += 35; confluences.append("Bearish CHoCH")
        if bsl_sweep: score += 25; confluences.append("Liquidity Sweep (BSL)")
        if fvg_bearish: score += 20; confluences.append("Fair Value Gap (FVG)")
        if is_premium: score += 20; confluences.append("Premium Zone")
        if score >= 65: signal = "SELL"

    if not signal: return None

    # حساب الأهداف (R:R) والستوب لوز
    if signal == "BUY":
        sl = (bullish_ob if bullish_ob else last_swing_low) * 0.999
        risk = abs(last_price - sl)
        if risk == 0: return None
        tp1 = last_price + (risk * 2.0)
        tp2 = last_price + (risk * 3.5)
        tp3 = last_price + (risk * 5.0)
    else:
        sl = (bearish_ob if bearish_ob else last_swing_high) * 1.001
        risk = abs(sl - last_price)
        if risk == 0: return None
        tp1 = last_price - (risk * 2.0)
        tp2 = last_price - (risk * 3.5)
        tp3 = last_price - (risk * 5.0)

    return {
        'price': last_price,
        'signal': signal,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'score': min(score, 99),
        'confluences': confluences,
        'swing_high': last_swing_high,
        'swing_low': last_swing_low
    }

# ==================== توليد شارت الشموع اليابانية ====================
def generate_smc_chart(df, symbol_name, analysis, dec):
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        
        recent_df = df.tail(35).copy()
        up = recent_df[recent_df['Close'] >= recent_df['Open']]
        down = recent_df[recent_df['Close'] < recent_df['Open']]
        width = (recent_df.index[1] - recent_df.index[0]) * 0.6 if len(recent_df) > 1 else 0.001

        # رسم الشموع
        ax.vlines(up.index, up['Low'], up['High'], color='#1dd1a1', linewidth=1.2)
        ax.vlines(down.index, down['Low'], down['High'], color='#ff6b6b', linewidth=1.2)
        ax.bar(up.index, up['Close'] - up['Open'], width, bottom=up['Open'], color='#1dd1a1')
        ax.bar(down.index, down['Open'] - down['Close'], width, bottom=down['Close'], color='#ff6b6b')

        # رسم مستويات الصفقة
        fmt = f".{dec}f"
        ax.axhline(analysis['price'], color='#c8d6e5', linestyle='-', linewidth=1.2, label=f"ENTRY: {analysis['price']:{fmt}}")
        ax.axhline(analysis['sl'], color='#ff6b6b', linestyle='--', linewidth=1.2, label=f"SL (OB/Structure): {analysis['sl']:{fmt}}")
        ax.axhline(analysis['tp1'], color='#1dd1a1', linestyle=':', linewidth=1.2, label=f"TP1 (1:2): {analysis['tp1']:{fmt}}")
        ax.axhline(analysis['tp3'], color='#1dd1a1', linestyle='-', linewidth=1.5, label=f"TP3 (1:5): {analysis['tp3']:{fmt}}")

        # خط الـ CHoCH
        choch_level = analysis['swing_high'] if analysis['signal'] == "BUY" else analysis['swing_low']
        ax.axhline(choch_level, color='#feca57', linestyle='-.', alpha=0.7, label=f"SMC Structure (CHoCH)")

        title_color = '#1dd1a1' if analysis['signal'] == "BUY" else '#ff6b6b'
        ax.set_title(f"FENIX FX PRO | SMC INSTITUTIONAL CHART ({symbol_name})", fontsize=11, color=title_color, fontweight='bold')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.12)
        
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        logging.error(f"SMC Chart error for {symbol_name}: {e}")
        return None

# ==================== تحليل السوق المحصن ====================
def analyze_market_vip(ticker_symbol, symbol_name):
    try:
        ticker = yf.Ticker(ticker_symbol, session=session)
        df_5m = ticker.history(period="5d", interval="5m")
        if df_5m.empty: return None

        smc_result = analyze_smc_structure(df_5m)
        if not smc_result: return None

        # تحديد عدد الخانات العشرية ديناميكياً
        dec = 5
        if any(x in symbol_name for x in ["USOIL", "GOLD", "BTC", "Bitcoin", "Ethereum", "Solana"]):
            dec = 2
        elif "JPY" in symbol_name:
            dec = 3

        chart_img = generate_smc_chart(df_5m, symbol_name, smc_result, dec)

        return {
            'name': symbol_name,
            'symbol': ticker_symbol,
            'price': smc_result['price'],
            'signal': smc_result['signal'],
            'sl': smc_result['sl'],
            'tp1': smc_result['tp1'],
            'tp2': smc_result['tp2'],
            'tp3': smc_result['tp3'],
            'score': smc_result['score'],
            'confluences': " + ".join(smc_result['confluences']),
            'chart': chart_img,
            'dec': dec
        }
    except Exception as e:
        logging.error(f"Analysis error for {symbol_name}: {e}")
        return None

# ==================== الحلقة الرئيسية (Bot Loop) ====================
async def lightning_fast_bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await asyncio.sleep(2)
    logging.info("Starting SMC Institutional Engine Loop...")
    
    while True:
        try:
            active_trades = load_active_trades()
            active_symbols = [t['name'] for t in active_trades if t['state'] != 'closed']

            # فحص الـ 15 زوجاً بالتوازي لزيادة السرعة
            tasks = [asyncio.to_thread(analyze_market_vip, ticker, name) for name, ticker in MONITORED_PAIRS.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for analysis in results:
                # تخطي الأخطاء إن حدثت في أحد الأزواج
                if isinstance(analysis, Exception) or not analysis: continue
                
                symbol_name = analysis['name']
                if symbol_name in active_symbols: continue

                clean_symbol = symbol_name.replace("/", "").replace(" ", "").upper()
                emoji = "🟢" if analysis['signal'] == "BUY" else "🔴"
                d = analysis['dec']

                caption_text = (
                    f"🏛️ **SMART MONEY CONCEPT (SMC) SIGNAL** ⚡\n\n"
                    f"PAIR: `#{clean_symbol}`\n"
                    f"TYPE: `#{analysis['signal']}` {emoji}\n"
                    f"─────────────────\n"
                    f"🎯 **ENTRY:** `{analysis['price']:.{d}f}`\n"
                    f"🛡️ **SL (OB/Structure):** `{analysis['sl']:.{d}f}`\n\n"
                    f"📌 **VIP TARGETS (Institutional R:R):**\n"
                    f"✅ **TP1:** `{analysis['tp1']:.{d}f}` (1:2 RR)\n"
                    f"✅✅ **TP2:** `{analysis['tp2']:.{d}f}` (1:3.5 RR)\n"
                    f"🚀 **TP3:** `{analysis['tp3']:.{d}f}` (1:5 RR)\n\n"
                    f"🔍 **SMC Confluences:**\n`{analysis['confluences']}`\n"
                    f"─────────────────\n"
                    f"📊 SMC Score: `{analysis['score']}%`"
                )
                
                try:
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
                        'state': 'open',
                        'dec': d
                    }
                    active_trades.append(new_trade)
                    save_active_trades(active_trades)
                    logging.info(f"Signal sent for {symbol_name}")
                except TelegramError as te:
                    logging.error(f"Telegram error sending {symbol_name}: {te}")

            # --- إدارة الصفقات المفتوحة (Live Trade Management) ---
            if active_trades:
                trades_to_keep = []
                for trade in active_trades:
                    try:
                        ticker = yf.Ticker(trade['symbol_yfinance'], session=session)
                        current_price = float(ticker.fast_info['last_price'])
                    except Exception as e:
                        logging.error(f"Error fetching current price for {trade['name']}: {e}")
                        trades_to_keep.append(trade) # الاحتفاظ بالصفقة والمحاولة لاحقاً
                        continue
                    
                    closed = False
                    result_msg = ""
                    pips = 0.0
                    outcome = "loss"
                    is_buy = trade['type'] == "BUY"
                    clean_sym = trade['name'].replace("/", "").replace(" ", "").upper()
                    d = trade.get('dec', 5)

                    try:
                        # 1. ضرب وقف الخسارة
                        if (is_buy and current_price <= trade['sl']) or (not is_buy and current_price >= trade['sl']):
                            if trade['state'] == 'open':
                                closed, result_msg = True, "❌ **Hit Stop Loss (SMC Structure Broken)**"
                                pips = -abs(trade['entry'] - trade['sl']) * 10000
                            else:
                                closed, result_msg = True, "⚪ **Closed at Break-Even (Risk Free)** 🛡️"
                                pips = 0.0
                                outcome = "win"

                        # 2. ضرب الهدف الأول TP1
                        elif trade['state'] == 'open' and ((is_buy and current_price >= trade['tp1']) or (not is_buy and current_price <= trade['tp1'])):
                            trade['state'] = 'tp1_hit'
                            trade['sl'] = trade['entry'] # تأمين الصفقة
                            
                            msg = (
                                f"🎯 **TP1 HIT | #{clean_sym}** ✅\n"
                                f"─────────────────\n"
                                f"🔒 **SMC Risk Management:**\n"
                                f"1️⃣ إغلاق **50% من العقود**.\n"
                                f"2️⃣ نقل הستوب لوز لنقطة الدخول (**Break-Even: {trade['entry']:.{d}f}**)."
                            )
                            await bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')

                        # 3. ضرب الهدف الثاني TP2
                        elif trade['state'] == 'tp1_hit' and ((is_buy and current_price >= trade['tp2']) or (not is_buy and current_price <= trade['tp2'])):
                            trade['state'] = 'tp2_hit'
                            msg = f"🎯🎯 **TP2 HIT | #{clean_sym}** ✅✅"
                            await bot.send_message(chat_id=trade['chat_id'], text=msg, parse_mode='Markdown')

                        # 4. ضرب الهدف الثالث والأخير TP3
                        elif (is_buy and current_price >= trade['tp3']) or (not is_buy and current_price <= trade['tp3']):
                            closed, result_msg = True, "🚀🚀 **SMC FULL TAKE PROFIT (TP3 HIT) | R:R 1:5** 🔥"
                            pips = abs(trade['tp3'] - trade['entry']) * 10000
                            outcome = "win"

                        if closed:
                            record_trade_result(trade['name'], outcome, round(pips, 1))
                            final_msg = (
                                f"📊 **إغلاق صفقة #{clean_sym}**\n"
                                f"─────────────────\n"
                                f"{result_msg}\n"
                                f"📌 Price: `{current_price:.{d}f}`\n"
                                f"─────────────────"
                            )
                            await bot.send_message(chat_id=trade['chat_id'], text=final_msg, parse_mode='Markdown')
                        else:
                            trades_to_keep.append(trade)
                            
                    except TelegramError as te:
                        logging.error(f"Telegram error managing {clean_sym}: {te}")
                        trades_to_keep.append(trade) # احتفظ بها للمحاولة مجدداً

                # حفظ التحديثات بعد انتهاء الحلقة
                if len(trades_to_keep) != len(active_trades):
                    save_active_trades(trades_to_keep)

            await asyncio.sleep(5) # انتظار 5 ثوانٍ قبل المسح التالي لتخفيف الضغط على السيرفر
            
        except Exception as e:
            logging.error(f"Global Loop error: {e}")
            await asyncio.sleep(10) # انتظار قليلاً قبل استئناف العمل في حال وجود خطأ عام

def main():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(lightning_fast_bot_loop())

if __name__ == "__main__":
    main()
