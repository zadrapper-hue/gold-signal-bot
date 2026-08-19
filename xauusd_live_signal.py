"""
XAUUSD (Gold) Live Signal Generator (พร้อมแจ้งเตือน + SL/TP แบบคม)
=====================================================================
กลยุทธ์: EMA Trend Filter + RSI Momentum + Pullback Entry + Candle Confirmation
         + SL แบบอิงโครงสร้างราคา (swing high/low) + TP ตาม Risk:Reward

จุดเข้าจะแม่นขึ้นเพราะต้องผ่านเงื่อนไข 6 ชั้น:
  1. เทรนด์ถูกทาง (ราคาเทียบ EMA200)
  2. โมเมนตัมสนับสนุน (RSI อยู่ในช่วงที่กำหนด)
  3. ราคาต้องย่อกลับมาใกล้ EMA21 ก่อน (ไม่ไล่ราคาที่วิ่งไปไกลแล้ว)
  4. มีแท่งเทียนยืนยันทิศทางจริง (ปิดทะลุแท่งก่อนหน้า)
  5. MACD อยู่ฝั่งเดียวกับทิศทางที่จะเข้า (เปิด/ปิดได้ที่ ENABLE_MACD_FILTER)
  6. ราคาไม่ยืดเกิน Bollinger Band ไปแล้ว (เปิด/ปิดได้ที่ ENABLE_BB_FILTER)

SL สั้นลงเพราะอิงจุด swing high/low ล่าสุด แทนการคูณ ATR คงที่แบบเดิม
TP คำนวณจาก Risk:Reward Ratio (ค่าเริ่มต้น 1:2.5) แทนการคูณ ATR ตรงๆ

วิธีใช้:
1. ติดตั้งไลบรารีที่ต้องใช้ (รันครั้งเดียว):
   py -m pip install yfinance pandas numpy requests --break-system-packages

2. ตั้งค่า Telegram (ไม่บังคับ — ถ้าไม่ตั้ง จะแจ้งเตือนแค่เสียง+ป๊อปอัพบนเครื่อง):
   แก้ TELEGRAM_BOT_TOKEN และ TELEGRAM_CHAT_ID ด้านล่างให้เป็นของคุณเอง

3. รันครั้งเดียว ดูสัญญาณตอนนี้:
   py xauusd_live_signal.py

4. รันต่อเนื่องแบบ auto-refresh ทุก N นาที พร้อมแจ้งเตือนเมื่อสัญญาณเปลี่ยน:
   py xauusd_live_signal.py --loop --interval 15

⚠️ ข้อสำคัญ:
- นี่คือเครื่องมือช่วยดูสัญญาณเชิงเทคนิค ไม่ใช่คำแนะนำการลงทุน และไม่ใช่การซื้อขายอัตโนมัติ
  (สคริปต์นี้แค่ "บอกสัญญาณ" ไม่ได้ส่งคำสั่งเทรดให้อัตโนมัติ)
- ราคาจาก Yahoo Finance (GC=F, Gold Futures) อาจมีความหน่วง 15-20 นาที และต่างจากราคา
  XAUUSD ของโบรกเกอร์ forex เล็กน้อย (ใช้เพื่อดูภาพรวมเทรนด์ ไม่ใช่ราคาซื้อขายจริง)
- ต้องรันบนเครื่องที่ต่อเน็ตปกติ (ไม่ใช่ในระบบแซนด์บ็อกซ์ที่จำกัดโดเมน)
- แจ้งเตือนป๊อปอัพ/เสียงบี๊บทำงานบน Windows เท่านั้น
"""

import argparse
import ctypes
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    requests = None

try:
    import winsound
    IS_WINDOWS = True
except ImportError:
    IS_WINDOWS = False


# ============================================================
# 🔔 CONFIG แจ้งเตือน - ปรับค่าตรงนี้
# ============================================================
ENABLE_DESKTOP_ALERT = True     # เสียงบี๊บ + ป๊อปอัพบนเครื่อง (Windows เท่านั้น — ข้ามอัตโนมัติเมื่อรันบนคลาวด์)
ENABLE_TELEGRAM_ALERT = True    # แจ้งเตือนผ่าน Telegram

# อ่านจาก Environment Variable ก่อน (สำหรับรันบน GitHub Actions/คลาวด์)
# ถ้าไม่มี env var จะใช้ค่าที่ใส่ไว้ตรงนี้แทน (สำหรับรันบนเครื่องตัวเอง)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8852179910:AAEQmygULu6LY7SlA_iHkYPdrqcmp9FPG88")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6293526076")

try:
    import yfinance as yf
except ImportError:
    raise SystemExit(
        "ยังไม่ได้ติดตั้ง yfinance — รันคำสั่งนี้ก่อน:\n"
        "    pip install yfinance pandas numpy --break-system-packages"
    )

# ============================================================
# ⚙️  CONFIG - ปรับค่าตรงนี้ (ต้องตรงกับที่ใช้ตอน backtest)
# ============================================================
TICKER = "XAUUSD=X"      # Gold Spot บน Yahoo Finance (ทางเลือก: "GC=F" สำหรับ futures)
INTERVAL = "1h"          # กรอบเวลาแท่งเทียน: 1m, 5m, 15m, 1h, 1d
LOOKBACK = "60d"         # ดึงข้อมูลย้อนหลังเท่าไหร่ (ต้องพอสำหรับ EMA 200)

EMA_TREND_PERIOD = 200
EMA_PULLBACK_PERIOD = 21     # EMA เร็ว ใช้หาจุดเข้าแบบ pullback
RSI_PERIOD = 14
RSI_BUY_MIN = 50
RSI_SELL_MAX = 50
ATR_PERIOD = 14

# --- SL/TP แบบใหม่: อิงโครงสร้างราคา (swing high/low) แทน ATR คงที่ ---
SWING_LOOKBACK = 10          # หา swing high/low จากกี่แท่งเทียนย้อนหลัง
SL_BUFFER_ATR_MULT = 0.3     # เผื่อ SL เลย swing point อีกนิด กัน noise (คูณด้วย ATR)
TP_RR_RATIO = 2.5            # Take Profit = ความเสี่ยง (risk) x เท่านี้ → R:R
PULLBACK_MAX_DIST_ATR = 0.5  # ราคาต้องอยู่ใกล้ EMA21 ไม่เกินกี่เท่าของ ATR ถึงจะนับว่าเป็น "pullback"

# --- ตัวกรองเสริม: MACD และ Bollinger Bands (เปิด/ปิดแยกกันได้) ---
ENABLE_MACD_FILTER = True
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ENABLE_BB_FILTER = True
BB_PERIOD = 20
BB_STD_MULT = 2.0

# --- โหมด Range-Trading (RSI x Williams %R crossover + จำกัดในกรอบ Bollinger Bands) ---
# ใช้ ADX วัดว่าตลาดตอนนี้ "มีเทรนด์" หรือ "sideways" แล้วสลับโหมดอัตโนมัติ
ENABLE_RANGE_MODE = True
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 20     # ADX >= ค่านี้ = ถือว่ามีเทรนด์ → ใช้โหมดเทรนด์เดิม
                              # ADX < ค่านี้ = sideways → สลับไปใช้โหมด range-trading
WILLIAMS_R_PERIOD = 14
RANGE_RSI_MID = 50            # เส้นกลางของ RSI (0-100) ใช้เทียบกับ Williams %R ที่ปรับสเกลแล้ว


# ============================================================
# 📊 อินดิเคเตอร์ (เหมือนกับสคริปต์ backtest)
# ============================================================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def williams_r(df: pd.DataFrame, period: int) -> pd.Series:
    """Williams %R: สเกล -100 ถึง 0 (ค่ายิ่งใกล้ 0 = overbought, ยิ่งใกล้ -100 = oversold)"""
    highest_high = df["High"].rolling(window=period).max()
    lowest_low = df["Low"].rolling(window=period).min()
    return -100 * (highest_high - df["Close"]) / (highest_high - lowest_low)


def williams_r_rescaled(df: pd.DataFrame, period: int) -> pd.Series:
    """แปลง Williams %R จากสเกล -100..0 ให้เป็น 0..100 แบบเดียวกับ RSI เพื่อเทียบ/หาจุดตัดกันได้ตรงๆ"""
    return williams_r(df, period) + 100


def adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Average Directional Index — วัดความแรงของเทรนด์ (ไม่บอกทิศทาง แค่บอกว่า 'มีเทรนด์' แค่ไหน)"""
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)
    atr_smooth = tr.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_smooth

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def macd(series: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """คืนค่า (macd_line, signal_line, histogram)"""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int, std_mult: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """คืนค่า (upper_band, middle_band/SMA, lower_band)"""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return upper, middle, lower


# ============================================================
# 📥 ดึงข้อมูลราคาสด (พร้อม retry — Yahoo Finance มักบล็อก IP ของ cloud/data center
# ชั่วคราวเมื่อยิง request ถี่ ต้องลองใหม่หลายครั้งและหน่วงเวลาไว้)
# ============================================================
FETCH_MAX_RETRIES = 4
FETCH_RETRY_DELAY_SEC = 15


def fetch_data() -> pd.DataFrame:
    last_error = None
    for attempt in range(1, FETCH_MAX_RETRIES + 1):
        try:
            df = yf.download(TICKER, period=LOOKBACK, interval=INTERVAL, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
            last_error = RuntimeError("ได้ข้อมูลว่างเปล่ากลับมา (empty DataFrame)")
        except Exception as e:
            last_error = e

        if attempt < FETCH_MAX_RETRIES:
            print(f"⚠️  ดึงข้อมูลไม่สำเร็จ (ครั้งที่ {attempt}/{FETCH_MAX_RETRIES}): {last_error}")
            print(f"   รอ {FETCH_RETRY_DELAY_SEC} วินาทีแล้วลองใหม่...")
            time.sleep(FETCH_RETRY_DELAY_SEC)

    raise RuntimeError(
        f"ดึงข้อมูล {TICKER} ไม่ได้หลังลอง {FETCH_MAX_RETRIES} ครั้ง (สาเหตุล่าสุด: {last_error}) "
        f"— Yahoo Finance อาจบล็อก IP ชั่วคราว ลองรันใหม่ภายหลัง"
    )


# ============================================================
# 🧮 คำนวณสัญญาณปัจจุบัน
# ============================================================
def is_bullish_confirmation(df: pd.DataFrame) -> bool:
    """แท่งเทียนล่าสุดยืนยันขาขึ้น: ปิดสูงกว่าเปิด และปิดเหนือจุดสูงสุดของแท่งก่อนหน้า"""
    last, prev = df.iloc[-1], df.iloc[-2]
    bullish_candle = last["Close"] > last["Open"]
    breaks_prev_high = last["Close"] > prev["High"]
    return bool(bullish_candle and breaks_prev_high)


def is_bearish_confirmation(df: pd.DataFrame) -> bool:
    """แท่งเทียนล่าสุดยืนยันขาลง: ปิดต่ำกว่าเปิด และปิดใต้จุดต่ำสุดของแท่งก่อนหน้า"""
    last, prev = df.iloc[-1], df.iloc[-2]
    bearish_candle = last["Close"] < last["Open"]
    breaks_prev_low = last["Close"] < prev["Low"]
    return bool(bearish_candle and breaks_prev_low)



# ============================================================
# 🧮 Confluence Score — รวมทุกตัวชี้วัดเข้าด้วยกัน โดยให้น้ำหนักตาม ADX
# แทนการสลับโหมดแบบเปิด/ปิด ตัวชี้วัดฝั่งเทรนด์กับฝั่ง range จะ "ถ่วงน้ำหนัก"
# ตามความแรงของเทรนด์ (ADX) แล้วรวมเป็นคะแนนเดียว
# ============================================================
CONFLUENCE_BUY_THRESHOLD = 0.5     # คะแนนรวม (-1 ถึง +1) ต้อง >= ค่านี้ ถึงจะออกสัญญาณ BUY
CONFLUENCE_SELL_THRESHOLD = -0.5   # คะแนนรวม ต้อง <= ค่านี้ ถึงจะออกสัญญาณ SELL
ADX_FULL_TREND_WEIGHT = 40         # ADX ที่ถือว่า "เทรนด์เต็มร้อย" (น้ำหนักฝั่งเทรนด์ = 1.0)


def compute_signal(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["ema_trend"] = ema(df["Close"], EMA_TREND_PERIOD)
    df["ema_pullback"] = ema(df["Close"], EMA_PULLBACK_PERIOD)
    df["rsi"] = rsi(df["Close"], RSI_PERIOD)
    df["atr"] = atr(df, ATR_PERIOD)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["Close"], MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(df["Close"], BB_PERIOD, BB_STD_MULT)
    df["adx"] = adx(df, ADX_PERIOD)
    df["wr_rescaled"] = williams_r_rescaled(df, WILLIAMS_R_PERIOD)

    last, prev = df.iloc[-1], df.iloc[-2]
    price = float(last["Close"])
    ema_val = float(last["ema_trend"])
    ema_pb_val = float(last["ema_pullback"])
    rsi_val = float(last["rsi"])
    atr_val = float(last["atr"])
    macd_line = float(last["macd"])
    macd_sig = float(last["macd_signal"])
    bb_upper = float(last["bb_upper"])
    bb_lower = float(last["bb_lower"])
    bb_mid = float(last["bb_mid"])
    adx_val = float(last["adx"])
    wr_now, wr_prev = float(last["wr_rescaled"]), float(prev["wr_rescaled"])
    rsi_prev = float(prev["rsi"])

    core_ready = not (pd.isna(ema_val) or pd.isna(rsi_val) or pd.isna(atr_val) or pd.isna(ema_pb_val))
    if not core_ready:
        return {"signal": "NOT_ENOUGH_DATA", "reason": "ข้อมูลย้อนหลังไม่พอสำหรับคำนวณ EMA/RSI/ATR"}

    uptrend = price > ema_val
    downtrend = price < ema_val

    # --- น้ำหนักตาม ADX: เทรนด์แรง → เน้นตัวชี้วัดฝั่งเทรนด์ / sideways → เน้นฝั่ง range (RSI x Williams%R) ---
    if pd.isna(adx_val):
        trend_weight, range_weight = 0.5, 0.5
        market_regime = "ไม่ทราบ (ADX ยังไม่พอ)"
    else:
        trend_weight = min(max(adx_val / ADX_FULL_TREND_WEIGHT, 0.0), 1.0)
        range_weight = 1.0 - trend_weight
        market_regime = "มีเทรนด์ (ADX สูง)" if adx_val >= ADX_TREND_THRESHOLD else "Sideways (ADX ต่ำ)"

    # --- ฝั่งเทรนด์: EMA200 + RSI momentum + candle confirm + MACD + pullback proximity ---
    bull_confirm = is_bullish_confirmation(df)
    bear_confirm = is_bearish_confirmation(df)
    dist_from_pullback_ema = abs(price - ema_pb_val)
    near_pullback_ema = dist_from_pullback_ema <= (PULLBACK_MAX_DIST_ATR * atr_val)

    trend_votes = [1.0 if uptrend else -1.0, 1.0 if rsi_val > 50 else -1.0]
    if bull_confirm:
        trend_votes.append(1.0)
    elif bear_confirm:
        trend_votes.append(-1.0)
    if ENABLE_MACD_FILTER and not pd.isna(macd_line) and not pd.isna(macd_sig):
        trend_votes.append(1.0 if macd_line > macd_sig else -1.0)
    trend_votes.append(1.0 if near_pullback_ema and uptrend else (-1.0 if near_pullback_ema and downtrend else 0.0))
    trend_score = sum(trend_votes) / len(trend_votes)

    # --- ฝั่ง range: RSI x Williams %R ตัดกัน ---
    range_ready = not (pd.isna(rsi_prev) or pd.isna(wr_prev) or pd.isna(wr_now))
    crossed_up = range_ready and rsi_prev <= wr_prev and rsi_val > wr_now
    crossed_down = range_ready and rsi_prev >= wr_prev and rsi_val < wr_now
    range_score = 1.0 if crossed_up else (-1.0 if crossed_down else 0.0)

    combined_score = trend_weight * trend_score + range_weight * range_score

    # --- ตัวกรองความปลอดภัยร่วม (ใช้ทั้งสองฝั่งเสมอ): ราคาต้องไม่ยืดเกินกรอบ Bollinger Bands ---
    bb_ready = not (pd.isna(bb_upper) or pd.isna(bb_lower))
    price_within_bb = (bb_lower <= price <= bb_upper) if (ENABLE_BB_FILTER and bb_ready) else True

    # --- หา swing high/low ล่าสุดสำหรับ SL แบบอิงโครงสร้าง ---
    recent = df.iloc[-(SWING_LOOKBACK + 1):-1]
    swing_low = float(recent["Low"].min())
    swing_high = float(recent["High"].max())

    result = {
        "time": df.index[-1],
        "price": price,
        "ema200": ema_val,
        "ema21": ema_pb_val,
        "rsi": rsi_val,
        "atr": atr_val,
        "macd": macd_line,
        "macd_signal": macd_sig,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "wr_rescaled": wr_now,
        "trend": "ขาขึ้น (Uptrend)" if uptrend else "ขาลง (Downtrend)",
        "adx": adx_val,
        "market_regime": market_regime,
        "trend_weight": trend_weight,
        "range_weight": range_weight,
        "trend_score": trend_score,
        "range_score": range_score,
        "combined_score": combined_score,
        "price_within_bb": price_within_bb,
    }

    buy_ok = combined_score >= CONFLUENCE_BUY_THRESHOLD and price_within_bb
    sell_ok = combined_score <= CONFLUENCE_SELL_THRESHOLD and price_within_bb

    if buy_ok:
        sl = swing_low - SL_BUFFER_ATR_MULT * atr_val
        risk = price - sl
        result["signal"] = "BUY / LONG"
        result["stop_loss"] = sl
        result["take_profit"] = price + risk * TP_RR_RATIO
        result["risk_points"] = risk
        result["rr_ratio"] = TP_RR_RATIO
    elif sell_ok:
        sl = swing_high + SL_BUFFER_ATR_MULT * atr_val
        risk = sl - price
        result["signal"] = "SELL / SHORT"
        result["stop_loss"] = sl
        result["take_profit"] = price - risk * TP_RR_RATIO
        result["risk_points"] = risk
        result["rr_ratio"] = TP_RR_RATIO
    else:
        result["signal"] = "NO TRADE / รอสัญญาณ"
        reason = []
        if not price_within_bb:
            reason.append("ราคาทะลุกรอบ Bollinger Bands ไปแล้ว (อาจ overextended รอย่อก่อน)")
        reason.append(
            f"คะแนนรวม {combined_score:+.2f} ยังไม่ถึงเกณฑ์ (ต้อง ≥{CONFLUENCE_BUY_THRESHOLD:+.2f} สำหรับ BUY "
            f"หรือ ≤{CONFLUENCE_SELL_THRESHOLD:+.2f} สำหรับ SELL)"
        )
        result["reason"] = " / ".join(reason)

    return result


# ============================================================
# 🔔 ฟังก์ชันแจ้งเตือน
# ============================================================
def send_desktop_alert(title: str, message: str):
    """เสียงบี๊บ + ป๊อปอัพ MessageBox บน Windows"""
    if not ENABLE_DESKTOP_ALERT:
        return
    if not IS_WINDOWS:
        print("⚠️  แจ้งเตือนแบบเสียง/ป๊อปอัพใช้ได้บน Windows เท่านั้น (ข้าม)")
        return
    try:
        # เสียงบี๊บ 3 ครั้ง
        for _ in range(3):
            winsound.Beep(1000, 400)
            time.sleep(0.15)
        # ป๊อปอัพ MessageBox (ไม่ต้องติดตั้งอะไรเพิ่ม เป็นของ Windows เอง)
        # 0x40 = icon info, 0x1000 = topmost (ขึ้นมาบนสุดเสมอ)
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1000)
    except Exception as e:
        print(f"⚠️  ส่งแจ้งเตือนบนเครื่องไม่สำเร็จ: {e}")


def send_telegram_alert(message: str):
    """ส่งข้อความแจ้งเตือนผ่าน Telegram Bot"""
    if not ENABLE_TELEGRAM_ALERT:
        return
    if requests is None:
        print("⚠️  ยังไม่ได้ติดตั้ง requests — รัน: py -m pip install requests --break-system-packages")
        return
    if "ใส่_TOKEN" in TELEGRAM_BOT_TOKEN or "ใส่_CHAT_ID" in TELEGRAM_CHAT_ID:
        print("⚠️  ยังไม่ได้ตั้งค่า TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ในสคริปต์ (ข้ามการแจ้งเตือน Telegram)")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️  ส่ง Telegram ไม่สำเร็จ: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"⚠️  ส่ง Telegram ไม่สำเร็จ: {e}")


def fire_alerts(result: dict):
    """เรียกแจ้งเตือนทุกช่องทางที่เปิดไว้ เมื่อมีสัญญาณ BUY/SELL"""
    signal = result["signal"]
    emoji = "🟢" if signal == "BUY / LONG" else "🔴"
    title = f"{emoji} สัญญาณทอง: {signal}"
    lines = [
        f"{emoji} {signal}",
        f"ราคา: {result['price']:.2f}",
        f"RSI: {result['rsi']:.1f}",
        f"Stop Loss: {result['stop_loss']:.2f}",
        f"Take Profit: {result['take_profit']:.2f}",
        f"เวลา: {result.get('time')}",
        "",
        "⚠️ สัญญาณเชิงเทคนิคเท่านั้น ไม่ใช่คำแนะนำการลงทุน",
    ]
    message = "\n".join(lines)

    send_desktop_alert(title, message)
    send_telegram_alert(message)


# ============================================================
# 🖨️  แสดงผล
# ============================================================
def print_signal(result: dict):
    print("=" * 55)
    print(f"🕐 เวลา: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  (แท่งล่าสุด: {result.get('time')})")
    print("=" * 55)

    if result["signal"] == "NOT_ENOUGH_DATA":
        print(f"⚠️  {result['reason']}")
        return

    regime = result.get("market_regime")
    adx_val = result.get("adx")
    if regime:
        adx_txt = f" (ADX={adx_val:.1f})" if adx_val is not None and not pd.isna(adx_val) else ""
        print(f"สภาพตลาด (Market Regime)    : {regime}{adx_txt}")
        print(f"น้ำหนักคะแนน               : เทรนด์ {result['trend_weight']*100:.0f}% / range {result['range_weight']*100:.0f}%")
        print("-" * 55)

    print(f"ราคาปัจจุบัน (XAUUSD proxy) : {result['price']:.2f}")
    print(f"EMA {EMA_TREND_PERIOD}                    : {result['ema200']:.2f}")
    print(f"EMA {EMA_PULLBACK_PERIOD} (pullback)          : {result['ema21']:.2f}")
    print(f"RSI {RSI_PERIOD}                      : {result['rsi']:.1f}")
    print(f"Williams %R (rescaled)     : {result['wr_rescaled']:.1f}")
    print(f"ATR {ATR_PERIOD}                      : {result['atr']:.2f}")
    if ENABLE_MACD_FILTER and not pd.isna(result.get("macd")):
        macd_state = "เหนือ signal (ขาขึ้น)" if result["macd"] > result["macd_signal"] else "ใต้ signal (ขาลง)"
        print(f"MACD                       : {result['macd']:.2f} vs signal {result['macd_signal']:.2f} ({macd_state})")
    if ENABLE_BB_FILTER and not pd.isna(result.get("bb_upper")):
        print(f"Bollinger Bands            : {result['bb_lower']:.2f} - {result['bb_mid']:.2f} - {result['bb_upper']:.2f}")
    print(f"ทิศทางเทรนด์                : {result['trend']}")
    print("-" * 55)
    print(f"📊 Trend Score  : {result['trend_score']:+.2f}   📊 Range Score : {result['range_score']:+.2f}")
    print(f"📊 Combined Score (ถ่วงน้ำหนักแล้ว) : {result['combined_score']:+.2f}")
    print("-" * 55)

    signal = result["signal"]
    if signal in ("BUY / LONG", "SELL / SHORT"):
        emoji = "🟢" if signal == "BUY / LONG" else "🔴"
        print(f"{emoji} สัญญาณ: {signal}")
        print(f"   Stop Loss   : {result['stop_loss']:.2f}  (ห่างจากราคา {result['risk_points']:.2f} จุด)")
        print(f"   Take Profit : {result['take_profit']:.2f}  (R:R = 1:{result['rr_ratio']})")
    else:
        print(f"⚪ สัญญาณ: {signal}")
        print(f"   เหตุผล: {result.get('reason', '-')}")

    print("=" * 55)
    print("⚠️  นี่คือสัญญาณเชิงเทคนิคเท่านั้น ไม่ใช่คำแนะนำการลงทุน")
    print("   ควรตรวจสอบข่าว/ปฏิทินเศรษฐกิจ (Fed, CPI, NFP) ประกอบก่อนตัดสินใจทุกครั้ง\n")


# ============================================================
# 💾 บันทึกสถานะล่าสุด (ไฟล์ JSON) - ใช้ตอนรันแบบครั้งเดียวต่อครั้ง (เช่นบน GitHub Actions)
# เก็บทั้ง "สัญญาณที่รอยืนยัน" (pending) และ "สัญญาณล่าสุดที่แจ้งเตือนไปแล้ว" (alerted)
# เพื่อกันแจ้งเตือนซ้ำ และกันสัญญาณสั่นไหวใกล้เกณฑ์ (whipsaw)
# ============================================================
STATE_FILE = "last_signal.txt"

# ต้องเห็นสัญญาณเดิมซ้ำติดกันกี่รอบ ถึงจะยอมส่งแจ้งเตือน (ยิ่งมาก ยิ่งแม่นแต่ช้าลง)
CONFIRMATION_BARS = 2


def load_state(use_file: bool) -> dict:
    default = {"pending_signal": None, "pending_count": 0, "last_alerted_signal": None}
    if not use_file:
        return default
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            data = json.loads(content)
            return {**default, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_state(state: dict, use_file: bool):
    if not use_file:
        return
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  บันทึกสถานะไม่สำเร็จ: {e}")


def update_state_and_check_alert(state: dict, current_signal: str | None) -> tuple[dict, bool]:
    """
    รับสัญญาณปัจจุบัน คืนค่า (state ใหม่, ควรส่งแจ้งเตือนไหม)
    ต้องเห็นสัญญาณเดียวกันซ้ำ CONFIRMATION_BARS รอบติดกัน และยังไม่เคยแจ้งเตือนสัญญาณนี้มาก่อน
    """
    actionable = current_signal in ("BUY / LONG", "SELL / SHORT")

    if not actionable:
        # สัญญาณหลุดจากโซนเข้าไม้แล้ว รีเซ็ตทั้ง pending และ alerted เพื่อให้รอบหน้าถ้าเจอสัญญาณใหม่ แจ้งได้อีก
        state["pending_signal"] = None
        state["pending_count"] = 0
        state["last_alerted_signal"] = None
        return state, False

    if current_signal == state.get("pending_signal"):
        state["pending_count"] = state.get("pending_count", 0) + 1
    else:
        state["pending_signal"] = current_signal
        state["pending_count"] = 1

    should_alert = (
        state["pending_count"] >= CONFIRMATION_BARS
        and current_signal != state.get("last_alerted_signal")
    )
    if should_alert:
        state["last_alerted_signal"] = current_signal

    return state, should_alert


# ============================================================
# ▶️  main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="XAUUSD Live Signal Generator")
    parser.add_argument("--loop", action="store_true", help="รันวนซ้ำอัตโนมัติ (ใช้ตอนรันบนเครื่องตัวเอง)")
    parser.add_argument("--interval", type=int, default=15, help="ความถี่รีเฟรช (นาที) เมื่อใช้ --loop")
    parser.add_argument("--test-alert", action="store_true", help="ทดสอบระบบแจ้งเตือนทันที (ไม่ต้องรอสัญญาณจริง)")
    parser.add_argument("--use-state-file", action="store_true",
                         help="อ่าน/บันทึกสถานะจากไฟล์ (ใช้ตอนรันบน GitHub Actions ที่แต่ละรอบเป็นโปรเซสใหม่)")
    args = parser.parse_args()

    if args.test_alert:
        print("🔔 กำลังทดสอบระบบแจ้งเตือน...")
        fake_result = {
            "signal": "BUY / LONG", "price": 4400.0, "rsi": 55.0,
            "stop_loss": 4380.0, "take_profit": 4430.0, "time": datetime.now(),
        }
        fire_alerts(fake_result)
        print("✅ ทดสอบเสร็จ — ถ้าไม่มีเสียง/ป๊อปอัพ/ข้อความ Telegram เด้งขึ้นมา ให้ตรวจสอบ CONFIG ด้านบนไฟล์")
        return

    state = load_state(args.use_state_file)

    def run_once():
        nonlocal state
        try:
            df = fetch_data()
            result = compute_signal(df)
            print_signal(result)

            current_signal = result.get("signal")
            state, should_alert = update_state_and_check_alert(state, current_signal)

            if should_alert:
                print(f"🔔 ยืนยันสัญญาณครบ {CONFIRMATION_BARS} รอบติดกันแล้ว — กำลังส่งแจ้งเตือน...")
                fire_alerts(result)
            elif current_signal in ("BUY / LONG", "SELL / SHORT"):
                print(f"⏳ พบสัญญาณ {current_signal} รอบที่ {state['pending_count']}/{CONFIRMATION_BARS} — รอยืนยันอีกรอบก่อนส่ง")

            save_state(state, args.use_state_file)
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาด: {e}")

    if args.loop:
        print(f"🔄 เริ่มรันแบบวนซ้ำทุก {args.interval} นาที (กด Ctrl+C เพื่อหยุด)")
        print(f"   จะแจ้งเตือนก็ต่อเมื่อเห็นสัญญาณเดิมซ้ำ {CONFIRMATION_BARS} รอบติดกัน (กันสัญญาณหลอก)\n")
        while True:
            run_once()
            time.sleep(args.interval * 60)
    else:
        run_once()


if __name__ == "__main__":
    main()
