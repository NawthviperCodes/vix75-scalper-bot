
from datetime import datetime
from telegram_notifier import send_telegram_message

TOUCH_LIMIT = 3
VWAP_TOLERANCE = 150

def is_bullish_marubozu(candle):
    return (candle.open < candle.close
            and (candle.high - candle.close) < (0.1 * (candle.close - candle.open))
            and (candle.open - candle.low) < (0.1 * (candle.close - candle.open)))

def is_bearish_marubozu(candle):
    return (candle.open > candle.close
            and (candle.high - candle.open) < (0.1 * (candle.open - candle.close))
            and (candle.close - candle.low) < (0.1 * (candle.open - candle.close)))

def is_inside_bar(prev, curr):
    return curr.high <= prev.high and curr.low >= prev.low

def is_vwap_bounce(candle, vwap, direction):
    if vwap is None:
        return False
    distance = abs(candle.close - vwap)
    if distance < VWAP_TOLERANCE:
        if direction == "bullish" and candle.close > candle.open and candle.low < vwap:
            return True
        elif direction == "bearish" and candle.close < candle.open and candle.high > vwap:
            return True
    return False

def is_ema_rejection(candle, ema_value, direction):
    if ema_value is None:
        return False
    if direction == "bullish":
        return candle.low <= ema_value <= candle.close and candle.close > candle.open
    elif direction == "bearish":
        return candle.high >= ema_value >= candle.close and candle.close < candle.open
    return False

def scalping_engine_vix75(
    symbol,
    point,
    current_price,
    fast_zones,
    last3_candles,
    active_trades,
    zone_touch_counts,
    SL_BUFFER,
    TP_RATIO,
    CHECK_RANGE,
    LOT_SIZE,
    MAGIC,
    macd=None,
    macd_signal=None,
    rsi=None,
    vwap=None,
    ema9=None,
    ema21=None,
    atr=None
):
    signals = []

    print(f"[DEBUG] Received last3_candles shape: {last3_candles.shape}")
    print(f"[DEBUG] last3_candles columns: {list(last3_candles.columns)}")
    print(f"[DEBUG] last3_candles tail:\n{last3_candles.tail(5)}")

    for name, series in [('macd', macd), ('macd_signal', macd_signal), ('rsi', rsi)]:
        if series is not None and len(series) < 3:
            print(f"[ERROR] {name} has less than 3 elements: len={len(series)}")
            send_telegram_message(f"❌ Not enough {name} data (len={len(series)})")
            return []

    if len(last3_candles) < 3:
        print(f"[ERROR] Not enough candles passed to scalping_engine_vix75: len={len(last3_candles)}")
        return []

    try:
        last3_candles = last3_candles.dropna()
        print(f"[DEBUG] Cleaned last3_candles shape: {last3_candles.shape}")

        if len(last3_candles) < 3:
            print("[ERROR] Dropped NA rows, not enough candles remain.")
            return []

        print(f"[DEBUG] Indexing into candles...")
        demand_price_check = last3_candles['low'].iloc[-2]
        supply_price_check = last3_candles['high'].iloc[-2]
        candle_time = last3_candles['time'].iloc[-2]

        c1, c2, c3 = last3_candles.iloc[-3], last3_candles.iloc[-2], last3_candles.iloc[-1]
        print(f"[DEBUG] Candle c1: {c1.to_dict()}")
        print(f"[DEBUG] Candle c2: {c2.to_dict()}")
        print(f"[DEBUG] Candle c3: {c3.to_dict()}")
    except Exception as e:
        print(f"[ERROR] Indexing failed in scalping_engine_vix75: {e}")
        send_telegram_message(f"❌ Candle indexing failed: {e}")
        return []

    for zone in fast_zones:
        zone_price = zone['price']
        zone_type_full = zone.get('type', '')
        zone_parts = zone_type_full.strip().split()

        if len(zone_parts) == 2:
            zone_type = zone_parts[1]
        elif len(zone_parts) == 1:
            zone_type = zone_parts[0]
        else:
            print(f"[ERROR] Unexpected zone type format: {zone_type_full}")
            send_telegram_message(f"❌ Bad zone type: {zone_type_full}")
            continue

        lot_size = LOT_SIZE / 2
        threshold = CHECK_RANGE * point
        price_check = demand_price_check if zone_type == 'demand' else supply_price_check
        dist = abs(price_check - zone_price)
        in_zone = dist < threshold

        if zone_price not in zone_touch_counts:
            zone_touch_counts[zone_price] = {
                'count': 0,
                'last_touch_time': candle_time,
                'was_outside_zone': False,
                'last_skip_time': None
            }

        z = zone_touch_counts[zone_price]
        if not in_zone:
            z['was_outside_zone'] = True

        if in_zone and z['was_outside_zone'] and candle_time != z['last_touch_time']:
            z['count'] += 1
            z['last_touch_time'] = candle_time
            z['was_outside_zone'] = False

        if z['count'] >= TOUCH_LIMIT:
            send_telegram_message(f"⚠️ FAST {zone_type.upper()} zone @ {zone_price:.2f} invalidated after {z['count']} touches.")
            del zone_touch_counts[zone_price]
            continue

        prev, curr = last3_candles.iloc[-2], last3_candles.iloc[-1]
        confirm = False
        reason = ""

        if zone_type == "demand":
            if is_bullish_marubozu(curr):
                confirm = True
                reason = "bullish marubozu"
            elif is_inside_bar(prev, curr) and curr.close > prev.high:
                confirm = True
                reason = "bullish inside bar breakout"
            elif is_vwap_bounce(curr, vwap, "bullish"):
                confirm = True
                reason = "VWAP bounce (bullish)"
            elif is_ema_rejection(curr, ema9, "bullish") or is_ema_rejection(curr, ema21, "bullish"):
                confirm = True
                reason = "EMA tap reversal (bullish)"

        elif zone_type == "supply":
            if is_bearish_marubozu(curr):
                confirm = True
                reason = "bearish marubozu"
            elif is_inside_bar(prev, curr) and curr.close < prev.low:
                confirm = True
                reason = "bearish inside bar breakout"
            elif is_vwap_bounce(curr, vwap, "bearish"):
                confirm = True
                reason = "VWAP rejection (bearish)"
            elif is_ema_rejection(curr, ema9, "bearish") or is_ema_rejection(curr, ema21, "bearish"):
                confirm = True
                reason = "EMA tap reversal (bearish)"

        # Add MACD/RSI confirmation if triggered
        if confirm:
            idx = -1
            if zone_type == "demand" and macd[idx] > macd_signal[idx] and rsi[idx] > 50:
                confirm = True
            elif zone_type == "supply" and macd[idx] < macd_signal[idx] and rsi[idx] < 50:
                confirm = True
            else:
                confirm = False

        if not confirm:
            last_sent = z.get("last_skip_time")
            if last_sent is None or (candle_time - last_sent).seconds > 300:
                send_telegram_message(f"⛔️ Skipped: no confirmation at FAST {zone_type.upper()} zone {zone_price:.2f}")
                z["last_skip_time"] = candle_time
            continue

        if active_trades.get("buy" if zone_type == "demand" else "sell"):
            continue

        side = "buy" if zone_type == "demand" else "sell"
        sl = (min(curr.low, prev.low) - atr) if side == "buy" else (max(curr.high, prev.high) + atr)
        risk = abs(curr.close - sl)
        tp = curr.close + TP_RATIO * risk if side == "buy" else curr.close - TP_RATIO * risk

        send_telegram_message(f"✅ Scalping Entry: {reason} at zone {zone_price:.2f}")
        signals.append({
            "side": side,
            "entry": curr.close,
            "sl": sl,
            "tp": tp,
            "zone": zone_price,
            "lot": lot_size,
            "reason": reason,
            "strategy": "scalping_vix75"
        })

    return signals
