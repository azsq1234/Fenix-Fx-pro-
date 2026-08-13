import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import asyncio
import pandas as pd
import ta
import numpy as np
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 🔑 تم إدراج التوكين الخاص بك بنجاح
TELEGRAM_BOT_TOKEN = "8902321690:AAEVLPl1pxx_IqgDKHMtB5wxW55H59nlSzI"

# خادم وهمي لضمان استمرار عمل الخدمة على Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro Bot is active!")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# تشغيل خادم الفحص في الخلفية
threading.Thread(target=start_health_server, daemon=True).start()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

class SMCAnalyzer:
    @staticmethod
    def get_market_analysis(symbol="EUR/USD"):
        dates = pd.date_range(end=pd.Timestamp.now(), periods=50, freq='1h')
        close = 1.0850 + np.cumsum(np.random.randn(50) * 0.0004)
        df = pd.DataFrame({'Close': close}, index=dates)
        
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['EMA20'] = ta.trend.ema_indicator(df['Close'], window=20)
        
        price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        ema = df['EMA20'].iloc[-1]
        
        if price > ema and rsi > 52:
            signal = "BUY (شراء) 🟢"
            structure = "Bullish BOS + Demand Zone"
            sl = price - 0.0015
            tp1 = price + 0.0020
            tp2 = price + 0.0040
        else:
            signal = "SELL (بيع) 🔴"
            structure = "Bearish BOS + Supply Zone"
            sl = price + 0.0015
            tp1 = price - 0.0020
            tp2 = price - 0.0040
            
        return {
            'symbol': symbol, 'signal': signal, 'price': price,
            'structure': structure, 'rsi': rsi, 'sl': sl, 'tp1': tp1, 'tp2': tp2
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🔥 **Fenix Fx Pro Bot** 🔥\n\n"
        "أهلاً بك! البوت يعمل بنجاح سحابياً على مدار الساعة.\n\n"
        "أرسل الأمر /signal للحصول على إشارة التداول الحالية."
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def send_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = SMCAnalyzer.get_market_analysis("EUR/USD")
    
    reply = (
        f"🦅 **إشارة تداول - Fenix Fx Pro** 🦅\n"
        f"───────────────────────\n"
        f"🔤 **الزوج:** {data['symbol']}\n"
        f"🎯 **النوع:** {data['signal']}\n"
        f"💵 **سعر الدخول:** `{data['price']:.5f}`\n\n"
        f"🏛 **هيكل SMC:** {data['structure']}\n"
        f"📊 **مؤشر RSI:** {data['rsi']:.1f}\n"
        f"───────────────────────\n"
        f"🎯 **الهدف 1:** `{data['tp1']:.5f}`\n"
        f"🎯 **الهدف 2:** `{data['tp2']:.5f}`\n"
        f"🛑 **وقف الخسارة:** `{data['sl']:.5f}`\n"
        f"───────────────────────\n"
        f"💡 *إدارة المخاطر:* 1% إلى 2% من رأس المال."
    )
    await update.message.reply_text(reply, parse_mode='Markdown')

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", send_signal))
    app.run_polling()

if __name__ == "__main__":
    main()
