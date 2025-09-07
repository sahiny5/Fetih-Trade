import pytz
import pandas as pd
import numpy as np
import ccxt
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os

# Telegram token ve chat ID environment variables ile Railway'den çekilecek
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Zaman aralığı
INTERVAL = "5m"

# İzlenecek semboller
SYMBOLS = ["BTC/USDT","AVAX/USDT","SOL/USDT","LTC/USDT","AAVE/USDT","LINK/USDT"]

# Botu başlat
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# OKX public client
exchange = ccxt.okx()

# OKX interval eşlemesi
interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h"}

def get_historical_data(symbol, interval, limit=500):
    """OKX public OHLCV verisi çek"""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval_map[interval], limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df = df.apply(pd.to_numeric, errors='coerce')
    return df

def calculate_signal(df):
    """EMA + ATR + Sinyal hesaplama (fitiller dahil)"""
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()

    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_length = 14
    df['atr'] = tr.ewm(alpha=1/atr_length, adjust=False).mean()

    atrValue1 = df['atr'] * 0.75
    df['nearEMA200'] = np.abs(df['close'] - df['ema200']) < atrValue1
    df['nearEMA200a'] = np.abs(df['high'] - df['ema200']) < atrValue1
    df['nearEMA200b'] = np.abs(df['low'] - df['ema200']) < atrValue1

    def crossover(s1, s2):
        return (s1 > s2) & (s1.shift(1) <= s2.shift(1))

    def crossunder(s1, s2):
        return (s1 < s2) & (s1.shift(1) >= s2.shift(1))

    df['buyCross'] = crossover(df['ema20'], df['ema50']) & (df['nearEMA200b'] | df['nearEMA200'])
    df['sellCross'] = crossunder(df['ema20'], df['ema50']) & (df['nearEMA200a'] | df['nearEMA200'])
    df['buyCrossa'] = crossunder(df['ema20'], df['ema50']) & (df['nearEMA200b'] | df['nearEMA200'])
    df['sellCrossa'] = crossover(df['ema20'], df['ema50']) & (df['nearEMA200a'] | df['nearEMA200'])

    df['buyAbove'] = df['buyCross'] & (df['close'] > df['ema200'])
    df['buyBelow'] = df['sellCrossa'] & (df['close'] <= df['ema200'])
    df['sellBelow'] = df['sellCross'] & (df['close'] < df['ema200'])
    df['sellAbove'] = df['buyCrossa'] & (df['close'] >= df['ema200'])

    df['atrValue'] = df['atr'] * 2
    RR = 2.0

    last_row = df.iloc[-1]
    signal, tp, sl, entry, emoji = None, None, None, last_row['close'], ""

    if last_row['buyAbove']:
        signal = "BUY"; emoji="🚀"
        sl = entry - last_row['atrValue']; tp = entry + RR*last_row['atrValue']
    elif last_row['buyBelow']:
        signal = "GO (SELL)"; emoji="🔽"
        sl = entry + last_row['atrValue']; tp = entry - RR*last_row['atrValue']
    elif last_row['sellAbove']:
        signal = "GO (BUY)"; emoji="🔼"
        sl = entry - last_row['atrValue']; tp = entry + RR*last_row['atrValue']
    elif last_row['sellBelow']:
        signal = "SELL"; emoji="💣"
        sl = entry + last_row['atrValue']; tp = entry - RR*last_row['atrValue']

    return signal, tp, sl, entry, emoji

def run_bot():
    istanbul_tz = pytz.timezone('Europe/Istanbul')
    for symbol in SYMBOLS:
        try:
            df = get_historical_data(symbol, INTERVAL)
            signal, tp, sl, entry, emoji = calculate_signal(df)
            current_bar = df.iloc[-1]['timestamp']
            current_bar_local = pd.to_datetime(current_bar, unit='ms', utc=True).tz_convert(istanbul_tz)

            if signal:
                tv_symbol = symbol.replace("/", "")
                tv_url = f"https://www.tradingview.com/chart/?symbol=OKX:{tv_symbol}&interval=5"

                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("📈 Grafiği Aç", url=tv_url))

                message = (
                    f"{emoji} Sinyal: {signal}\n"
                    f"📊 Sembol: {symbol}\n"
                    f"🟢 Giriş: {round(entry,2)}\n"
                    f"💰 TP: {round(tp,2)}\n"
                    f"⛔ SL: {round(sl,2)}\n"
                    f"⏱ Zaman: {current_bar_local.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                bot.send_message(TELEGRAM_CHAT_ID, message, reply_markup=markup)
                print(f"{current_bar_local} → {symbol} → Sinyal gönderildi")
            else:
                print(f"{current_bar_local} → {symbol} → Sinyal yok")
        except Exception as e:
            print(f"{symbol} veri veya hesaplama hatası: {e}")

if __name__ == "__main__":
    run_bot()
