import os
import math
import requests
import pandas as pd
from datetime import datetime, timezone
import yfinance as yf

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = {
    "ALTIN": "GC=F",      # Gold Futures
    "GÜMÜŞ": "SI=F",      # Silver Futures
    "BTC": "BTC-USD"
}

# ===================== GÖSTERGELER =====================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def macd(series):
    fast = ema(series, 12)
    slow = ema(series, 26)
    macd_line = fast - slow
    signal = ema(macd_line, 9)
    hist = macd_line - signal
    return macd_line, signal, hist

# ===================== VERİ =====================
def fetch(symbol):
    df = yf.download(symbol, period="240d", interval="1d", progress=False)
    df = df.dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

# ===================== ANALİZ + SKOR =====================
def analyze(df, name):
    close = df["close"]
    volume = df["volume"] if "volume" in df else None

    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e200 = ema(close, 200)

    macd_line, signal, hist = macd(close)
    r = rsi(close)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0

    # --- Trend (30) ---
    if close.iloc[-1] > e20.iloc[-1] > e50.iloc[-1]:
        score += 30
        trend = "🟢 UP"
    elif close.iloc[-1] < e20.iloc[-1] < e50.iloc[-1]:
        score += 5
        trend = "🔴 DOWN"
    else:
        score += 15
        trend = "🟡 NÖTR"

    # --- MACD (25) ---
    if macd_line.iloc[-1] > signal.iloc[-1]:
        score += 15
        macd_state = "🟢"
    else:
        score += 5
        macd_state = "🔴"

    if hist.iloc[-1] > hist.iloc[-2]:
        score += 10
        hist_state = "↗️"
    else:
        hist_state = "↘️"

    # --- RSI (20) ---
    rsi_val = r.iloc[-1]
    if 45 <= rsi_val <= 65:
        score += 20
        rsi_state = f"{rsi_val:.1f} (sağlıklı)"
    elif rsi_val > 70:
        score += 5
        rsi_state = f"{rsi_val:.1f} (aşırı alım ⚠️)"
    elif rsi_val < 30:
        score += 10
        rsi_state = f"{rsi_val:.1f} (aşırı satım)"
    else:
        score += 10
        rsi_state = f"{rsi_val:.1f}"

    # --- Momentum (15) ---
    change_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
    if change_1d > 0:
        score += 15
    else:
        score += 5

    # --- Hacim (sadece BTC) (10) ---
    vol_state = ""
    if name == "BTC" and volume is not None:
        vol_ratio = volume.iloc[-1] / volume.rolling(20).mean().iloc[-1]
        if vol_ratio > 1:
            score += 10
            vol_state = f"Hacim: {vol_ratio:.2f}x"
        else:
            vol_state = f"Hacim: {vol_ratio:.2f}x"

    return {
        "name": name,
        "close": close.iloc[-1],
        "score": score,
        "trend": trend,
        "macd": macd_state,
        "hist": hist_state,
        "rsi": rsi_state,
        "change": change_1d,
        "volume": vol_state
    }

# ===================== TELEGRAM =====================
def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    })

# ===================== MAIN =====================
def main():
    gold = analyze(fetch(SYMBOLS["ALTIN"]), "ALTIN")
    silver = analyze(fetch(SYMBOLS["GÜMÜŞ"]), "GÜMÜŞ")
    btc = analyze(fetch(SYMBOLS["BTC"]), "BTC")

    # --- Oranlar ---
    gold_silver = gold["close"] / silver["close"]
    gold_btc = gold["close"] / btc["close"]

    gs_state = "ALTIN ÖNDE" if gold["score"] > silver["score"] else "GÜMÜŞ ÖNDE"
    gb_state = "RISK-OFF" if gold_btc > (gold["close"] / btc["close"]) else "RISK-ON"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = f"""
📊 GÜNLÜK ALTIN / GÜMÜŞ / BTC ANALİZİ
🕛 12:00 TR | {now}

🟢 ALTIN — Skor: {gold['score']}
• Trend: {gold['trend']}
• MACD: {gold['macd']} {gold['hist']}
• RSI: {gold['rsi']}

🟡 GÜMÜŞ — Skor: {silver['score']}
• Trend: {silver['trend']}
• MACD: {silver['macd']} {silver['hist']}
• RSI: {silver['rsi']}

🟢 BTC — Skor: {btc['score']}
• Trend: {btc['trend']}
• MACD: {btc['macd']} {btc['hist']}
• RSI: {btc['rsi']}
• {btc['volume']}

⚖️ Gold / Silver: {gold_silver:.2f} → {gs_state}
🔁 Gold / BTC: {gold_btc:.4f} → {gb_state}

🧠 SONUÇ:
{ 'Altın güvenli liman olarak önde.' if gold['score'] > silver['score'] and gold['score'] > btc['score']
else 'Risk iştahı yüksek, BTC veya gümüş daha önde.' }
""".strip()

    send(msg)

if __name__ == "__main__":
    main()
