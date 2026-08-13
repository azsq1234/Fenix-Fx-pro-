import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, timezone
import asyncio
import requests
import yfinance as yf
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = "8923196852:AAEvbKmOtpXfrykk9APpuLYM6D7BIwiIIrE"

# --- إدارة الإحصائيات والصفقات النشطة ---
STATS_FILE = "stats.json"
active_trades = []

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def update_symbol_stats(symbol, outcome):
    stats = load_stats()
    if symbol not in stats:
        stats[symbol] = {"wins": 0, "losses": 0}
    if outcome == "win":
        stats[symbol]["wins"] += 1
    else:
        stats[symbol]["losses"] += 1
    save_stats(stats)

def get_symbol_win_rate(symbol):
    stats = load_stats()
    if symbol not in stats: return 0.0
    s = stats[symbol]
    total = s["wins"] + s["losses"]
    return (s["wins"] / total * 100) if total > 0 else 0.0

# --- تقسيم الأسواق والأزواج ---
FOREX_PAIRS = {
    "💶 EUR/USD": "EURUSD=X",
    "💷 GBP/USD": "GBPUSD=X",
    "💴 USD/JPY": "USDJPY=X",
    "🇨🇭 USD/CHF": "USDCHF=X",
    "🇨🇦 USD/CAD": "USDCAD=X",
    "🇦🇺 AUD/USD": "AUDUSD=X",
    "🇳ℤ NZD/USD": "NZDUSD=X",
    "🇪🇺 EUR/GBP": "EURGBP=X"
}

CRYPTO_PAIRS = {
    "₿ البيتكوين (BTC)": "BTC-USD",
    "💎 الإيثريوم (ETH)": "ETH-USD",
    "☀️ سولانا (SOL)": "SOL-USD",
    "🟡 باينانس (BNB)": "BNB-USD",
    "✕ ريبل (XRP)": "XRP-USD"
}

COMMODITIES_PAIRS = {
    "🥇 الذهب (Gold)": "GC=F",
    "🥈 الفضة (Silver)": "SI=F",
    "🛢 النفط (Oil)": "CL=F"
}

ALL_PAIRS_MAP = {**FOREX_PAIRS, **CRYPTO_PAIRS, **COMMODITIES_PAIRS}

MINUTES_BEFORE_NEWS = 30
MINUTES_AFTER_NEWS = 30

# --- سيرفر فحص الصحة لـ Render (24/7) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Fenix Fx Pro Active!")
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()
logging.basicConfig(level=logging.INFO)

# --- فلتر الأخبار عالية التأثير ---
def check_high_impact_news(symbol):
    try:
        if "=X" not in symbol:
            return False, ""
        clean_symbol = symbol.replace("=X", "")
        currency1, currency2 = clean_symbol[:3], clean_symbol[3:]

        url = "https://nodedata.forexfactory.com/forex/calendar/thisWeek.json"
        response = requests.get(url, timeout=5)
        if response.status_code != 200: return False, ""

        events = response.json()
        now_utc = datetime.now(timezone.utc)

        for event in events:
            if event.get("impact") == "High" and event.get("country") in [currency1, currency2]:
                event_time = datetime.fromisoformat(event.get("date")).astimezone(timezone.utc)
                diff_minutes = (event_time - now_utc).total_seconds() / 60.0
                if -MINUTES_AFTER_NEWS <= diff_minutes <= MINUTES_BEFORE_NEWS:
                    return True, f"{event.get('title')} ({event.get('country')})"

        return False, ""
    except Exception:
        return False, ""

# --- الخوارزمية الديناميكية لحساب الخسارة ---
def calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price):
    price_diff = abs(entry_price - sl_price)
    if price_diff == 0: return 1.0

    if ticker_symbol == "GC=F": return price_diff * 100.0
    elif ticker_symbol == "SI=F": return price_diff * 5000.0
    elif ticker_symbol == "CL=F": return price_diff * 1000.0
    elif "-USD" in ticker_symbol: return price_diff * 1.0
    elif "=X" in ticker_symbol:
        clean_symbol = ticker_symbol.replace("=X", "")
        base_curr, quote_curr = clean_symbol[:3], clean_symbol[3:]
        if quote_curr == "USD": return price_diff * 100000.0
        elif base_curr == "USD": return (price_diff * 100000.0) / entry_price
        elif quote_curr == "GBP": return price_diff * 100000.0 * 1.28
        else: return price_diff * 100000.0
    return price_diff * 100.0

def generate_prop_firm_lot_table(entry_price, sl_price, ticker_symbol):
    loss_per_lot = calculate_loss_per_standard_lot(ticker_symbol, entry_price, sl_price)
    if loss_per_lot == 0: loss_per_lot = 1.0

    capitals = [100, 500, 1000, 5000, 10000, 25000, 50000, 100000]
    table_text = "📐 **جدول اللوت الدقيق (مخاطرة 0.5%):**\n"
    table_text += "```text\n"
    table_text += "رأس المال | اللوت      | المخاطرة\n"
    table_text += "---------------------------------\n"

    for cap in capitals:
        risk_amount = cap * 0.005
        exact_lot = risk_amount / loss_per_lot
        lot_str = "0.01(Min)" if exact_lot < 0.01 else f"{exact_lot:.2f}"
        
        # التنسيق الآمن لتجنب أخطاء السيرفر
        cap_str = str(cap).ljust(9)
        lot_formatted = lot_str.ljust(10)
        risk_str = f"${risk_amount:.1f}".ljust(8)
        
        table_text += f"${cap_str}| {lot_formatted} | {risk_str}\n"

    table_text += "
