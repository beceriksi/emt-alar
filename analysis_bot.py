import os
import requests
import pandas as pd
from datetime import datetime, timezone
import yfinance as yf

# ===================== AYARLAR =====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = {
    "ALTIN": "GC=F",
    "GÜMÜŞ": "SI=F",
    "BTC": "BTC-USD",
    "DXY": "DX-Y.NYB",     # Dollar Index
    "US10Y": "^TNX"        # US 10Y Yield
}

# ===================== GÖSTERGELER =====================
def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/p, adjust=False).mean()
    al = l.ewm(alpha=1/p, adjust=False).mean()
    rs = ag / al.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

def macd(s):
    m = ema(s, 12) - ema(s, 26)
    sig = ema(m, 9)
    hist = m - sig
    return m, sig, hist

def fetch(sym):
    df = yf.download(sym, period="300d", interval="1d", progress=False)
    df = df.dropna()
    df.columns = [c.lower() for c in df.columns]
    return df

# ===================== ANALİZ =====================
def analyze(df, name):
    close = df["close"]
    vol = df["volume"] if "volume" in df else None

    e20, e50, e200 = ema(close,20), ema(close,50), ema(close,200)
    m, s, h = macd(close)
    r = rsi(close)

    score = 0

    # TREND (30)
    if close.iloc[-1] > e20.iloc[-1] > e50.iloc[-1]:
        score += 30
        trend = "🟢 UP"
    elif close.iloc[-1] < e20.iloc[-1] < e50.iloc[-1]:
        score += 5
        trend = "🔴 DOWN"
    else:
        score += 15
        trend = "🟡 NÖTR"

    # MACD (25)
    score += 15 if m.iloc[-1] > s.iloc[-1] else 5
    hist = "↗️" if h.iloc[-1] > h.iloc[-2] else "↘️"
    score += 10 if hist == "↗️" else 0

    # RSI (20)
    rsi_val = r.iloc[-1]
    if 45 <= rsi_val <= 65:
        score += 20
        rsi_state = f"{rsi_val:.1f} (sağlıklı)"
    elif rsi_val > 70:
        score += 5
        rsi_state = f"{rsi_val:.1f} (aşırı alım ⚠️)"
    else:
        score += 10
        rsi_state = f"{rsi_val:.1f}"

    # MOMENTUM (15)
    chg = (close.iloc[-1] / close.iloc[-2] - 1) * 100
    score += 15 if chg > 0 else 5

    # HACİM (BTC) (10)
    vol_state = ""
    if name == "BTC" and vol is not None:
        vr = vol.iloc[-1] / vol.rolling(20).mean().iloc[-1]
        if vr > 1:
            score += 10
        vol_state = f"Hacim: {vr:.2f}x"

    return {
        "name": name,
        "close": close.iloc[-1],
        "score": score,
        "trend": trend,
        "rsi": rsi_state,
        "macd": "🟢" if m.iloc[-1] > s.iloc[-1] else "🔴",
        "hist": hist,
        "volume": vol_state
    }

# ===================== TELEGRAM =====================
def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True}
    )

# ===================== MAIN =====================
def main():
    gold = analyze(fetch(SYMBOLS["ALTIN"]), "ALTIN")
    silver = analyze(fetch(SYMBOLS["GÜMÜŞ"]), "GÜMÜŞ")
    btc = analyze(fetch(SYMBOLS["BTC"]), "BTC")

    dxy_df = fetch(SYMBOLS["DXY"])
    us10_df = fetch(SYMBOLS["US10Y"])

    dxy_trend = "⬆️" if dxy_df["close"].iloc[-1] > ema(dxy_df["close"],20).iloc[-1] else "⬇️"
    us10_trend = "⬆️" if us10_df["close"].iloc[-1] > ema(us10_df["close"],20).iloc[-1] else "⬇️"

    # MAKRO PUAN ETKİSİ
    macro_note = ""
    if dxy_trend == "⬆️":
        gold["score"] -= 8
        silver["score"] -= 6
        macro_note += "• DXY güçlü (emtia baskı)\n"
    else:
        gold["score"] += 5
        silver["score"] += 5

    if us10_trend == "⬆️":
        gold["score"] -= 7
        macro_note += "• US10Y yükseliyor (altın negatif)\n"
    else:
        gold["score"] += 5

    gs = gold["close"] / silver["close"]
    gs_state = "ALTIN ÖNDE" if gold["score"] > silver["score"] else "GÜMÜŞ ÖNDE"

    gb = gold["close"] / btc["close"]
    gb_state = "RISK-OFF" if gb > (gold["close"]/btc["close"]) else "RISK-ON"

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
• RSI: {btc['rsi']}
• {btc['volume']}

🌍 MAKRO DURUM:
• DXY: {dxy_trend}
• US10Y: {us10_trend}
{macro_note if macro_note else "• Makro nötr"}

⚖️ Gold / Silver: {gs:.2f} → {gs_state}
🔁 Gold / BTC: {gb:.4f} → {gb_state}

🧠 SONUÇ:
Makro + teknik birlikte değerlendirildi. Ani alım için acele edilmemeli.
""".strip()

    send(msg)

if __name__ == "__main__":
    main()
