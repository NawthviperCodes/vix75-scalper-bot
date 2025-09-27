# === zone_detector.py (Dual Zone Detection: Strict + Fast) ===
def detect_zones(df, lookback=100, zone_size=5):
    """
    Detect strong supply and demand zones (pivot-based)
    """
    demand_zones = []
    supply_zones = []

    for i in range(zone_size, len(df) - zone_size):
        candle = df.iloc[i]
        prev_candles = df.iloc[i - zone_size:i]
        next_candles = df.iloc[i + 1:i + 1 + zone_size]

        # Strict Demand Zone (pivot low)
        if (
            all(candle.low < x.low for x in prev_candles.itertuples()) and
            all(candle.low < x.low for x in next_candles.itertuples())
        ):
            demand_zones.append({
                "type": "demand",
                "price": candle.low,
                "time": candle.time
            })

        # Strict Supply Zone (pivot high)
        if (
            all(candle.high > x.high for x in prev_candles.itertuples()) and
            all(candle.high > x.high for x in next_candles.itertuples())
        ):
            supply_zones.append({
                "type": "supply",
                "price": candle.high,
                "time": candle.time
            })

    return demand_zones, supply_zones


def detect_fast_zones(df, min_proximity=15000, wick_ratio=1.5, cluster_size=2):
    """
    Smarter fast-zone detection (VIX75 oriented):
    - ATR-adaptive proximity (dynamic band)
    - Wick rejection requirement
    - Cluster filter (need at least `cluster_size` touches)
    """
    fast_demand, fast_supply = [], []

    if df.empty or len(df) < 20:
        return fast_demand, fast_supply

    last_candle = df.iloc[-1]
    recent = df.tail(5)

    # --- ATR adaptive band
    atr_points = df['close'].diff().abs().rolling(14).mean().iloc[-1]
    proximity = max(int(atr_points * 2), min_proximity)

    def is_wick_rejection(c, side):
        body = abs(c.close - c.open)
        if body == 0: 
            return False
        upper = c.high - max(c.close, c.open)
        lower = min(c.close, c.open) - c.low
        if side == "demand":
            return (lower / body) >= wick_ratio
        else:
            return (upper / body) >= wick_ratio

    # --- Demand zone candidates
    demand_hits = [c for c in recent.itertuples() if c.low <= last_candle.low + proximity]
    if len(demand_hits) >= cluster_size and is_wick_rejection(last_candle, "demand"):
        fast_demand.append({
            "type": "fast_demand",
            "price": last_candle.low,
            "time": last_candle.time
        })

    # --- Supply zone candidates
    supply_hits = [c for c in recent.itertuples() if c.high >= last_candle.high - proximity]
    if len(supply_hits) >= cluster_size and is_wick_rejection(last_candle, "supply"):
        fast_supply.append({
            "type": "fast_supply",
            "price": last_candle.high,
            "time": last_candle.time
        })

    return fast_demand, fast_supply


# === scalper_strategy_engine.py (Updated for Dual Zones) ===
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, place_dynamic_order, trail_sl

SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
ZONE_LOOKBACK = 100
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 30000

active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None

def zones_equal(z1, z2):
    if len(z1) != len(z2):
        return False
    for a, b in zip(z1, z2):
        if abs(a['price'] - b['price']) > 1e-5 or a['time'] != b['time']:
            return False
    return True

def get_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def print_detected_zones(demand_zones, supply_zones, fast_demand, fast_supply):
    print(f"[INFO] Strict Zones: {len(demand_zones)} demand, {len(supply_zones)} supply")
    for zone in demand_zones:
        print(f"  Demand zone @ {zone['price']:.2f} at {zone['time']}")
    for zone in supply_zones:
        print(f"  Supply zone @ {zone['price']:.2f} at {zone['time']}")

    print(f"[INFO] Fast Zones: {len(fast_demand)} demand, {len(fast_supply)} supply")
    for zone in fast_demand:
        print(f"  Fast Demand @ {zone['price']:.2f} at {zone['time']}")
    for zone in fast_supply:
        print(f"  Fast Supply @ {zone['price']:.2f} at {zone['time']}")

def monitor_and_trade(strategy_mode="trend_follow", fixed_lot=None):
    global _last_demand_zones, _last_supply_zones, _last_fast_demand, _last_fast_supply, _last_zone_alert_time

    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        print("[ERROR] H1 unavailable.")
        return

    demand_zones, supply_zones = detect_zones(h1_df)
    fast_demand, fast_supply = detect_fast_zones(h1_df)
    print_detected_zones(demand_zones, supply_zones, fast_demand, fast_supply)

    current_h1_time = h1_df['time'].iloc[-1]
    if ((not zones_equal(demand_zones, _last_demand_zones) or not zones_equal(supply_zones, _last_supply_zones) or
         not zones_equal(fast_demand, _last_fast_demand) or not zones_equal(fast_supply, _last_fast_supply))
        and (_last_zone_alert_time != current_h1_time)):
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones
        _last_fast_demand = fast_demand
        _last_fast_supply = fast_supply
        _last_zone_alert_time = current_h1_time
        send_telegram_message(f"📊 New zones detected.\nStrict: D={len(demand_zones)}, S={len(supply_zones)} | Fast: D={len(fast_demand)}, S={len(fast_supply)}")

    trend = calculate_h1_trend(h1_df)
    if not trend:
        print("[ERROR] Not enough H1 data for trend.")
        return

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if len(m1_df) < 4:
        print("[ERROR] Not enough M1.")
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print("[ERROR] No tick data.")
        return

    price = tick.bid
    point = mt5.symbol_info(SYMBOL).point

    signals = trade_decision_engine(
        symbol=SYMBOL,
        point=point,
        current_price=price,
        trend=trend,
        demand_zones=demand_zones + fast_demand,
        supply_zones=supply_zones + fast_supply,
        last3_candles=m1_df.iloc[-4:-1],
        active_trades=active_trades,
        zone_touch_counts=zone_touch_counts,
        SL_BUFFER=SL_BUFFER,
        TP_RATIO=TP_RATIO,
        CHECK_RANGE=CHECK_RANGE,
        LOT_SIZE=fixed_lot if fixed_lot else 0.001,
        MAGIC=MAGIC,
        strategy_mode=strategy_mode
    )

    for signal in signals:
        side = signal['side']
        entry = signal['entry']
        sl = signal['sl']
        tp = signal['tp']
        zone = signal['zone']

        emoji = '🟢' if side == 'buy' else '🔴'
        msg = f"{emoji} {side.upper()} | Zone: {zone:.2f} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
        print(msg)
        send_telegram_message(msg)

        try:
            if fixed_lot:
                result = place_order(SYMBOL, side, fixed_lot, sl, tp, MAGIC)
            else:
                result = place_dynamic_order(SYMBOL, side, sl, tp, MAGIC)
        except TypeError as e:
            print(f"[ERROR] Order placement failed: {e}")
            send_telegram_message("❌ Order placement failed: check trade_executor")
            return

        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            confirmation = (
                f"✅ ORDER PLACED\n{side.upper()} {SYMBOL}\nPrice: {result.price:.2f}\nSL: {sl:.2f} | TP: {tp:.2f}"
            )
            send_telegram_message(confirmation)
            active_trades[side] = True
        else:
            error_msg = f"❌ Order Failed\nRetcode: {result.retcode}\nMessage: {result.comment}"
            print(error_msg)
            send_telegram_message(error_msg)

    trail_sl(SYMBOL, MAGIC)

def calculate_h1_trend(h1_df):
    h1_df['SMA50'] = h1_df['close'].rolling(50).mean()
    if len(h1_df) < 51:
        return None
    last = h1_df['close'].iloc[-1]
    sma = h1_df['SMA50'].iloc[-1]
    if last > sma:
        return "uptrend"
    elif last < sma:
        return "downtrend"
    return "sideways"
