import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, trail_sl,place_order_at_zone
from performance_tracker import send_daily_summary
from trade_logger import log_pending_trade, update_trade_result
import pytz
from ta.trend import MACD
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice
from ta.volatility import AverageTrueRange
from symbol_info_helper import get_lot_constraints

# ============================
#   CONFIG & GLOBAL STATE
# ============================
SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_M15  # Update zones every 15 minutes
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
TIMEFRAME_CONFIRM = mt5.TIMEFRAME_M5
ZONE_LOOKBACK = 100
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 5000
MIN_LOT = 0.001

# Runtime state
active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None

def send_intro():
    intro_text = (
        "📢 **Bot Introduction**\n\n"
        "This bot trades the *Volatility 75 Index* using two modes:\n"
        "• **Strict** – waits for H1/H4 trend alignment and classic price-action patterns.\n"
        "• **Aggressive** – reacts to fast zones using a weighted score of price-action "
        "plus MACD, RSI and VWAP, with ATR-based risk control.\n\n"
        "⚠️ *Disclaimer*: This is an automated system for educational purposes. "
        "Trading synthetic indices involves significant risk. Use at your own discretion; "
        "the author assumes no liability for financial loss.\n\n"
        "👤 **Author**: Thabo Masilompana\n"
        "📞 **Contact**: 066 229 7338\n"
        "💡 Signals are generated automatically—no manual confirmation is given."
    )
    from telegram_notifier import send_telegram_message
    send_telegram_message(intro_text)

# ============================
#   HELPERS
# ============================
def zones_equal(z1, z2):
    """Compare lists of zones by price+time."""
    if len(z1) != len(z2):
        return False
    for a, b in zip(z1, z2):
        if abs(a['price'] - b['price']) > 1e-5 or a['time'] != b['time']:
            return False
    return True


def merge_touch_counts(old_zones, new_zones, label):
    """Carry over touch counts for zones that persist across refreshes."""
    merged_counts = {}
    for zone in new_zones:
        key = zone['price']
        if key in zone_touch_counts:
            merged_counts[key] = zone_touch_counts[key]
    return merged_counts


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


def get_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    if df.empty:
        return df
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def calculate_trend(df):
    """Simple SMA(50) trend filter on close."""
    if df.empty:
        return None
    df = df.copy()
    df['SMA50'] = df['close'].rolling(50).mean()
    if len(df) < 51:
        return None
    last = float(df['close'].iloc[-1])
    sma = float(df['SMA50'].iloc[-1])
    if last > sma:
        return "uptrend"
    elif last < sma:
        return "downtrend"
    else:
        return "sideways"

def calc_risk_based_lot(account_balance, risk_pct, stop_points, point_value, min_lot):
    """
    Return a lot size so that if the stop is hit,
    only `risk_pct` of account_balance is lost.
    Lot size is clamped between broker min/max, rounded to the correct step.
    """
    # how much money you are willing to lose on this trade
    risk_amount = account_balance * risk_pct

    # each point costs `point_value * lot`
    raw_lot = risk_amount / (stop_points * point_value)

    # --- Apply broker constraints ---
    broker_min, broker_max, step = get_lot_constraints(SYMBOL)

    # Fallback to passed min_lot if broker call failed
    min_allowed = broker_min if broker_min else min_lot
    max_allowed = broker_max if broker_max else 1.0
    step_size = step if step else 0.001

    # Clamp between broker min/max
    lot = max(min_allowed, min(raw_lot, max_allowed))

    # Round down to nearest step size
    lot = (lot // step_size) * step_size

    return round(lot, 3)

# ============================
#   CORE LOOP
# ============================
def monitor_and_trade(strategy_mode=None, fixed_lot=None):
    global _last_demand_zones, _last_supply_zones, _last_fast_demand, _last_fast_supply, _last_zone_alert_time, zone_touch_counts

    # -------- 1) Collect context data
    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        print("[ERROR] H1 unavailable.")
        return

    demand_zones, supply_zones = detect_zones(h1_df)
    fast_demand, fast_supply = detect_fast_zones(h1_df)

    trend = calculate_trend(h1_df)
    if not trend:
        print("[ERROR] Not enough H1 data for trend.")
        return

    # -------- H4 Trend Context (new) ----------
    h4_df = get_data(SYMBOL, mt5.TIMEFRAME_H4, 200)
    if h4_df.empty:
        print("[ERROR] H4 unavailable.")
        return

    h4_trend = calculate_trend(h4_df)
    if not h4_trend:
        print("[ERROR] Not enough H4 data for trend.")
        return

    # Require alignment between H1 and H4 trends (both must be same non-sideways)
    if trend != h4_trend or trend == "sideways" or h4_trend == "sideways":
        print(f"[INFO] Skipping trades (H1={trend}, H4={h4_trend}) → no strong alignment.")
        try:
            send_telegram_message(f"⚠️ Skipped trading: No strong trend alignment (H1={trend}, H4={h4_trend})")
        except Exception:
            pass
        return
    # ------------------------------------------

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 150)
    if len(m1_df) < 35:
        print("[ERROR] Not enough M1 candles for indicators.")
        return

    m5_df = get_data(SYMBOL, TIMEFRAME_CONFIRM, 50)
    m5_context = {}
    if not m5_df.empty and len(m5_df) >= 35:
        try:
            m5_context['trend'] = calculate_trend(m5_df)
            m5_context['macd'] = MACD(close=m5_df['close']).macd().dropna().values
            m5_context['rsi'] = RSIIndicator(close=m5_df['close']).rsi().dropna().values
        except Exception as e:
            print(f"[WARN] M5 context failed: {e}")
            m5_context = {}

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print("[ERROR] No tick data.")
        return

    price = float(tick.bid)
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        print("[ERROR] Symbol info unavailable.")
        return
    point = symbol_info.point
    
    # --- Harden stops_level retrieval (for future use) ---
    stops_level = getattr(symbol_info, "stops_level", None)
    if stops_level is not None:
        min_distance = stops_level * point
    else:
        min_distance = 500 * point  # fallback safe default

    # Indicators on M1
    try:
        macd_calc = MACD(close=m1_df['close'])
        macd_line = macd_calc.macd().dropna().values
        macd_signal = macd_calc.macd_signal().dropna().values
        rsi_values = RSIIndicator(close=m1_df['close']).rsi().dropna().values
        vwap_value = VolumeWeightedAveragePrice(
            high=m1_df['high'], low=m1_df['low'], close=m1_df['close'], volume=m1_df['real_volume']
        ).vwap.iloc[-1]
        atr = AverageTrueRange(
            high=m1_df['high'], low=m1_df['low'], close=m1_df['close']
        ).average_true_range().iloc[-1]
    except Exception as e:
        print(f"[ERROR] Indicator calculation failed: {e}")
        macd_line = macd_signal = rsi_values = vwap_value = atr = None

    # -------- 2) Primary pass — strict + aggressive
    strict_signals, flipped_strict = trade_decision_engine(
        symbol=SYMBOL,
        point=point,
        current_price=price,
        trend=trend,
        demand_zones=demand_zones,
        supply_zones=supply_zones,
        last3_candles=m1_df.iloc[-4:-1],
        active_trades=active_trades,
        zone_touch_counts=zone_touch_counts,
        SL_BUFFER=SL_BUFFER,
        TP_RATIO=TP_RATIO,
        CHECK_RANGE=CHECK_RANGE,
        LOT_SIZE=fixed_lot if fixed_lot else MIN_LOT,
        MAGIC=MAGIC,
        strategy_mode="trend_follow",
        macd=macd_line,
        macd_signal=macd_signal,
        rsi=rsi_values,
        vwap=vwap_value,
        atr=atr,
        m5_context=m5_context
    )

    aggressive_signals, flipped_fast = trade_decision_engine(
        symbol=SYMBOL,
        point=point,
        current_price=price,
        trend=trend,
        demand_zones=fast_demand,
        supply_zones=fast_supply,
        last3_candles=m1_df.iloc[-4:-1],
        active_trades=active_trades,
        zone_touch_counts=zone_touch_counts,
        SL_BUFFER=SL_BUFFER,
        TP_RATIO=TP_RATIO,
        CHECK_RANGE=CHECK_RANGE,
        LOT_SIZE=fixed_lot if fixed_lot else MIN_LOT,
        MAGIC=MAGIC,
        strategy_mode="aggressive",
        macd=macd_line,
        macd_signal=macd_signal,
        rsi=rsi_values,
        vwap=vwap_value,
        atr=atr,
        m5_context=m5_context
    )

    # -------- 3) Apply flips
    def _remove_zone(zlist, zflip):
        return [z for z in zlist if not (abs(z['price'] - zflip['price']) < 1e-5 and z['time'] == zflip['time'])]

    for z in flipped_strict:
        if z['type'] == 'demand':
            supply_zones = _remove_zone(supply_zones, z)
            demand_zones.append(z)
        elif z['type'] == 'supply':
            demand_zones = _remove_zone(demand_zones, z)
            supply_zones.append(z)

    for z in flipped_fast:
        if z['type'] == 'demand':
            fast_supply = _remove_zone(fast_supply, z)
            fast_demand.append(z)
        elif z['type'] == 'supply':
            fast_demand = _remove_zone(fast_demand, z)
            fast_supply.append(z)

    if flipped_strict or flipped_fast:
        send_telegram_message(f"♻️ Zones flipped: {len(flipped_strict) + len(flipped_fast)}")

        # Re-run engine
        postflip_strict, _ = trade_decision_engine(
            symbol=SYMBOL,
            point=point,
            current_price=price,
            trend=trend,
            demand_zones=demand_zones,
            supply_zones=supply_zones,
            last3_candles=m1_df.iloc[-4:-1],
            active_trades=active_trades,
            zone_touch_counts=zone_touch_counts,
            SL_BUFFER=SL_BUFFER,
            TP_RATIO=TP_RATIO,
            CHECK_RANGE=CHECK_RANGE,
            LOT_SIZE=fixed_lot if fixed_lot else MIN_LOT,
            MAGIC=MAGIC,
            strategy_mode="trend_follow",
            macd=macd_line,
            macd_signal=macd_signal,
            rsi=rsi_values,
            vwap=vwap_value,
            atr=atr,
            m5_context=m5_context
        )

        postflip_aggr, _ = trade_decision_engine(
            symbol=SYMBOL,
            point=point,
            current_price=price,
            trend=trend,
            demand_zones=fast_demand,
            supply_zones=fast_supply,
            last3_candles=m1_df.iloc[-4:-1],
            active_trades=active_trades,
            zone_touch_counts=zone_touch_counts,
            SL_BUFFER=SL_BUFFER,
            TP_RATIO=TP_RATIO,
            CHECK_RANGE=CHECK_RANGE,
            LOT_SIZE=fixed_lot if fixed_lot else MIN_LOT,
            MAGIC=MAGIC,
            strategy_mode="aggressive",
            macd=macd_line,
            macd_signal=macd_signal,
            rsi=rsi_values,
            vwap=vwap_value,
            atr=atr,
            m5_context=m5_context
        )
        strict_signals.extend(postflip_strict)
        aggressive_signals.extend(postflip_aggr)

    # -------- 4) Informational printout
    print_detected_zones(demand_zones, supply_zones, fast_demand, fast_supply)

    # -------- 5) Execute signals
    signals = strict_signals + aggressive_signals

    # --- Spread & slippage protection (skip trading if spread too wide) ---
    try:
        spread_points = (tick.ask - tick.bid) / point
    except Exception as e:
        spread_points = None
        print(f"[WARN] Could not compute spread: {e}")

    # Dynamic spread limit based on ATR
    if atr:
        max_spread = max(1500, atr / point * 0.75)  # at least 1500 points, or 0.75×ATR
    else:
        max_spread = 3000  # fallback if ATR unavailable

    if spread_points is not None:
        if spread_points > max_spread:
            print(f"[SKIP] Spread too high: {spread_points:.0f} points (max {max_spread:.0f})")
            try:
                send_telegram_message(
                    f"⛔ Trade skipped: spread {spread_points:.0f} > allowed {max_spread:.0f}"
                )
            except Exception:
                pass
            return
        
    print(f"[DEBUG] Got {len(signals)} signals, spread={spread_points}")
    for signal in signals:
        side = signal['side']
        entry = signal['entry']
        sl = signal['sl']
        tp = signal['tp']
        zone = signal['zone']
        reason = signal.get('reason', '')
        strategy = signal.get('strategy', '')
        
        # --- Enforce broker min distance before placing order ---
        if abs(entry - sl) < min_distance:
            if side == "buy":
                sl = entry - min_distance
            else:
                sl = entry + min_distance
            # Recalculate TP relative to adjusted SL
            if side == "buy":
                tp = entry + TP_RATIO * (entry - sl)
            else:
                tp = entry - TP_RATIO * (sl - entry)

        if abs(tp - entry) < min_distance:
            if side == "buy":
                tp = entry + min_distance
            else:
                tp = entry - min_distance

        # --- Risk-based lot sizing ---
        # Prefer explicit fixed_lot if passed, otherwise compute from account balance & stop distance
        try:
            account_info = mt5.account_info()
        except Exception:
            account_info = None

        if fixed_lot:
            lot = fixed_lot
        else:
            if account_info:
                try:
                    balance = float(account_info.balance)
                    # guard: stop_points must be > 0
                    stop_points = max(1.0, abs(entry - sl) / point)
                    # prefer symbol_info.trade_tick_value if available, else fall back to 1
                    tick_value = getattr(symbol_info, 'trade_tick_value', None)
                    if tick_value is None or tick_value == 0:
                        tick_value = 1.0
                    lot = calc_risk_based_lot(
                        account_balance=balance,
                        risk_pct=0.01,       # risk 1% per trade (adjustable)
                        stop_points=stop_points,
                        point_value=tick_value,
                        min_lot=MIN_LOT
                    )
                except Exception as e:
                    print(f"[WARN] Risk-based lot calculation failed: {e}")
                    lot = max(MIN_LOT, signal.get('lot', MIN_LOT))
            else:
                lot = max(MIN_LOT, signal.get('lot', MIN_LOT))

        emoji = '🟢' if side == 'buy' else '🔴'
        msg = (
            f"{emoji} {side.upper()} | Zone: {zone:.2f} | Entry: {entry:.2f} | "
            f"SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot:.3f} | {strategy} {reason}"
        )
        print(msg)
        try:
            send_telegram_message(msg)
        except Exception:
            pass

        # Place order with one retry for transient failures/slippage
        try:
            result = place_order_at_zone(SYMBOL, side, lot, sl, tp, MAGIC, zone['price'])
            # If no result or failed retcode, retry once
            if result is None or getattr(result, 'retcode', None) != mt5.TRADE_RETCODE_DONE:
                # small pause could be added here if desired (avoid sleeping in main loop if not wanted)
                try:
                    send_telegram_message("⚠️ Order failed first attempt — retrying once...")
                except Exception:
                    pass
                result = place_order_at_zone(SYMBOL, side, lot, sl, tp, MAGIC, zone['price'])
        except TypeError as e:
            print(f"[ERROR] Order placement failed: {e}")
            send_telegram_message("❌ Order placement failed: check your trade_executor function definition")
            continue
        except Exception as e:
            print(f"[ERROR] Unexpected order placement exception: {e}")
            send_telegram_message(f"❌ Unexpected order placement exception: {e}")
            continue

        # Handle result
        if result is not None:
            if getattr(result, 'retcode', None) == mt5.TRADE_RETCODE_DONE:
                confirmation = (
                    f"✅ ORDER PLACED\n"
                    f"{side.upper()} {SYMBOL}\n"
                    f"Price: {getattr(result, 'price', entry):.2f}\n"
                    f"SL: {sl:.2f} | TP: {tp:.2f}"
                )
                try:
                    send_telegram_message(confirmation)
                except Exception:
                    pass
                active_trades[side] = True
                try:
                    log_pending_trade(strategy, side, reason, zone, entry, sl, tp, lot)
                except Exception as e:
                    print(f"[WARN] log_pending_trade failed: {e}")
            else:
                error_msg = (
                    f"❌ Order Failed\n"
                    f"Retcode: {getattr(result, 'retcode', 'N/A')}\n"
                    f"Message: {getattr(result, 'comment', '')}"
                )
                print(error_msg)
                try:
                    send_telegram_message(error_msg)
                except Exception:
                    pass
        else:
            try:
                send_telegram_message("❌ Order attempt returned None")
            except Exception:
                pass

    # -------- 6) Housekeeping
    try:
        trail_sl(SYMBOL, MAGIC)
    except Exception as e:
        print(f"[WARN] trail_sl failed: {e}")

    check_for_closed_trades()



# ============================
#   HISTORY / P&L TRACKING
# ============================
def check_for_closed_trades():
    now = datetime.now()
    start = now - timedelta(days=1)
    deals = mt5.history_deals_get(start, now)
    if not deals:
        return

    seen = set()
    for deal in deals:
        if getattr(deal, 'entry', None) != 1:
            continue

        for exit_deal in deals:
            if getattr(exit_deal, 'entry', None) == 0 and exit_deal.position_id == deal.position_id and (deal.position_id, exit_deal.time) not in seen:
                entry_time = datetime.fromtimestamp(deal.time, tz=pytz.utc).astimezone()
                exit_time = datetime.fromtimestamp(exit_deal.time, tz=pytz.utc).astimezone()
                side = "buy" if deal.type == mt5.ORDER_TYPE_BUY else "sell"
                entry_price = deal.price
                exit_price = exit_deal.price
                profit = exit_deal.profit
                result = "win" if profit > 0 else "loss"
                seen.add((deal.position_id, exit_deal.time))

                try:
                    update_trade_result(entry_price, side, exit_price, profit)
                except Exception as e:
                    print(f"[WARN] update_trade_result failed: {e}")
                break


# ============================
#   OPTIONAL: DAILY SUMMARY
# ============================
def maybe_send_daily_summary():
    try:
        send_daily_summary()
    except Exception as e:
        print(f"[WARN] Daily summary failed: {e}")




if __name__ == "__main__":
   
    monitor_and_trade()
