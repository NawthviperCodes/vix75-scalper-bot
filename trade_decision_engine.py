# === trade_decision_engine.py (VIX75 Fast-Zone Scoring, ATR-Adaptive, Crash-Safe) ===
from datetime import datetime
from trade_logger import log_skipped_trade
import MetaTrader5 as mt5

from telegram_notifier import send_telegram_message
from candlestick_patterns import (
    is_bullish_pin_bar,
    is_bullish_engulfing,
    is_bearish_pin_bar,
    is_bearish_engulfing,
    is_morning_star,
    is_evening_star,
    is_bullish_rectangle,
    is_bearish_rectangle
)
from indicator_filters import macd_cross, rsi_filter, vwap_filter
import pandas as pd

# =====================
#   CONSTANTS & STATE
# =====================
RESET_BUFFER_POINTS = 1000
rejected_signals_log = []

# =====================
#   CORE ENGINE
# =====================

def trade_decision_engine(
    symbol,
    point,
    current_price,
    trend,
    demand_zones,
    supply_zones,
    last3_candles,
    active_trades,
    zone_touch_counts,
    SL_BUFFER,
    TP_RATIO,
    CHECK_RANGE,
    LOT_SIZE,
    MAGIC,
    strategy_mode="trend_follow",
    macd=None,
    macd_signal=None,
    rsi=None,
    vwap=None,
    atr=None,
    m5_context=None
):
    """Return (signals, flipped_zones)

    Enhancements (VIX75 scalper oriented):
    - Price-action FIRST for fast zones (pin bars, engulfings, morning/evening star, rectangles).
    - Indicators are additive (MACD/RSI/VWAP scoring) instead of hard gates.
    - Wick-rejection BOOST (on touch 1–2) to catch sharp VIX75 reversals.
    - ATR-adaptive sensitivity (high ATR → lower threshold, low ATR → higher threshold).
    - Robust flip handling + instant re-eval on flips.
    - Defensive indicator access (never KeyError even if indicator returns odd keys/missing data).
    """

    signals = []
    flipped_zones = []

    # --------- helpers
    def log_rejection(reason, zone_type, zone_price, strategy, trend_context):
        record = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "zone_type": zone_type,
            "zone_price": zone_price,
            "strategy": strategy,
            "trend": trend_context
        }
        rejected_signals_log.append(record)
        try:
            log_skipped_trade(reason, zone_type, zone_price, strategy, trend_context)
        except Exception as e:
            print(f"[WARN] Failed to log skipped trade: {e}")

    def m5_agrees_with_entry(side, trend_type="trend_follow", is_fast_zone=False):
        """
        Adaptive M5 filter for VIX75:
        - Trend-follow: allow M5 uptrend or sideways for buys, downtrend or sideways for sells.
        - Counter-trend: require M5 to match reversal direction.
        - Fast zones: M5 is soft — only blocks if strongly opposite.
        """
        if not m5_context:
            return True  # No data → allow

        m5_trend = m5_context.get("trend")

        # === Fast zones ===
        if is_fast_zone:
            # Only reject if strongly opposite
            if side == "buy" and m5_trend == "downtrend":
                return False
            if side == "sell" and m5_trend == "uptrend":
                return False
            return True

        # === Trend-follow trades ===
        if trend_type == "trend_follow":
            if side == "buy":
                return m5_trend in ("uptrend", "sideways")
            if side == "sell":
                return m5_trend in ("downtrend", "sideways")

        # === Counter-trend trades ===
        elif trend_type == "counter_trend":
            if side == "buy":
                return m5_trend == "uptrend"
            if side == "sell":
                return m5_trend == "downtrend"

        return False

    def update_touch_count(zone_price, candle_time, in_zone, min_time_gap_sec=30):
        if zone_price not in zone_touch_counts:
            zone_touch_counts[zone_price] = {
                'count': 0,
                'last_touch_time': candle_time,
                'was_outside_zone': True
            }
        zone_state = zone_touch_counts[zone_price]
        if isinstance(candle_time, pd.Timestamp):
            candle_time = candle_time.to_pydatetime()
        last_time = zone_state['last_touch_time']
        time_diff = (candle_time - last_time).total_seconds()
        if not in_zone:
            zone_state['was_outside_zone'] = True
        if in_zone and zone_state['was_outside_zone'] and time_diff >= min_time_gap_sec:
            zone_state['count'] += 1
            zone_state['last_touch_time'] = candle_time
            zone_state['was_outside_zone'] = False
        return zone_state['count']

    def reset_touch_count(zone_price):
        if zone_price in zone_touch_counts:
            del zone_touch_counts[zone_price]

    def candle_confirms_breakout(trend_, candle_, zone_price_, min_dist=20):
        if trend_ == "uptrend" and (candle_.close - zone_price_) > min_dist:
            return True
        elif trend_ == "downtrend" and (zone_price_ - candle_.close) > min_dist:
            return True
        return False

    def is_valid_engulfing(prev, curr, direction):
        body_prev = abs(prev.close - prev.open)
        body_curr = abs(curr.close - curr.open)
        if body_prev == 0:
            return False
        if direction == "bullish":
            return curr.open < prev.close and curr.close > prev.open and body_curr > body_prev
        elif direction == "bearish":
            return curr.open > prev.close and curr.close < prev.open and body_curr > body_prev
        return False

    def has_wick_rejection(candle_, direction="bullish", min_wick_ratio=1.5):
        body = abs(candle_.close - candle_.open)
        if body == 0:
            return False
        upper_wick = candle_.high - max(candle_.close, candle_.open)
        lower_wick = min(candle_.close, candle_.open) - candle_.low
        return (lower_wick / body) >= min_wick_ratio if direction == "bullish" else (upper_wick / body) >= min_wick_ratio

    def detect_false_breakout(prev, curr, zone_price, direction):
        if direction == "bearish":
            return prev.close > zone_price and curr.close < zone_price and is_valid_engulfing(prev, curr, "bearish")
        elif direction == "bullish":
            return prev.close < zone_price and curr.close > zone_price and is_valid_engulfing(prev, curr, "bullish")
        return False

    # --- indicator helpers (defensive) ---
    def macd_side_confirms(side, macd_arr, macd_sig):
        """
        Defensive access:
        - Accept either {'buy','sell'} OR {'bullish','bearish'} keys from indicator.
        - Return False if arrays too short or indicator unavailable.
        """
        try:
            info = macd_cross(macd_arr, macd_sig) if (macd_arr is not None and macd_sig is not None) else {}
        except Exception:
            return False
        if not isinstance(info, dict):
            return False
        if side in info:
            return bool(info.get(side, False))
        # Gracefully map bullish/bearish to buy/sell
        if side == "buy":
            return bool(info.get("bullish", False))
        if side == "sell":
            return bool(info.get("bearish", False))
        return False

    def rsi_confirms(side, rsi_vals):
        try:
            if rsi_vals is None or len(rsi_vals) < 2:
                return False
            return bool(rsi_filter(rsi_vals, side))
        except Exception:
            return False

    def vwap_confirms(side, price, vwap_val):
        try:
            if vwap_val is None or price is None:
                return False
            return bool(vwap_filter(price, vwap_val, side))
        except Exception:
            return False

    # --- convenience: build entry
    def build_entry(side, candle, prev_candle, zone_price, lot_size):
        """
        Build order with ATR-adaptive stop loss.
        - FAST/aggressive zones → wick ± (2.5 × ATR)
        - STRICT zones → wick ± max(SL_BUFFER, 2 × ATR)
        - TP scales with TP_RATIO * risk
        - Enforces broker minimum distance (stops_level) for SL/TP
        """
        min_stop_dist = SL_BUFFER * point
        atr_mult_fast = 2.5
        atr_mult_strict = 2.0

        if strategy_mode == "aggressive" and atr is not None:
            stop_padding = max(min_stop_dist, atr_mult_fast * atr)
        else:
            stop_padding = max(min_stop_dist, atr_mult_strict * atr if atr is not None else min_stop_dist)

        if side == "buy":
            wick_sl = min(candle.low, prev_candle.low) - stop_padding
            risk = candle.close - wick_sl
            tp = candle.close + TP_RATIO * risk
        else:  # sell
            wick_sl = max(candle.high, prev_candle.high) + stop_padding
            risk = wick_sl - candle.close
            tp = candle.close - TP_RATIO * risk

        # --- Safety: enforce minimum SL/TP distance (broker stops_level) ---
        try:
            symbol_info = mt5.symbol_info(symbol)
            stops_level = getattr(symbol_info, "stops_level", None) if symbol_info else None
            if stops_level:
                min_distance = stops_level * point
            else:
                min_distance = 500 * point  # fallback if broker doesn’t provide
        except Exception:
            min_distance = 500 * point  # safe fallback

        # Adjust SL if too close
        if abs(candle.close - wick_sl) < min_distance:
            if side == "buy":
                wick_sl = candle.close - min_distance
            else:
                wick_sl = candle.close + min_distance
            # Recalculate risk & TP
            if side == "buy":
                risk = candle.close - wick_sl
                tp = candle.close + TP_RATIO * risk
            else:
                risk = wick_sl - candle.close
                tp = candle.close - TP_RATIO * risk

        # Adjust TP if too close
        if abs(tp - candle.close) < min_distance:
            if side == "buy":
                tp = candle.close + min_distance
            else:
                tp = candle.close - min_distance

        return {
            "side": side,
            "entry": zone_price,  # Changed from candle.close
            "sl": wick_sl,
            "tp": tp,
            "zone": zone_price,
            "lot": lot_size,
            "strategy": strategy_mode
        }


    # --- fast-zone scorer (price-action weighted) ---
    def score_fast_zone(side, zone_type, candles_win, touch_number, macd_arr, macd_sig, rsi_vals, vwap_val, price, atr_value):
        """
        Scoring:
          PA (any strong match) ............ +2   (primary)
          Wick rejection boost (touch <=2) . +2   (bonus)
          MACD agrees ...................... +1
          RSI agrees ....................... +1
          VWAP agrees ...................... +1
        Threshold (ATR-adaptive):
          base = 3
          if ATR high (>= 2 * CHECK_RANGE*point) → threshold = 2 (more reactive)
          if ATR low  (<= 0.8 * CHECK_RANGE*point) → threshold = 4 (more selective)
        """
        c1, c2, c3 = candles_win.iloc[-3], candles_win.iloc[-2], candles_win.iloc[-1]
        pa_score = 0
        wick_boost = 0
        ind_score = 0

        # --- Price Action by zone type ---
        if zone_type == "demand":
            pa_hits = [
                is_bullish_pin_bar(c3.open, c3.high, c3.low, c3.close),
                is_bullish_engulfing(c2.open, c2.high, c2.low, c2.close, c3.open, c3.high, c3.low, c3.close) if hasattr(is_bullish_engulfing, "__call__") else is_valid_engulfing(c2, c3, "bullish"),
                is_morning_star(c1, c2, c3),
                is_bullish_rectangle(candles_win.itertuples(index=False))
            ]
            if any(pa_hits):
                pa_score += 2
            if has_wick_rejection(c3, direction="bullish") and touch_number in (1, 2):
                wick_boost = 2
        else:  # supply
            pa_hits = [
                is_bearish_pin_bar(c3.open, c3.high, c3.low, c3.close),
                is_bearish_engulfing(c2.open, c2.high, c2.low, c2.close, c3.open, c3.high, c3.low, c3.close) if hasattr(is_bearish_engulfing, "__call__") else is_valid_engulfing(c2, c3, "bearish"),
                is_evening_star(c1, c2, c3),
                is_bearish_rectangle(candles_win.itertuples(index=False))
            ]
            if any(pa_hits):
                pa_score += 2
            if has_wick_rejection(c3, direction="bearish") and touch_number in (1, 2):
                wick_boost = 2

        # --- Indicators as additive confirmations ---
        ind_score += 1 if macd_side_confirms(side, macd_arr, macd_sig) else 0
        ind_score += 1 if rsi_confirms(side, rsi_vals) else 0
        ind_score += 1 if vwap_confirms(side, price, vwap_val) else 0

        # --- ATR-adaptive threshold ---
        base_threshold = 3
        zone_pip = CHECK_RANGE * point
        if atr_value is not None:
            if atr_value >= 2.0 * zone_pip:
                threshold = max(2, base_threshold - 1)  # more reactive in high vol
            elif atr_value <= 0.8 * zone_pip:
                threshold = base_threshold + 1          # stricter in chop
            else:
                threshold = base_threshold
        else:
            threshold = base_threshold

        # === VIX75 tweak: PA + Wick can fire alone ===
        pa_wick_score = pa_score + wick_boost
        if pa_wick_score >= threshold:
            return pa_wick_score, threshold, {"pa": pa_score, "wick": wick_boost, "ind": ind_score}

        # Otherwise, allow indicators to boost PA + Wick
        total = pa_wick_score + ind_score
        return total, threshold, {"pa": pa_score, "wick": wick_boost, "ind": ind_score}

    # --- instant eval for flipped zones uses same PA-first logic ---
    def evaluate_flipped_and_signal(new_side, new_zone_type_label, zone_price, lot_size, candle, prev_candle, zone_label_prefix, is_fast_zone=False):
        # Use PA first; allow breakout as backup; then soft-check M5; then additive indicators
        candles_win = last3_candles.tail(5)
        c1, c2, c3 = candles_win.iloc[-3], candles_win.iloc[-2], candles_win.iloc[-1]

        # Determine zone_type from new_side
        zone_type = 'demand' if new_side == 'buy' else 'supply'
        # Quick PA gate (one strong PA OR breakout)
        pa_ok = False
        if zone_type == "demand":
            if is_bullish_pin_bar(c3.open, c3.high, c3.low, c3.close) or is_valid_engulfing(c2, c3, "bullish") or is_morning_star(c1, c2, c3) or is_bullish_rectangle(candles_win.itertuples(index=False)):
                pa_ok = True
        else:
            if is_bearish_pin_bar(c3.open, c3.high, c3.low, c3.close) or is_valid_engulfing(c2, c3, "bearish") or is_evening_star(c1, c2, c3) or is_bearish_rectangle(candles_win.itertuples(index=False)):
                pa_ok = True

        if not pa_ok and candle_confirms_breakout(trend, c3, zone_price):
            pa_ok = True

        flip_trend_type = "trend_follow" if ((new_side == "buy" and trend == "uptrend") or (new_side == "sell" and trend == "downtrend")) else "counter_trend"

        if pa_ok and m5_agrees_with_entry(new_side, trend_type=flip_trend_type, is_fast_zone=is_fast_zone):
            # Additive indicators (lightweight)
            macd_ok = macd_side_confirms(new_side, macd, macd_signal)
            rsi_ok = rsi_confirms(new_side, rsi)
            vwap_ok = vwap_confirms(new_side, current_price, vwap)

            # Require at least 1 of the 3 to avoid super-weak flips
            conf_count = sum([macd_ok, rsi_ok, vwap_ok])
            if conf_count >= 1 or is_fast_zone:
                order = build_entry(new_side, c3, c2, zone_price, lot_size)
                order["reason"] = f"flipped {new_zone_type_label} instant"
                send_telegram_message(
                    f"📥 SIGNAL: {zone_label_prefix} {new_zone_type_label} | Entry: {order['entry']:.2f} | SL: {order['sl']:.2f} | TP: {order['tp']:.2f} | Lot: {order['lot']:.3f}"
                )
                signals.append(order)
            else:
                log_rejection("flipped: weak indicator backing", new_zone_type_label, zone_price, strategy_mode, trend)
        else:
            log_rejection("flipped: PA/M5 not ok", new_zone_type_label, zone_price, strategy_mode, trend)

    # =====================
    #   PREP CANDLES
    # =====================
    demand_price_check = last3_candles['low'].iloc[-2]
    supply_price_check = last3_candles['high'].iloc[-2]
    candle_time = last3_candles['time'].iloc[-1]

    candles = last3_candles.tail(5)
    c1, c2, c3 = candles.iloc[-3], candles.iloc[-2], candles.iloc[-1]
    candle = c3
    prev_candle = c2

    all_zones = [("demand", demand_zones), ("supply", supply_zones)]

    for zone_type, zones in all_zones:
        for zone in list(zones):  # iterate over copy to allow local append/remove if needed
            zone_price = zone['price']
            zone_kind = zone.get('type', 'strict')
            is_fast = "fast" in str(zone_kind).lower()
            lot_size = LOT_SIZE / 2 if is_fast else LOT_SIZE  # keep your half-lot for fast zones (as you requested earlier)

            zone_type_label = zone_type.upper()
            zone_label = f"{'FAST' if is_fast else 'STRICT'} {zone_type_label}"

            threshold = CHECK_RANGE * point
            dist = abs(demand_price_check - zone_price) if zone_type == "demand" else abs(supply_price_check - zone_price)
            in_zone = dist < threshold
            if not in_zone and zone_price in zone_touch_counts:
                zone_touch_counts[zone_price]['was_outside_zone'] = True

            touch_number = update_touch_count(zone_price, candle_time, in_zone, min_time_gap_sec=30)

            # Determine trade trend_type: if zone aligns with H1 trend then trend_follow else counter_trend
            trade_trend_type = "trend_follow" if ((zone_type == "demand" and trend == "uptrend") or (zone_type == "supply" and trend == "downtrend")) else "counter_trend"

            if trend == "uptrend" and zone_type == "supply":
                send_telegram_message(
                    f"⛔ Skipped SELL setup — uptrend only ({zone_type} zone at {zone_price:.2f})"
                )
                log_rejection("directional filter (uptrend)", zone_type, zone_price, strategy_mode, trend)
                continue

            if trend == "downtrend" and zone_type == "demand":
                send_telegram_message(
                    f"⛔ Skipped BUY setup — downtrend only ({zone_type} zone at {zone_price:.2f})"
                )
                log_rejection("directional filter (downtrend)", zone_type, zone_price, strategy_mode, trend)
                continue
            # ----------------- invalidation + flip
            if touch_number >= 4:
                send_telegram_message(
                    f"⚠️ {zone_label} zone at {zone_price:.2f} invalidated after {touch_number} touches"
                )
                if candle_confirms_breakout(trend, candle, zone_price):
                    # Flip: set new type (opposite) and keep original time for safe removal upstream
                    new_type = 'demand' if zone_type == 'supply' else 'supply'
                    flipped_zone = {
                        'price': zone_price,
                        'time': zone.get('time', datetime.now()),  # keep original if present
                        'type': new_type,
                        'origin': 'flipped',
                        'from': zone_type
                    }
                    flipped_zones.append(flipped_zone)
                    send_telegram_message(
                        f"🔁 Zone flipped: {zone_type.upper()} → {new_type.upper()} @ {zone_price:.2f}"
                    )

                    # Instant eval of flipped zone (opposite confirmations)
                    new_side = "buy" if new_type == "demand" else "sell"
                    evaluate_flipped_and_signal(
                        new_side=new_side,
                        new_zone_type_label=new_type.upper(),
                        zone_price=zone_price,
                        lot_size=lot_size,
                        candle=candle,
                        prev_candle=prev_candle,
                        zone_label_prefix="STRICT" if not is_fast else "FAST",
                        is_fast_zone=is_fast
                    )
                reset_touch_count(zone_price)
                continue

            # ----------------- normal confirmation path (touches 1..3)
            if touch_number and touch_number <= 3:
                send_telegram_message(
                    f"⚠️ Price touched {zone_label} zone at {zone_price:.2f} (touch {touch_number})"
                )

                # trend filter for trend_follow mode
                if strategy_mode == "trend_follow":
                    if (zone_type == "demand" and trend != "uptrend") or (
                        zone_type == "supply" and trend != "downtrend"
                    ):
                        send_telegram_message(
                            f"⛔ Skipped: trend mismatch at {zone_label} zone {zone_price:.2f} (trend: {trend})"
                        )
                        log_rejection("trend mismatch", zone_type, zone_price, strategy_mode, trend)
                        continue

                confirmed = False
                reason = ""

                # Legacy PA confirmations (kept for STRICT zones & as an early fast gate)
                if zone_type == "demand" and is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close):
                    confirmed = True; reason = "bullish pin bar"
                elif zone_type == "supply" and is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close):
                    confirmed = True; reason = "bearish pin bar"
                elif zone_type == "demand" and is_valid_engulfing(prev_candle, candle, "bullish"):
                    confirmed = True; reason = "bullish engulfing"
                elif zone_type == "supply" and is_valid_engulfing(prev_candle, candle, "bearish"):
                    confirmed = True; reason = "bearish engulfing"
                elif candle_confirms_breakout(trend, candle, zone_price):
                    confirmed = True; reason = "breakout"

                # ==========================
                # FAST ZONE: PA-FIRST SCORER
                # ==========================
                if strategy_mode == "aggressive" and is_fast:
                    side = "buy" if zone_type == "demand" else "sell"

                    # Compute score for fast zone
                    total, threshold_needed, breakdown = score_fast_zone(
                        side=side,
                        zone_type=zone_type,
                        candles_win=candles,
                        touch_number=touch_number,
                        macd_arr=macd,
                        macd_sig=macd_signal,
                        rsi_vals=rsi,
                        vwap_val=vwap,
                        price=current_price,
                        atr_value=atr
                    )

                    send_telegram_message(
                        f"🧮 {zone_label} score={total} (need≥{threshold_needed}) | PA:{breakdown['pa']} Wick:{breakdown['wick']} Ind:{breakdown['ind']} | ATR:{'N/A' if atr is None else round(float(atr),2)}"
                    )

                    # M5 filter: adaptive for fast zones (soft)
                    if not m5_agrees_with_entry(side, trend_type=trade_trend_type, is_fast_zone=True):
                        send_telegram_message(
                            f"⛔ Skipped: M5 disagrees with {side.upper()} entry at {zone_price:.2f} (FAST)"
                        )
                        log_rejection("M5 disagreement (FAST)", zone_type, zone_price, strategy_mode, trend)
                        continue

                    if total >= threshold_needed and not active_trades.get(side):
                        order = build_entry(side, candle, prev_candle, zone_price, lot_size)
                        order["reason"] = f"FAST score={total}"
                        send_telegram_message(f"✅ Entry reason (FAST): score {total} ≥ {threshold_needed}")
                        send_telegram_message(
                           f"📥 SIGNAL: {side.upper()} {zone_label} | Entry: {order['entry']:.2f} | "
                           f"SL: {order['sl']:.2f} | TP: {order['tp']:.2f} | Lot: {order['lot']:.3f}"
                        )
                        signals.append(order)
                    else:
                        if total < threshold_needed:
                            send_telegram_message(
                                f"⛔ Skipped (FAST): score {total} < {threshold_needed} at {zone_label} {zone_price:.2f}"
                            )
                            log_rejection("score below threshold (FAST)", zone_type, zone_price, strategy_mode, trend)
                        # If active trade exists on same side, we silently skip to avoid stacking
                    continue  # Fast zone handled fully; skip legacy strict path

                # ==============
                # STRICT ZONES
                # ==============
                if confirmed:
                    side = "buy" if zone_type == "demand" else "sell"

                    # --- VIX75 tweak: prioritize PA + Wick over M5 ---
                    wick_ok = has_wick_rejection(candle, direction="bullish" if side == "buy" else "bearish")
                    if (confirmed and wick_ok):
                        # Skip M5 hard filter: allow PA+Wick to fire even if M5 disagrees
                        pass
                    else:
                        # otherwise still apply M5 check
                        if not m5_agrees_with_entry(side, trend_type=trade_trend_type, is_fast_zone=False):
                            send_telegram_message(
                                f"⛔ Skipped: M5 disagrees with {side.upper()} entry at zone {zone_price:.2f}"
                            )
                            log_rejection("M5 disagreement", zone_type, zone_price, strategy_mode, trend)
                            continue

                    if not active_trades.get(side):
                        order = build_entry(side, candle, prev_candle, zone_price, lot_size)
                        order["reason"] = reason + (" + wick" if wick_ok else "")
                        send_telegram_message(f"✅ Entry reason: {order['reason']}")
                        send_telegram_message(
                           f"📥 SIGNAL: {side.upper()} {zone_label} | Entry: {order['entry']:.2f} | "
                           f"SL: {order['sl']:.2f} | TP: {order['tp']:.2f} | Lot: {order['lot']:.3f}"
                        )
                        signals.append(order)
                        
                else:
                    send_telegram_message(
                        f"⛔ Skipped: no confirmation at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("no confirmation", zone_type, zone_price, strategy_mode, trend)

            # ----------------- false breakout logic
            if detect_false_breakout(prev_candle, candle, zone_price, direction=("bearish" if zone_type == "demand" else "bullish")):
                reverse_side = "sell" if zone_type == "demand" else "buy"

                # false breakout is always counter-trend attempt → require M5 counter agreement
                if trend not in ["sideways"]:
                    send_telegram_message(
                        f"⛔ Skipped reversal: strong trend ({trend}) at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("strong trend blocks reversal", zone_type, zone_price, strategy_mode, trend)
                    continue
                if not (macd is not None and macd_signal is not None and rsi is not None and vwap is not None):
                    send_telegram_message(
                        f"⛔ Skipped reversal: missing indicators at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("missing indicators", zone_type, zone_price, strategy_mode, trend)
                    continue
                if not (macd_side_confirms(reverse_side, macd, macd_signal) and rsi_confirms(reverse_side, rsi) and vwap_confirms(reverse_side, current_price, vwap)):
                    send_telegram_message(
                        f"⛔ Reversal blocked by indicators at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("reversal blocked by indicators", zone_type, zone_price, strategy_mode, trend)
                    continue

                penetration = abs(candle.close - zone_price)
                min_penetration = CHECK_RANGE * point * 1.5
                if penetration < min_penetration:
                    send_telegram_message(
                        f"⛔ Shallow fakeout ignored at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("shallow penetration", zone_type, zone_price, strategy_mode, trend)
                    continue

                # require M5 to agree with counter-trend reversal and pass is_fast flag
                if not m5_agrees_with_entry(reverse_side, trend_type="counter_trend", is_fast_zone=is_fast):
                    send_telegram_message(
                        f"⛔ Skipped reversal: M5 disagrees with {reverse_side.upper()} at {zone_label} zone {zone_price:.2f}"
                    )
                    log_rejection("M5 blocks reversal", zone_type, zone_price, strategy_mode, trend)
                    continue

                entry = candle.close
                sl = (max(candle.high, prev_candle.high) + SL_BUFFER * point) if zone_type == "demand" else (
                    min(candle.low, prev_candle.low) - SL_BUFFER * point
                )
                tp = entry - TP_RATIO * (sl - entry) if zone_type == "demand" else (
                    entry + TP_RATIO * (entry - sl)
                )
                send_telegram_message(
                    f"🔄 False breakout reversal at {zone_label} zone {zone_price:.2f} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot_size:.3f}"
                )
                signals.append({
                    "side": reverse_side,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "zone": zone_price,
                    "lot": lot_size,
                    "reason": "false breakout",
                    "strategy": strategy_mode
                })

    return signals, flipped_zones
