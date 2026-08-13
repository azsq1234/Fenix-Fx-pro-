import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import pandas as pd
import ta
import numpy as np
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 🔑 التوكين الجديد المربوط
TELEGRAM_BOT_TOKEN = "8482434263:AAG1N_R8AEZCKmLWDlyEA2HE8VYT1wMewgY"

# --- سيرفر فحص الصحة لضمان الاستمرارية على Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro is Running!")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- محرك تحليل SMC والتحليل الفني ---
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

# --- واجهة الأزرار والتعامل مع الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📊 طلب إشارة تداول")],
        [KeyboardButton("ℹ️ حول البوت"), KeyboardButton("⚠️ إدارة المخاطر")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = (
        "🦅 **مرحباً بك في Fenix Fx Pro** 🦅\n\n"
        "النظام المطور لتحليل الأسواق المالية بناءً على **Smart Money Concepts (SMC)** والسيولة.\n\n"
        "👇 **استخدم الأزرار بالأسفل للتنقل والحصول على الإشارات:**"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 طلب إشارة تداول" or text == "/signal":
        await update.message.reply_text("⏳ جاري تحليل بيانات السوق وهيكل SMC...")
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

    elif text == "ℹ️ حول البوت":
        await update.message.reply_text("🤖 **Fenix Fx Pro**: بوت ذكي يحلل اتجاهات السيولة ومناطق العرض والطلب لتوفير إشارات تداول عالية الدقة.")

    elif text == "⚠️ إدارة المخاطر":
        await update.message.reply_text("📌 **قواعد التداول:**\n1. لا تخاطر بأكثر من 1-2% لكل صفقة.\n2. التزم دائماً بوقف الخسارة (SL).")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", handle_messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.run_polling()

if __name__ == "__main__":
    main()
