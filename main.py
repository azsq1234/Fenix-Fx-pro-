import json
import io
import threading
import logging
import asyncio
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from tvdatafeed import TvDatafeed, Interval
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from telegram import Bot

# الإعدادات
TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"
TELEGRAM_CHAT_ID = "-1004382901216"
TRADES_FILE = "active_trades.json"

tv = TvDatafeed()
logging.basicConfig(level=logging.INFO)

# سيرفر صحة البوت (للإبقاء على الريندر نشطاً)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Engine LIVE")
    def log_message(self, format, *args): pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthCheckHandler).serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# منطق العمل
async def bot_loop():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    while True:
        try:
            # مثال لجلب بيانات الذهب واستخراج شارت
            df = tv.get_hist(symbol="XAUUSD", exchange="OANDA", interval=Interval.in_5_minute, n_bars=50)
            if df is not None:
                plt.style.use('dark_background')
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.plot(df['close'], color='#1dd1a1')
                ax.set_title("XAUUSD 5M")
                
                buf = io.BytesIO()
                plt.savefig(buf, format='png')
                buf.seek(0)
                plt.close(fig)
                
                await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=buf, caption="شارت الذهب الحالي")
            
            await asyncio.sleep(60)
        except Exception as e:
            logging.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(bot_loop())
