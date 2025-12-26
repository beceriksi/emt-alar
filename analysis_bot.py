import os
import requests
import pandas as pd
from datetime import datetime, timezone
import yfinance as yf

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = {
    "ALTIN": "GC=F",
    "GÜMÜŞ": "SI=F",
    "BTC": "BTC-USD",
    "DXY": "DX-Y.NYB",     # Dollar Index
    "US10Y": "^TNX"        # US 10Y Yield
}

# ===================== INDICATORS =====================
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

    # MultiIndex FIX (GitHub Actions'ta sık olur)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    return df

# ===================== ANALYZE =====================
def analyze(df, name):
    close = df["close"]
    vol = df["volume"] if "volume" in df else None

    e20, e50 = ema(close, 20), ema(close, 50)
    m, s, h = macd(close)
    r = rsi(close)

    # Core states
    trend_up = (close.iloc[-1] > e20.iloc[-1] > e50.iloc[-1])
    trend_down = (close.iloc[-1] < e20.iloc[-1] < e50.iloc[-1])
    trend = "🟢 UP" if trend_up else ("🔴 DOWN" if trend_down else "🟡 NÖTR")

    macd_pos = (m.iloc[-1] > s.iloc[-1])
    macd_state = "🟢" if macd_pos else "🔴"

    hist_up = (h.iloc[-1] > h.iloc[-2])
    hist_state = "↗️" if hist_up else "↘️"

    rsi_val = float(r.iloc[-1])
    if rsi_val >= 70:
        rsi_state = f"{rsi_val:.1f} (aşırı alım ⚠️)"
    elif rsi_val <= 30:
        rsi_state = f"{rsi_val:.1f} (aşırı satım ⚠️)"
    else:
        rsi_state = f"{rsi_val:.1f}"

    # Score (0-100)
    score = 0

    # Trend (30)
    if trend_up:
        score += 30
    elif trend_down:
        score += 5
    else:
        score += 15

    # MACD (25)
    score += 15 if macd_pos else 5
    score += 10 if hist_up else 0

    # RSI (20)
    if 45 <= rsi_val <= 65:
        score += 20
    elif rsi_val > 70:
        score += 5
    elif rsi_val < 30:
        score += 10
    else:
        score += 10

    # Momentum (15) - 1D change
    chg = (close.iloc[-1] / close.iloc[-2] - 1) * 100
    score += 15 if chg > 0 else 5

    # Volume (BTC only) (10)
    vol_state = ""
    vol_ratio = None
    if name == "BTC" and vol is not None:
        vma = vol.rolling(20).mean().iloc[-1]
        if vma and vma > 0:
            vol_ratio = float(vol.iloc[-1] / vma)
            score += 10 if vol_ratio > 1 else 0
            vol_state = f"Hacim: {vol_ratio:.2f}x"
        else:
            vol_state = "Hacim: -"

    return {
        "name": name,
        "close": float(close.iloc[-1]),
        "score": int(round(score)),
        "trend": trend,
        "trend_up": trend_up,
        "macd": macd_state,
        "macd_pos": macd_pos,
        "hist": hist_state,
        "hist_up": hist_up,
        "rsi": rsi_state,
        "rsi_val": rsi_val,
        "chg": float(chg),
        "volume": vol_state,
        "vol_ratio": vol_ratio
    }

# ===================== BIAS LOGIC =====================
def bias_label(asset, score, trend_up, rsi_val, macd_pos, hist_up, macro_support, macro_oppose):
    """
    Net, yoruma kapalı karar etiketi.
    - LONG: trend+momentum sağlıklı + RSI aşırı alım değil + makro karşı değil
    - NO TRADE: trend iyi ama RSI şişkin / kararsız
    - SHORT/KÂR AL: skor düşük veya RSI çok şişkin + momentum zayıflıyor veya makro ters
    """
    # Hard short triggers (özellikle altın/gümüş için)
    if macro_oppose and score < 60:
        return "🔴 SHORT BIAS / KÂR AL"

    if rsi_val >= 75 and (not hist_up or not macd_pos):
        return "🔴 SHORT BIAS / KÂR AL"

    # Long conditions
    if score >= 70 and trend_up and macd_pos and (40 <= rsi_val <= 65) and (not macro_oppose):
        return "🟢 LONG BIAS"

    # No-trade zone (trend var ama şişkin/kararsız)
    if score >= 60 and trend_up and (rsi_val >= 70):
        return "🟡 NO TRADE / BEKLE"

    # BTC için de aynı mantık: düşük skor = riskli
    if score < 55:
        return "🔴 SHORT BIAS / KÂR AL"

    return "🟡 NO TRADE / BEKLE"

# ===================== TELEGRAM =====================
def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True}, timeout=20)
    r.raise_for_status()

# ===================== MAIN =====================
def main():
    gold = analyze(fetch(SYMBOLS["ALTIN"]), "ALTIN")
    silver = analyze(fetch(SYMBOLS["GÜMÜŞ"]), "GÜMÜŞ")
    btc = analyze(fetch(SYMBOLS["BTC"]), "BTC")

    dxy = fetch(SYMBOLS["DXY"])
    us10 = fetch(SYMBOLS["US10Y"])

    dxy_up = dxy["close"].iloc[-1] > ema(dxy["close"], 20).iloc[-1]
    us10_up = us10["close"].iloc[-1] > ema(us10["close"], 20).iloc[-1]

    dxy_trend = "⬆️" if dxy_up else "⬇️"
    us10_trend = "⬆️" if us10_up else "⬇️"

    # Makro etkisi (skora yansır)
    macro_note_lines = []
    if dxy_up:
        gold["score"] -= 8
        silver["score"] -= 6
        macro_note_lines.append("• DXY ⬆️ (emtia baskı)")
    else:
        gold["score"] += 5
        silver["score"] += 5
        macro_note_lines.append("• DXY ⬇️ (emtia destek)")

    if us10_up:
        gold["score"] -= 7
        macro_note_lines.append("• US10Y ⬆️ (altın negatif)")
    else:
        gold["score"] += 5
        macro_note_lines.append("• US10Y ⬇️ (altın destek)")

    # Score clamp
    for a in (gold, silver, btc):
        a["score"] = max(0, min(100, int(a["score"])))

    # Oranlar
    gs = gold["close"] / silver["close"]
    gb = gold["close"] / btc["close"]

    # Makro durum (bias kararında)
    macro_support = (not dxy_up) and (not us10_up)
    macro_oppose_gold = dxy_up or us10_up
    macro_oppose_silver = dxy_up  # gümüş için DXY daha direkt

    # Bias etiketleri
    gold_bias = bias_label("ALTIN", gold["score"], gold["trend_up"], gold["rsi_val"], gold["macd_pos"], gold["hist_up"],
                           macro_support=macro_support, macro_oppose=macro_oppose_gold)
    silver_bias = bias_label("GÜMÜŞ", silver["score"], silver["trend_up"], silver["rsi_val"], silver["macd_pos"], silver["hist_up"],
                             macro_support=macro_support, macro_oppose=macro_oppose_silver)
    btc_bias = bias_label("BTC", btc["score"], btc["trend_up"], btc["rsi_val"], btc["macd_pos"], btc["hist_up"],
                          macro_support=False, macro_oppose=False)

    # Sonuç cümlesi (tek satır, net)
    if "🔴" in btc_bias and ("🟢" in gold_bias or "🟡" in gold_bias):
        final_line = "🧠 SONUÇ: BTC zayıf → risk-off. Emtia güçlü ama aşırı alım varsa kovalamadan kaçın."
    elif "🟢" in btc_bias:
        final_line = "🧠 SONUÇ: Risk-on eğilimi var. BTC daha avantajlı."
    else:
        final_line = "🧠 SONUÇ: Kararsız görünüm. Acele işlem yok."

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = f"""
📊 GÜNLÜK ALTIN / GÜMÜŞ / BTC
🕛 12:00 TR | {now}

🟢 ALTIN — Skor: {gold['score']}
• Trend: {gold['trend']}
• MACD: {gold['macd']} {gold['hist']}
• RSI: {gold['rsi']}
🎯 {gold_bias}

🟡 GÜMÜŞ — Skor: {silver['score']}
• Trend: {silver['trend']}
• MACD: {silver['macd']} {silver['hist']}
• RSI: {silver['rsi']}
🎯 {silver_bias}

🟢 BTC — Skor: {btc['score']}
• Trend: {btc['trend']}
• MACD: {btc['macd']} {btc['hist']}
• RSI: {btc['rsi']}
• {btc['volume']}
🎯 {btc_bias}

🌍 MAKRO:
• DXY: {dxy_trend}
• US10Y: {us10_trend}
{chr(10).join(macro_note_lines)}

⚖️ Gold / Silver: {gs:.2f}
🔁 Gold / BTC: {gb:.4f}

{final_line}
""".strip()

    send(msg)

if __name__ == "__main__":
    main()
