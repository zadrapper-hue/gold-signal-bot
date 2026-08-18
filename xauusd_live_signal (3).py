"""
XAUUSD (Gold) Live Signal Generator (พร้อมแจ้งเตือน + SL/TP แบบคม)
=====================================================================
กลยุทธ์: EMA Trend Filter + RSI Momentum + Pullback Entry + Candle Confirmation
         + SL แบบอิงโครงสร้างราคา (swing high/low) + TP ตาม Risk:Reward

จุดเข้าจะแม่นขึ้นเพราะต้องผ่านเงื่อนไข 4 ชั้น:
  1. เทรนด์ถูกทาง (ราคาเทียบ EMA200)
  2. โมเมนตัมสนับสนุน (RSI อยู่ในช่วงที่กำหนด)
  3. ราคาต้องย่อกลับมาใกล้ EMA21 ก่อน (ไม่ไล่ราคาที่วิ่งไปไกลแล้ว)
  4. มีแท่งเทียนยืนยันทิศทางจริง (ปิดทะลุแท่งก่อนหน้า)

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


# ============================================================
# 📥 ดึงข้อมูลราคาสด
# ============================================================
def fetch_data() -> pd.DataFrame:
    df = yf.download(TICKER, period=LOOKBACK, interval=INTERVAL, progress=False)
    if df.empty:
        raise RuntimeError(
            f"ดึงข้อมูล {TICKER} ไม่ได้ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต หรือลอง TICKER อื่น เช่น 'XAUUSD=X'"
        )
    # yfinance บางเวอร์ชันคืน MultiIndex columns เมื่อดึงสัญลักษณ์เดียว — flatten ให้เรียบร้อย
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


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


def compute_signal(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["ema_trend"] = ema(df["Close"], EMA_TREND_PERIOD)
    df["ema_pullback"] = ema(df["Close"], EMA_PULLBACK_PERIOD)
    df["rsi"] = rsi(df["Close"], RSI_PERIOD)
    df["atr"] = atr(df, ATR_PERIOD)

    last = df.iloc[-1]
    price = float(last["Close"])
    ema_val = float(last["ema_trend"])
    ema_pb_val = float(last["ema_pullback"])
    rsi_val = float(last["rsi"])
    atr_val = float(last["atr"])

    if pd.isna(ema_val) or pd.isna(rsi_val) or pd.isna(atr_val) or pd.isna(ema_pb_val):
        return {"signal": "NOT_ENOUGH_DATA", "reason": "ข้อมูลย้อนหลังไม่พอสำหรับคำนวณ EMA/RSI/ATR"}

    uptrend = price > ema_val
    downtrend = price < ema_val

    # --- เงื่อนไข pullback: ราคาต้องใกล้ EMA21 (ไม่ไล่ราคาที่วิ่งไปไกลแล้ว) ---
    dist_from_pullback_ema = abs(price - ema_pb_val)
    near_pullback_ema = dist_from_pullback_ema <= (PULLBACK_MAX_DIST_ATR * atr_val)

    # --- เงื่อนไขโมเมนตัม ---
    rsi_long_ok = RSI_BUY_MIN < rsi_val < 70
    rsi_short_ok = 30 < rsi_val < RSI_SELL_MAX

    # --- เงื่อนไขแท่งเทียนยืนยัน ---
    bull_confirm = is_bullish_confirmation(df)
    bear_confirm = is_bearish_confirmation(df)

    long_ok = uptrend and rsi_long_ok and near_pullback_ema and bull_confirm
    short_ok = downtrend and rsi_short_ok and near_pullback_ema and bear_confirm

    # --- หา swing high/low ล่าสุดสำหรับ SL แบบอิงโครงสร้าง ---
    recent = df.iloc[-(SWING_LOOKBACK + 1):-1]  # ไม่รวมแท่งปัจจุบัน กันมองย้อนอนาคต
    swing_low = float(recent["Low"].min())
    swing_high = float(recent["High"].max())

    result = {
        "time": df.index[-1],
        "price": price,
        "ema200": ema_val,
        "ema21": ema_pb_val,
        "rsi": rsi_val,
        "atr": atr_val,
        "trend": "ขาขึ้น (Uptrend)" if uptrend else "ขาลง (Downtrend)",
        "near_pullback": near_pullback_ema,
        "bull_confirm": bull_confirm,
        "bear_confirm": bear_confirm,
    }

    if long_ok:
        sl = swing_low - SL_BUFFER_ATR_MULT * atr_val
        risk = price - sl
        result["signal"] = "BUY / LONG"
        result["stop_loss"] = sl
        result["take_profit"] = price + risk * TP_RR_RATIO
        result["risk_points"] = risk
        result["rr_ratio"] = TP_RR_RATIO
    elif short_ok:
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
        if not uptrend and not downtrend:
            reason.append("ราคาใกล้ EMA200 มาก ยังไม่มีทิศทางชัด")
        if uptrend and not rsi_long_ok:
            reason.append(f"เทรนด์ขึ้นแต่ RSI={rsi_val:.1f} อยู่นอกช่วง {RSI_BUY_MIN}-70")
        if downtrend and not rsi_short_ok:
            reason.append(f"เทรนด์ลงแต่ RSI={rsi_val:.1f} อยู่นอกช่วง 30-{RSI_SELL_MAX}")
        if (uptrend or downtrend) and not near_pullback_ema:
            reason.append(f"ราคาห่าง EMA{EMA_PULLBACK_PERIOD} เกินไป (รอราคาย่อกลับมาก่อน)")
        if uptrend and rsi_long_ok and near_pullback_ema and not bull_confirm:
            reason.append("รอแท่งเทียนยืนยันขาขึ้น (ยังไม่ปิดทะลุแท่งก่อนหน้า)")
        if downtrend and rsi_short_ok and near_pullback_ema and not bear_confirm:
            reason.append("รอแท่งเทียนยืนยันขาลง (ยังไม่ปิดทะลุแท่งก่อนหน้า)")
        result["reason"] = " / ".join(reason) if reason else "เงื่อนไขยังไม่ครบ"

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

    print(f"ราคาปัจจุบัน (XAUUSD proxy) : {result['price']:.2f}")
    print(f"EMA {EMA_TREND_PERIOD}                    : {result['ema200']:.2f}")
    print(f"EMA {EMA_PULLBACK_PERIOD} (pullback)          : {result['ema21']:.2f}")
    print(f"RSI {RSI_PERIOD}                      : {result['rsi']:.1f}")
    print(f"ATR {ATR_PERIOD}                      : {result['atr']:.2f}")
    print(f"ทิศทางเทรนด์                : {result['trend']}")
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
# 💾 บันทึกสัญญาณล่าสุด (ไฟล์) - ใช้ตอนรันแบบครั้งเดียวต่อครั้ง (เช่นบน GitHub Actions)
# เพื่อให้รู้ว่าสัญญาณ "เปลี่ยน" จากรอบที่แล้วไหม แม้แต่ละรอบเป็นโปรเซสใหม่
# ============================================================
STATE_FILE = "last_signal.txt"


def read_last_signal_from_file() -> str | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def write_last_signal_to_file(signal: str):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(signal or "")
    except Exception as e:
        print(f"⚠️  บันทึกสถานะไม่สำเร็จ: {e}")


# ============================================================
# ▶️  main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="XAUUSD Live Signal Generator")
    parser.add_argument("--loop", action="store_true", help="รันวนซ้ำอัตโนมัติ (ใช้ตอนรันบนเครื่องตัวเอง)")
    parser.add_argument("--interval", type=int, default=15, help="ความถี่รีเฟรช (นาที) เมื่อใช้ --loop")
    parser.add_argument("--test-alert", action="store_true", help="ทดสอบระบบแจ้งเตือนทันที (ไม่ต้องรอสัญญาณจริง)")
    parser.add_argument("--use-state-file", action="store_true",
                         help="อ่าน/บันทึกสัญญาณล่าสุดจากไฟล์ (ใช้ตอนรันบน GitHub Actions ที่แต่ละรอบเป็นโปรเซสใหม่)")
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

    last_signal = read_last_signal_from_file() if args.use_state_file else None

    def run_once():
        nonlocal last_signal
        try:
            df = fetch_data()
            result = compute_signal(df)
            print_signal(result)

            current_signal = result.get("signal")
            actionable = current_signal in ("BUY / LONG", "SELL / SHORT")
            signal_changed = current_signal != last_signal

            if actionable and signal_changed:
                print("🔔 สัญญาณเปลี่ยน — กำลังส่งแจ้งเตือน...")
                fire_alerts(result)

            last_signal = current_signal
            if args.use_state_file:
                write_last_signal_to_file(current_signal or "")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาด: {e}")

    if args.loop:
        print(f"🔄 เริ่มรันแบบวนซ้ำทุก {args.interval} นาที (กด Ctrl+C เพื่อหยุด)")
        print("   จะแจ้งเตือนก็ต่อเมื่อสัญญาณเปลี่ยนเป็น BUY หรือ SELL ใหม่เท่านั้น\n")
        while True:
            run_once()
            time.sleep(args.interval * 60)
    else:
        run_once()


if __name__ == "__main__":
    main()
